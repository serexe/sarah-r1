"""Offline production bridge/runtime/HTTP regressions. No live HA/provider/audio."""
import asyncio
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
import httpx
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bridge.core import Store
from bridge.ha import HADispatcher, TOOLS, validate
from bridge.server import make_app
from test_runtime import runtime, Stream


class FullHA(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'state.db')
        self.store.provision('one', 'a'*48)
        self.headers = {'Authorization':'Bearer '+'a'*48}
        self.conversation = self.store.conversation('one')
        self.requests = []; self.payloads = []; self.wire = []; self.spoken = []
        self.room = 'light.actual_lounge'
        self.members = ['light.alpha', 'light.beta']
        self.rows = {e:{'entity_id':e, 'state':'on', 'attributes':{'friendly_name':e}} for e in self.members}
        self.rows[self.room] = {'entity_id':self.room, 'state':'on', 'attributes':{
            'friendly_name':'Living Room', 'entity_id':self.members.copy(), 'is_hue_group':True, 'hue_type':'room'}}
        self.rows['climate.study'] = {'entity_id':'climate.study', 'state':'heat', 'attributes':{'temperature':20}}
        self.services = [{'domain':'light', 'services':{'turn_off':{}, 'turn_on':{}}},
                         {'domain':'climate', 'services':{'set_temperature':{'fields':{'temperature':{}}}}},
                         {'domain':'script', 'services':{'calculate':{'response':{'optional':False}}}}]
        self.failpost = False; self.mismatch = False; self.change_members = False
        async def ha(request):
            self.assertEqual(request.headers['Authorization'], 'Bearer synthetic-ha')
            self.requests.append((request.method, request.path_qs))
            if request.path == '/api/services': return web.json_response(self.services)
            if request.path == '/api/states': return web.json_response(list(self.rows.values()))
            if request.method == 'GET':
                row = self.rows.get(request.path.rsplit('/',1)[1])
                return web.json_response(row) if row else web.Response(status=404)
            data = await request.json(); self.payloads.append(data)
            if self.failpost: return web.Response(status=503, text='synthetic secret must not leak')
            service = request.path.rsplit('/',1)[1]
            if service == 'turn_off':
                self.rows[self.room]['state'] = 'off'
                for e in self.members: self.rows[e]['state'] = 'off'
                if self.mismatch: self.rows[self.members[0]]['state'] = 'on'
                if self.change_members: self.rows[self.room]['attributes']['entity_id'] = [self.members[0]]
            if service == 'set_temperature': self.rows['climate.study']['attributes']['temperature'] = data['temperature']
            return web.json_response({'service_response':{'answer':42}} if request.query_string else [])
        app = web.Application(); app.router.add_route('*','/{rest:.*}',ha)
        self.ha = TestServer(app); await self.ha.start_server()
        self.dispatcher = HADispatcher(str(self.ha.make_url('')).rstrip('/'), 'synthetic-ha', [('light','turn_on','light.old_bulb')])
        self.dispatcher.convergence_seconds=.25
        self.dispatcher.convergence_interval=.002
        adapter,_ = runtime(); self.adapter = adapter
        self.transcript = 'Please make the living room dark.'
        adapter.transcribe = lambda _: self.transcript
        async def speak(text,path): self.spoken.append(text); path.write_bytes(b'no audio')
        adapter.speak = speak
        self.calls = []; self.prose = 'A thoughtful conversation.'
        original = httpx.AsyncClient; owner = self
        class Wire(httpx.AsyncBaseTransport):
            def __init__(self): self.raw = httpx.AsyncHTTPTransport()
            async def handle_async_request(self,request):
                if request.url.host != 'chatgpt.com': return await self.raw.handle_async_request(request)
                payload = json.loads(request.content); owner.wire.append(payload)
                count = sum(i.get('type') == 'function_call_output' for i in payload['input'])
                if count < len(owner.calls):
                    name,args = owner.calls[count]
                    call = {'type':'function_call','call_id':'call-'+str(count),'name':name,'arguments':json.dumps(args)}
                    events = [{'type':'response.completed','response':{'output':[call]}}]
                else: events = [{'type':'response.output_text.delta','delta':owner.prose},{'type':'response.completed'}]
                return httpx.Response(200,stream=Stream([('data: '+json.dumps(e)+'\n\n').encode() for e in events]))
            async def aclose(self): await self.raw.aclose()
        self.patch = patch('httpx.AsyncClient',lambda **kw: original(transport=Wire(),**kw)); self.patch.start()
        self.client = TestClient(TestServer(make_app(self.store,adapter,self.dispatcher))); await self.client.start_server()
        b = io.BytesIO()
        with wave.open(b,'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\0\0'*8000)
        self.wav = b.getvalue()

    async def asyncTearDown(self):
        await self.client.close(); await self.ha.close(); self.patch.stop(); self.store.close(); self.tmp.cleanup()

    async def submit(self,key='request'):
        response = await self.client.post('/v1/turns',data=self.wav,headers={**self.headers,
            'Content-Type':'audio/wav','X-Conversation':self.conversation,'Idempotency-Key':key})
        self.assertEqual(response.status,202); turn = (await response.json())['turn']
        async with asyncio.timeout(5):
            while True:
                row = await (await self.client.get('/v1/turns/'+turn,headers=self.headers)).json()
                if row['state'] in ('done','error','confirming','cancelled'): return row
                await asyncio.sleep(.025)

    def action(self,domain='light',service='turn_off',entity=None,data=None):
        return ('ha_call_service',{'domain':domain,'service':service,'entity_id':entity or self.room,'data':data or {}})

    async def test_discovery_room_action_and_dedupe(self):
        self.calls = [('ha_list_entities',{'domain':'light','area':'living room'}),
                      ('ha_get_state',{'entity_id':self.room}), ('ha_list_services',{'domain':'light'}),
                      self.action(), self.action()]
        row = await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertIn('State verified.',row['detail'])
        self.assertIn('already claimed',row['detail'])
        self.assertEqual(self.payloads,[{'entity_id':self.room}])
        self.assertTrue(all(any(p == '/api/states/'+e for _,p in self.requests) for e in self.members))
        outputs = [json.loads(i['output']) for i in self.wire[1]['input'] if i.get('type') == 'function_call_output']
        self.assertEqual(outputs[0]['entities'][0]['entity_id'],self.room)
        self.assertEqual({t['name'] for t in self.wire[0]['tools']},
            {t['name'] for t in __import__('bridge.ha',fromlist=['TOOLS']).TOOLS+__import__('bridge.siyuan',fromlist=['TOOLS']).TOOLS+__import__('bridge.calendar',fromlist=['TOOLS']).TOOLS+__import__('bridge.tvtime',fromlist=['TOOLS']).TOOLS})
        duplicate = await self.submit()
        self.assertEqual(duplicate['id'],row['id']); self.assertEqual(len(self.payloads),1)
        self.assertEqual(self.spoken,[row['detail']])

    async def test_other_domain_parameters_and_detailed_state(self):
        self.calls = [self.action('climate','set_temperature','climate.study','{"temperature":22.5,"hvac_mode":"heat"}'),
                      ('ha_get_state',{'entity_id':'climate.study'})]
        row = await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertEqual(self.payloads,[{'entity_id':'climate.study','temperature':22.5,'hvac_mode':'heat'}])
        self.assertNotIn('{',row['detail'])
        self.assertIn('22.5',self.wire[-1]['input'][-1]['output'])
        self.assertNotIn('State verified.',row['detail'])

    async def test_unsupported_service_truthful_error_no_post(self):
        self.calls = [self.action('climate','invented','climate.study')]
        row = await self.submit()
        self.assertIn('ha_service_unavailable',row['detail'])
        self.assertEqual(self.payloads,[])
        self.assertNotIn('State verified.',row['detail'])

    async def test_failed_post_no_retry_or_model_success(self):
        self.failpost = True; self.calls = [self.action(),self.action()]; self.prose = 'It definitely worked.'
        row = await self.submit()
        self.assertIn('Outcome not verified. No automatic retry.',row['detail'])
        self.assertNotIn(self.prose,row['detail']); self.assertNotIn('synthetic secret',row['detail'])
        self.assertEqual(len(self.payloads),1)

    async def test_dynamic_room_mismatch_and_membership_change_not_verified(self):
        for flag in ('mismatch','change_members'):
            setattr(self,flag,True); self.calls = [self.action()]
            row = await self.submit(flag)
            self.assertNotIn('State verified.',row['detail'])
            setattr(self,flag,False)
            self.rows[self.room]['attributes']['entity_id'] = self.members.copy()

    async def test_free_conversation_and_context_always_tools_no_approval(self):
        first = await self.submit(); self.transcript = 'And what about kindness?'
        second = await self.submit('followup')
        self.assertEqual(first['detail'],self.prose); self.assertEqual(second['detail'],self.prose)
        self.assertEqual(self.requests,[])
        self.assertEqual(len(self.wire[-1]['tools']),18)
        self.assertEqual(self.wire[-1]['tool_choice'],'auto')
        self.assertEqual(self.wire[-1]['input'][0]['content'],'Please make the living room dark.')
        self.assertNotIn('confirmation',second)
        self.assertEqual((await self.client.get('/v1/health')).status,403)

    async def test_response_only_service_no_entity(self):
        self.calls = [('ha_call_service',{'domain':'script','service':'calculate','data':'{}'})]
        row = await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertIn(('POST','/api/services/script/calculate?return_response'),self.requests)
        self.assertNotIn('{',row['detail'])
        self.assertIn('42',self.wire[-1]['input'][-1]['output'])
        self.assertNotIn('State verified.',row['detail'])

    async def test_equivalent_json_target_dedupes_and_legacy_allowlist_not_gate(self):
        # Same action serialized two ways must have one durable identity.
        self.calls = [self.action(), ('ha_call_service',{'domain':'light','service':'turn_off',
                      'data':json.dumps({'entity_id':self.room})})]
        row = await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertEqual(len(self.payloads),1)
        self.assertIn('already claimed',row['detail'])

    async def test_area_selector_and_nested_service_data_not_rewritten(self):
        data = {'area_id':'study','temperature':23,'nested':{'values':[1,2], 'enabled':True}}
        self.calls = [('ha_call_service',{'domain':'climate','service':'set_temperature','data':json.dumps(data)})]
        row = await self.submit()
        self.assertEqual(row['state'],'done',row)
        self.assertEqual(self.payloads,[data])
        self.assertIn('service accepted',row['detail'])
        self.assertIn('Outcome not verified.',row['detail'])
        self.assertNotIn('State verified.',row['detail'])

    async def test_group_brightness_checks_every_discovered_member(self):
        # HA accepted a turn_on request, but one bulb's brightness does not match.
        for row in self.rows.values(): row['attributes']['brightness'] = 102
        self.rows[self.members[0]]['attributes']['brightness'] = 255
        self.calls = [self.action(service='turn_on',data={'brightness_pct':40})]
        row = await self.submit()
        self.assertNotIn('State verified.',row['detail'])
        self.assertNotIn('State verified.',row['detail'])
        self.assertEqual(len(self.payloads),1)

    async def test_no_shell_or_url_tool_and_path_validation(self):
        self.calls = [('terminal',{'command':'id'})]
        row = await self.submit()
        self.assertIn('ha_tool_denied',row['detail']); self.assertEqual(self.requests,[])
        from bridge.core import Denied
        for value in ('../states','https://untrusted.example.invalid','light/x'):
            with self.assertRaises(Denied): validate('ha_call_service',{'domain':value,'service':'turn_on','data':{}})

# Imports above are fixture helpers, not additional TestCases.
