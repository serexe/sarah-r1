"""Offline production-runtime regressions. Synthetic pool, transport, and children only."""
import asyncio
import inspect
import io
import json
import signal
import sys
import tempfile
import threading
import time
import unittest
import wave
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from aiohttp.test_utils import TestClient, TestServer
from bridge import runtime as module
from bridge.core import Store
from bridge.runtime import VoiceRuntime
from bridge.server import make_app


from bridge.acp_client import ACPClient, ACPConfig, ACPError
from bridge.acp_runtime import ACPRuntime, create_runtime


class ACPTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(Path('/opt/hermes-agent').is_dir(), 'optional installed Hermes composition fixture unavailable')
    async def test_installed_composition_scope_and_dispatch(self):
        import subprocess
        import os
        script = '''
import asyncio,sys,json
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,'/opt/hermes-agent')
from bridge.acp_launcher import compose, REVIEWED_SOUL
from bridge.acp_policy import NAMES, SCHEMAS
from hermes_state import SessionDB
from hermes_cli.config import _ensure_default_soul_md
from hermes_cli.default_soul import is_legacy_template_soul
async def main():
 home=Path(sys.argv[1])
 assert not is_legacy_template_soul(REVIEWED_SOUL.decode())
 (home/'SOUL.md').write_bytes(REVIEWED_SOUL)
 for _ in range(2):
  _ensure_default_soul_md(home)
  assert (home/'SOUL.md').read_bytes()==REVIEWED_SOUL
 db=SessionDB(db_path=Path(sys.argv[1])/'state.db')
 resolver=lambda **kw: {'provider':'openai-codex','api_mode':'codex_responses','base_url':'https://chatgpt.com/backend-api/codex','api_key':'offline-placeholder'}
 server=compose(asyncio.get_running_loop(),db,resolver)
 state=server.session_manager.create_session(cwd=sys.argv[1])
 assert state.agent.valid_tool_names==NAMES
 assert state.agent.skip_context_files is True
 assert state.agent.load_soul_identity is False
 assert state.agent._memory_store is None
 assert not state.agent._memory_enabled and not state.agent._user_profile_enabled
 assert (home/'SOUL.md').read_bytes()==REVIEWED_SOUL
 for name in ['terminal','read_file','browser_navigate','delegate_task','execute_code','unknown']:
  try: state.agent._execute_tool_calls(NS(tool_calls=[NS(function=NS(name=name))]))
  except ValueError as e: assert str(e)=='acp_scoped_tool_denied'
  else: raise AssertionError(name)
 calls=[]
 class Conn:
  async def ext_method(self,method,params):
   calls.append((method,params));return {'reply':'offline receipt'}
 server._conn=Conn();state.is_running=True
 from model_tools import handle_function_call
 result=await asyncio.to_thread(handle_function_call,'ha_get_state',{'entity_id':'light.test'},state.session_id,enabled_tools=list(NAMES),enabled_toolsets=['sarah_bridge'])
 assert len(calls)==1, result
 assert calls[0][0]=='sarah/dispatch'
 state.is_running=False
 server2=compose(asyncio.get_running_loop(),db,resolver)
 restored=server2.session_manager.get_session(state.session_id)
 assert restored.session_id==state.session_id and restored.agent.session_id==state.session_id
 try: await server2.load_session(sys.argv[1],'missing')
 except ValueError: pass
 else: raise AssertionError('missing load accepted')
 # Actual installed SDK wire path. Fake only conversation/model boundary.
 import socket,acp,contextlib
 from bridge.acp_client import ACPClient
 from bridge.acp_policy import identity
 left,right=socket.socketpair()
 ar,aw=await asyncio.open_connection(sock=left)
 cr,cw=await asyncio.open_connection(sock=right)
 wire_server=compose(asyncio.get_running_loop(),db,resolver)
 serving=asyncio.create_task(acp.run_agent(wire_server,input_stream=aw,output_stream=ar))
 client=ACPClient(cr,cw)
 assert (await client.initialize())['loadSession']
 assert (await client.request('_sarah/policy',{}))['policy']==identity()
 session=(await client.request('session/new',{'cwd':sys.argv[1],'mcpServers':[]}))['sessionId']
 wired=wire_server.session_manager.get_session(session)
 def fake_conversation(**kw):
  call=NS(id='offline_call',function=NS(name='ha_get_state',arguments='{"entity_id":"light.test"}'))
  messages=[{'role':'user','content':kw['user_message']},{'role':'assistant','content':None,'tool_calls':[{'id':'offline_call','type':'function','function':{'name':'ha_get_state','arguments':'{"entity_id":"light.test"}'}}]}]
  wired.agent._execute_tool_calls(NS(tool_calls=[call]),messages,session,1)
  messages.append({'role':'assistant','content':'offline response'})
  wired.agent._flush_messages_to_session_db(messages,kw['conversation_history'])
  return {'final_response':'offline response','messages':messages}
 wired.agent.run_conversation=fake_conversation
 receipts=[]
 async def owner(name,args):
  receipts.append((name,args));return {'reply':'server-owned receipt'}
 client.dispatch=owner
 assert await client.prompt(session,'offline prompt')=='offline response'
 assert receipts==[('ha_get_state',{'entity_id':'light.test'})]
 await client.close()
 serving.cancel()
 with contextlib.suppress(asyncio.CancelledError): await serving
 aw.close()
 assert db.get_messages_as_conversation(session)[-1]['content']=='offline response'
 print('SDK WIRE PASS: policy, explicit scoped request, turn owner, persisted history')
 print('BOOTSTRAP PASS: installed seed preserves exact non-legacy sentinel; context, soul identity, memory disabled')
 print('INSTALLED PASS',sorted(NAMES))
 print('EFFECTIVE_SCHEMAS',json.dumps(state.agent.tools))
asyncio.run(main())
'''
        with tempfile.TemporaryDirectory() as home:
            import shutil
            shutil.copyfile('bridge/sarah-acp.yaml', Path(home)/'config.yaml')
            result = subprocess.run([sys.executable, '-B', '-c', script, home],
                env={'HOME':home,'HERMES_HOME':home,'PATH':'/usr/bin:/bin'},
                capture_output=True,text=True,timeout=25)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            print(result.stdout)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'state.db')
        self.store.provision('a', 'a' * 48)
        self.store.provision('b', 'b' * 48)
        self.conversation = self.store.conversation('a')
        # Synthetic installed source identity; never depend on operator installation.
        self.source_patch = patch.object(ACPConfig, 'identity', new_callable=__import__('unittest.mock', fromlist=['PropertyMock']).PropertyMock)
        self.source_identity = self.source_patch.start()
        from bridge.acp_policy import identity
        self.source_identity.side_effect = lambda: __import__('bridge.acp_policy', fromlist=['identity']).identity()
        self.config = ACPConfig(cwd=self.tmp.name)
        self.calls = []
        self.clients = []
        self.stall = False
        self.disconnect_prompt = False
        self.bad_policy = False
        self.entered = asyncio.Event()

    def tearDown(self):
        self.source_patch.stop()
        self.store.close()
        self.tmp.cleanup()

    async def connect(self, config):
        reader = asyncio.StreamReader(limit=ACPClient.LINE_BYTES)
        owner = self
        class Writer:
            closed = False
            def frame(self, value):
                reader.feed_data((json.dumps({'jsonrpc': '2.0', **value}) + '\n').encode())
            def write(self, data):
                frame = json.loads(data)
                owner.calls.append(frame)
                method = frame.get('method')
                if method == 'initialize':
                    result = {'protocolVersion': 1, 'agentCapabilities': {'loadSession': True}}
                elif method == '_sarah/policy':
                    from bridge.acp_policy import identity, SCHEMAS
                    result = {'policy': 'wrong' if owner.bad_policy else identity(), 'schemas': SCHEMAS}
                elif method == 'session/new':
                    result = {'sessionId': 'synthetic-' + str(len(owner.clients))}
                elif method == 'session/load':
                    # History updates must not be spoken as new assistant output.
                    self.frame({'method': 'session/update', 'params': {'sessionId': frame['params']['sessionId'],
                        'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'old history'}}}})
                    result = {}
                elif method == 'session/prompt':
                    owner.entered.set()
                    if owner.disconnect_prompt:
                        reader.feed_eof()
                        return
                    if owner.stall:
                        return
                    self.frame({'method': 'session/update', 'params': {'sessionId': frame['params']['sessionId'],
                        'update': {'sessionUpdate': 'agent_message_chunk', 'content': {'type': 'text', 'text': 'hello'}}}})
                    result = {'stopReason': 'end_turn'}
                else:
                    return
                self.frame({'id': frame['id'], 'result': result})
            async def drain(self): pass
            def close(self): self.closed = True
            async def wait_closed(self): pass
        client = ACPClient(reader, Writer())
        self.clients.append(client)
        return client

    def adapter(self):
        return ACPRuntime(self.store, '/not-used', self.config)

    async def bound(self, adapter=None, device='a', conversation=None, history=()):
        return await (adapter or self.adapter())._reply_bound('hello', history,
            device=device, conversation=conversation or self.conversation)

    async def test_durable_load_and_device_isolation(self):
        with patch.object(ACPClient, 'connect', self.connect):
            self.assertEqual(await self.bound(), 'hello')
            self.store.close()
            self.store = Store(Path(self.tmp.name) / 'state.db')
            self.assertEqual(await self.bound(history=[{'role': 'assistant', 'content': 'hello'}]), 'hello')
            other = self.store.conversation('b')
            self.assertEqual(await self.bound(device='b', conversation=other), 'hello')
            with self.assertRaisesRegex(ValueError, 'not_found'):
                await self.bound(device='b')
        methods = [c.get('method') for c in self.calls]
        self.assertEqual(methods.count('session/new'), 2)
        self.assertEqual(methods.count('session/load'), 1)
        sessions = self.store.db.execute('SELECT session FROM acp_sessions').fetchall()
        self.assertEqual(len({r['session'] for r in sessions}), 2)
        self.assertTrue(all(c.writer.closed for c in self.clients))

    async def test_permission_and_client_execution_denied(self):
        client = await self.connect(self.config)
        await client.handle_agent({'method': 'session/request_permission', 'id': 'permission'})
        await client.handle_agent({'method': 'terminal/create', 'id': 'exec'})
        self.assertEqual(self.calls[-2]['result'], {'outcome': {'outcome': 'cancelled'}})
        self.assertEqual(self.calls[-1]['error']['code'], -32601)
        await client.close()

    async def test_public_timezone_only_nonsecret_child_configuration(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from bridge.calendar import ZONE
        process = SimpleNamespace(stdout=object(), stdin=object())
        spawn = AsyncMock(return_value=process)
        with patch('bridge.acp_client.asyncio.create_subprocess_exec', spawn):
            client = await ACPClient.connect(self.config)
        self.assertIs(client.process, process)
        env = spawn.call_args.kwargs['env']
        self.assertEqual(set(env), {'HOME', 'PATH', 'LANG', 'R1_TIMEZONE'})
        self.assertEqual(env['R1_TIMEZONE'], ZONE)
        self.assertEqual(spawn.call_args.args, self.config.command)

    async def test_dispatch_requires_current_session_policy_and_allowlist(self):
        from bridge.acp_policy import identity
        client = await self.connect(self.config)
        seen = []
        async def dispatch(name, args):
            seen.append((name,args));return {'reply':'actual owner output'}
        client.dispatch = dispatch
        client.session_id = 'bound'
        request = {'method':'_sarah/dispatch','id':'tool','params':{
            'sessionId':'bound','policy':identity(),'name':'ha_get_state',
            'arguments':{'entity_id':'light.test'}}}
        with self.assertRaisesRegex(ACPError,'acp_dispatch_binding_denied'):
            await client.handle_agent(request)
        client.collecting = True
        for key,value in [('sessionId','wrong'),('policy','wrong')]:
            bad = {**request,'params':{**request['params'],key:value}}
            with self.assertRaisesRegex(ACPError,'acp_dispatch_binding_denied'):
                await client.handle_agent(bad)
        with self.assertRaisesRegex(ValueError,'acp_scoped_tool_denied'):
            await client.handle_agent({**request,'params':{**request['params'],'name':'terminal'}})
        self.assertEqual(seen,[])
        await client.handle_agent(request)
        self.assertEqual(seen,[('ha_get_state',{'entity_id':'light.test'})])
        self.assertEqual(self.calls[-1]['result'],{'reply':'actual owner output'})
        await client.close()

    async def test_transport_loss_and_restart_never_replay(self):
        self.disconnect_prompt = True
        with patch.object(ACPClient, 'connect', self.connect):
            with self.assertRaisesRegex(ACPError, 'acp_disconnected'):
                await self.bound()
            self.store.close()
            self.store = Store(Path(self.tmp.name) / 'state.db')
            with self.assertRaisesRegex(ACPError, 'acp_session_uncertain_or_changed'):
                await self.bound()
        self.assertEqual(sum(c.get('method') == 'session/prompt' for c in self.calls), 1)
        self.assertTrue(any(c.get('method') == 'session/cancel' for c in self.calls))
        self.assertTrue(self.clients[0].writer.closed)

    async def test_stop_marks_uncertain_closes_and_no_replay(self):
        self.stall = True
        with patch.object(ACPClient, 'connect', self.connect):
            task = asyncio.create_task(self.bound())
            await asyncio.wait_for(self.entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            with self.assertRaisesRegex(ACPError, 'acp_session_uncertain_or_changed'):
                await self.bound()
        self.assertTrue(self.clients[0].writer.closed)
        self.assertEqual(sum(c.get('method') == 'session/prompt' for c in self.calls), 1)
        self.assertTrue(any(c.get('method') == 'session/cancel' for c in self.calls))

    async def test_policy_mismatch_and_changed_binding_fail_closed(self):
        self.bad_policy = True
        with patch.object(ACPClient, 'connect', self.connect):
            with self.assertRaisesRegex(ACPError,'acp_policy_mismatch'):
                await self.bound()
            self.assertFalse(any(c.get('method') in ('session/new','session/prompt') for c in self.calls))
            self.bad_policy = False
            self.assertEqual(await self.bound(),'hello')
        with patch('bridge.acp_policy.identity', return_value='changed'):
            with patch.object(ACPClient,'connect',side_effect=AssertionError('must not reconnect')):
                with self.assertRaisesRegex(ACPError,'acp_session_uncertain_or_changed'):
                    await self.bound()

    async def test_old_history_and_inflight_refused_without_connect(self):
        with patch.object(ACPClient, 'connect', side_effect=AssertionError('must not connect')):
            with self.assertRaisesRegex(ACPError, 'acp_backend_requires_new_conversation'):
                await self.bound(history=[{'role': 'user', 'content': 'old'}])
            self.store.db.execute('INSERT INTO acp_sessions VALUES(?,?,?,?,?)',
                ('a', self.conversation, self.config.identity, 'synthetic', 'inflight'))
            with self.assertRaisesRegex(ACPError, 'acp_session_uncertain_or_changed'):
                await self.bound()

    async def test_inactive_selector_rejects_audio_without_agent(self):
        with patch('bridge.acp_runtime.VoiceRuntime') as old:
            create_runtime(self.store, '/not-used')
            old.assert_called_once_with('/not-used')
        # Readiness fixture only; never depend on a live profile's generated files.
        with patch('bridge.acp_launcher.validate_profile'):
            adapter = create_runtime(self.store, '/not-used', 'acp')
            self.assertTrue(adapter.ready)
        adapter = ACPRuntime(self.store, '/not-used', self.config)
        self.assertFalse(adapter.ready)  # Non-dedicated cwd still fails closed.
        with patch.object(ACPClient, 'connect', side_effect=AssertionError('must not connect')):
            with self.assertRaisesRegex(ACPError, adapter.reason):
                await adapter.reply('hello')

            client = TestClient(TestServer(make_app(self.store, adapter, ha=object(), siyuan=object(),
                                                     calendar=object(), tvtime=object())))
            await client.start_server()
            try:
                health = await client.get('/v1/health', headers={'Authorization': 'Bearer ' + 'a' * 48})
                state = await health.json()
                self.assertFalse(state['ready'])
                self.assertFalse(state['tools'])
                self.assertIn(adapter.reason, state['reason'])
                self.assertTrue(all(state[k] for k in ('home_assistant', 'siyuan', 'calendar', 'tvtime')))
                response = await client.post('/v1/turns', data=b'no audio admitted',
                    headers={'Authorization': 'Bearer ' + 'a' * 48, 'Content-Type': 'audio/wav'})
                self.assertEqual(response.status, 503)
                self.assertEqual((await response.json())['error'], adapter.reason)
                self.assertEqual(self.store.db.execute('SELECT count(*) FROM turns').fetchone()[0], 0)
            finally: await client.close()

    async def test_reviewed_bootstrap_profile_fails_closed(self):
        from bridge import acp_launcher
        profile = Path(self.tmp.name)/'profile'
        profile.mkdir()
        config = profile/'config.yaml'
        reviewed_config = Path('bridge/sarah-acp.yaml').read_bytes()
        config.write_bytes(reviewed_config)
        soul = profile/'SOUL.md'
        soul.write_bytes(acp_launcher.REVIEWED_SOUL)
        scoped = ACPConfig(cwd=str(profile/'workspace'))
        with patch.object(acp_launcher, 'PROFILE', profile):
            def check(accepted):
                if accepted:
                    acp_launcher.validate_profile()
                else:
                    with self.assertRaises((ValueError, OSError)):
                        acp_launcher.validate_profile()
                self.assertEqual(ACPRuntime(self.store, '/not-used', scoped).ready, accepted)
            check(True)
            # Includes installed default identity, not merely arbitrary text.
            seeded = b'Synthetic default persona; not reviewed inert bootstrap.'
            for content in (seeded, b'', b'arbitrary identity', acp_launcher.REVIEWED_SOUL+b'\n'):
                with self.subTest(content=content[:32]):
                    soul.write_bytes(content)
                    check(False)
                    self.assertEqual(soul.read_bytes(), content)  # No repair/delete at launch.
            soul.unlink()
            check(False)
            target = profile/'sentinel-target'
            target.write_bytes(acp_launcher.REVIEWED_SOUL)
            soul.symlink_to(target)
            check(False)
            soul.unlink()
            soul.write_bytes(acp_launcher.REVIEWED_SOUL)
            for name in ('.env', 'AGENTS.md'):
                path = profile/name
                path.write_bytes(b'')
                check(False)
                path.unlink()
                path.symlink_to(profile/'missing')
                check(False)
                path.unlink()
            config.write_bytes(reviewed_config+b'\n')
            check(False)
            config.write_bytes(reviewed_config)
            check(True)


DONE = (b'data: {"type":"response.output_text.delta","delta":"hello"}\n\n'
        b'data: {"type":"response.completed"}\n\n')


class Stream(httpx.SyncByteStream, httpx.AsyncByteStream):
    def __init__(self, chunks=(DONE,), delay=0.0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            time.sleep(self.delay)
            yield chunk

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    def close(self):
        self.closed = True

    async def aclose(self):
        self.closed = True


def runtime():
    # Bypass constructor: never import Hermes auth or load any credentials/models.
    adapter = VoiceRuntime.__new__(VoiceRuntime)
    entry = SimpleNamespace(runtime_api_key='synthetic', runtime_base_url=module.BASE,
                            provider='openai-codex', id='synthetic-entry')
    rotations = []

    def rotate(**kwargs):
        rotations.append(kwargs)
        return entry

    pool = SimpleNamespace(select=lambda: entry, mark_exhausted_and_rotate=rotate)
    adapter.load_pool = lambda provider: pool
    adapter.headers = lambda *args, **kwargs: {}
    return adapter, rotations


class Transport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
        self.clients = []
        self.stack = ExitStack()

    def __enter__(self):
        def handle(request):
            self.requests.append(request)
            status, stream = next(self.responses)
            return httpx.Response(status, stream=stream)
        transport = httpx.MockTransport(handle)
        sync, asynchronous = httpx.Client, httpx.AsyncClient

        def factory(cls, **kwargs):
            client = cls(transport=transport, **kwargs)
            self.clients.append(client)
            return client
        self.stack.enter_context(patch.object(module.httpx, 'Client', lambda **kw: factory(sync, **kw)))
        self.stack.enter_context(patch.object(module.httpx, 'AsyncClient', lambda **kw: factory(asynchronous, **kw)))
        return self

    def __exit__(self, *args):
        return self.stack.__exit__(*args)


async def reply(adapter):
    # Both pre-fix synchronous and repaired asynchronous implementation exercised.
    result = adapter.reply('hello', [{'role': 'assistant', 'content': 'prior'}])
    return await result if inspect.isawaitable(result) else result


class CodexTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_high_and_route_contract(self):
        adapter, _ = runtime()
        stream = Stream()
        with Transport([(200, stream)]) as transport:
            self.assertEqual(await reply(adapter), 'hello')
        request = transport.requests[0]
        payload = json.loads(request.content)
        self.assertEqual(payload['reasoning'], {'effort': 'high'})
        self.assertEqual(payload['model'], 'gpt-6.1-sol')
        self.assertEqual(payload['tools'], [])
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertFalse(payload['store'])
        self.assertTrue(payload['stream'])
        self.assertEqual(str(request.url), module.BASE + '/responses')
        self.assertTrue(stream.closed)
        self.assertTrue(all(client.is_closed for client in transport.clients))

    async def test_heartbeat_total_deadline_closes_upstream(self):
        adapter, _ = runtime()
        stream = Stream([b': heartbeat\n\n'] * 12 + [DONE], delay=0.015)
        with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.05, create=True), Transport([(200, stream)]):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reply(adapter), 1)
            self.assertLess(time.monotonic() - started, 0.18)
        self.assertTrue(stream.closed)

    async def test_stalled_read_deadline_closes_upstream(self):
        adapter, _ = runtime()
        stream = Stream([DONE], delay=0.2)
        with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.04, create=True), Transport([(200, stream)]):
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(reply(adapter), 1)
        self.assertTrue(stream.closed)

    async def test_deadline_spans_pool_rotation_attempts(self):
        adapter, rotations = runtime()
        streams = [Stream([b'rejected'], delay=0.03) for _ in range(3)]
        # Delay response headers too, independent of whether error bodies are consumed.
        original = module.httpx.AsyncClient
        with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.05, create=True), Transport([(429, s) for s in streams]) as transport:
            real_send = original.send

            async def delayed_send(client, *args, **kwargs):
                await asyncio.sleep(0.03)
                return await real_send(client, *args, **kwargs)

            with patch.object(original, 'send', delayed_send):
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(reply(adapter), 1)
        self.assertLess(len(transport.requests), 3)
        self.assertEqual(rotations[0], {'status_code': 429, 'api_key_hint': 'synthetic',
                                        'credential_id': 'synthetic-entry'})
        self.assertTrue(streams[0].closed)

    async def test_sse_unterminated_line_is_bounded(self):
        adapter, _ = runtime()
        stream = Stream([b':' + b'a' * 40, b'a' * 40, b'\n\n', DONE])
        with patch.object(module, 'SSE_LINE_BYTES', 64, create=True), Transport([(200, stream)]):
            with self.assertRaisesRegex(RuntimeError, '^codex_sse_line_too_large$'):
                await reply(adapter)
        self.assertTrue(stream.closed)

    async def test_sse_total_bytes_includes_heartbeats(self):
        adapter, _ = runtime()
        stream = Stream([b': heartbeat\n\n'] * 50 + [DONE])
        with patch.object(module, 'SSE_TOTAL_BYTES', 512, create=True), Transport([(200, stream)]):
            with self.assertRaisesRegex(RuntimeError, '^codex_sse_total_too_large$'):
                await reply(adapter)
        self.assertTrue(stream.closed)

    async def test_real_loopback_socket_closed_on_deadline(self):
        # Real HTTPX I/O, rerouted only by test transport. No provider contacted.
        for mode in ('headers_stall', 'body_stall', 'heartbeat'):
            with self.subTest(mode=mode):
                adapter, _ = runtime()
                closed = asyncio.Event()
                handlers = set()

                async def upstream(reader, writer):
                    handlers.add(asyncio.current_task())
                    sender = None
                    try:
                        request = await reader.readuntil(b'\r\n\r\n')
                        length = next(int(line.split(b':', 1)[1]) for line in request.split(b'\r\n')
                                      if line.lower().startswith(b'content-length:'))
                        await reader.readexactly(length)
                        if mode != 'headers_stall':
                            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nConnection: close\r\n\r\n')
                            await writer.drain()
                        if mode == 'heartbeat':
                            async def heartbeats():
                                while True:
                                    writer.write(b': heartbeat\n\n')
                                    await writer.drain()
                                    await asyncio.sleep(0.005)
                            sender = asyncio.create_task(heartbeats())
                        self.assertEqual(await reader.read(), b'')
                        closed.set()
                    finally:
                        if sender:
                            sender.cancel()
                            await asyncio.gather(sender, return_exceptions=True)
                        writer.close()
                        await writer.wait_closed()
                        handlers.discard(asyncio.current_task())

                server = await asyncio.start_server(upstream, '127.0.0.1', 0)
                port = server.sockets[0].getsockname()[1]
                raw = httpx.AsyncHTTPTransport()

                class Loopback(httpx.AsyncBaseTransport):
                    async def handle_async_request(self, request):
                        # Production request still pins original supported URL.
                        if str(request.url) != module.BASE + '/responses':
                            raise AssertionError('unexpected upstream URL')
                        request.url = httpx.URL(f'http://127.0.0.1:{port}/responses')
                        return await raw.handle_async_request(request)

                    async def aclose(self):
                        await raw.aclose()

                client_class = httpx.AsyncClient
                try:
                    with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.08, create=True), \
                         patch.object(module.httpx, 'Client', side_effect=AssertionError('synchronous_upstream_disallowed')), \
                         patch.object(module.httpx, 'AsyncClient', lambda **kw: client_class(transport=Loopback(), **kw)):
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(reply(adapter), 1)
                        await asyncio.wait_for(closed.wait(), 0.5)
                finally:
                    server.close()
                    await server.wait_closed()
                    for task in list(handlers):
                        task.cancel()
                    await asyncio.gather(*handlers, return_exceptions=True)
                    await raw.aclose()

    async def test_completion_closes_without_waiting_for_eof(self):
        adapter, _ = runtime()
        stream = Stream([DONE, b': never needed\n\n'], delay=0.03)
        with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.05, create=True), Transport([(200, stream)]):
            self.assertEqual(await reply(adapter), 'hello')
        self.assertTrue(stream.closed)

    async def test_rotation_keeps_issuing_identity_and_no_fallback(self):
        adapter, rotations = runtime()
        streams = [Stream(), Stream()]
        with Transport([(429, streams[0]), (200, streams[1])]):
            self.assertEqual(await reply(adapter), 'hello')
        self.assertEqual(rotations, [{'status_code': 429, 'api_key_hint': 'synthetic',
                                     'credential_id': 'synthetic-entry'}])
        self.assertTrue(all(s.closed for s in streams))

    async def test_http_expiry_terminal_and_next_admission(self):
        await self.http_expiry()

    async def test_stop_http_stream_closes_before_worker_reuse(self):
        await self.http_expiry(cancelled=True)

    async def http_expiry(self, cancelled=False):
        adapter, _ = runtime()
        adapter.transcribe = lambda path: 'synthetic transcript'

        async def speak(text, path):
            pass
        adapter.speak = speak
        streams = [Stream([b': heartbeat\n\n'] * 30 + [DONE], delay=10 if cancelled else 0.01), Stream()]
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'state.db')
            store.provision('test', 'a' * 48)
            conversation = store.conversation('test')
            client = TestClient(TestServer(make_app(store, adapter)))
            await client.start_server()
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                wav.writeframes(b'\0\0' * 16000)
            headers = {'Authorization': 'Bearer ' + 'a' * 48,
                       'Content-Type': 'audio/wav', 'X-Conversation': conversation}
            try:
                with patch.object(module, 'CODEX_TOTAL_SECONDS', 10 if cancelled else 0.05, create=True), Transport([(200, s) for s in streams]) as transport:
                    for key, expected in [('first', 'error'), ('second', 'done')]:
                        response = await client.post('/v1/turns', data=buf.getvalue(),
                                                     headers={**headers, 'Idempotency-Key': key})
                        self.assertEqual(response.status, 202)
                        turn = (await response.json())['turn']
                        if cancelled and key == 'first':
                            async with asyncio.timeout(1):
                                while store.get('test', turn)['state'] != 'thinking':
                                    await asyncio.sleep(0.001)
                            cancel_response = await client.post('/v1/turns/' + turn + '/cancel',
                                                                json={}, headers={'Authorization': headers['Authorization']})
                            self.assertEqual(cancel_response.status, 200)
                            self.assertEqual((await cancel_response.json())['state'], 'cancelled')
                            async with asyncio.timeout(1):
                                while not streams[0].closed:
                                    await asyncio.sleep(0.005)
                            self.assertTrue(all(c.is_closed for c in transport.clients))
                            self.assertEqual(len(transport.requests), 1)
                            expected = 'cancelled'
                        async with asyncio.timeout(1):
                            while True:
                                result = await (await client.get('/v1/turns/' + turn, headers=headers)).json()
                                if result['state'] in ('error', 'done', 'cancelled'):
                                    break
                                await asyncio.sleep(0.005)
                        self.assertEqual(result['state'], expected)
                        self.assertTrue(streams[0].closed)
                    self.assertEqual(result['detail'], 'hello')
            finally:
                await client.close()
                store.close()

    async def test_stop_native_tts_dispatch_ownership(self):
        # Existing HTTP/runtime seams; native thread + synthetic child are real.
        # No Whisper/Kokoro model, credentials or integration traffic involved.
        for boundary in ('native', 'tts', 'dispatch'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                adapter, _ = runtime()
                started=asyncio.Event(); release=threading.Event(); native_done=threading.Event()
                loop=asyncio.get_running_loop(); children=[]; calls=[]; clips=[]
                first=True

                def transcribe(path):
                    nonlocal first
                    clips.append(path)
                    if first and boundary=='native':
                        first=False
                        loop.call_soon_threadsafe(started.set)
                        try:
                            if not release.wait(3): raise RuntimeError('synthetic_release_timeout')
                            self.assertTrue(path.exists(), 'live native worker lost clip')
                        finally: native_done.set()
                    return 'synthetic transcript'

                async def answer(text, history, dispatch=None):
                    if boundary=='dispatch' and not calls:
                        return (await dispatch('ha_call_service', {}))['reply']
                    return 'normal followup'

                async def dispatch(name, args, claim):
                    self.assertTrue(await claim({'name':name,'arguments':args}))
                    calls.append(name); started.set()
                    await asyncio.Event().wait()

                async def speak(text, path):
                    nonlocal first
                    if first and boundary=='tts':
                        first=False
                        await VoiceRuntime.speak(adapter, text, path)
                    else: path.write_bytes(b'synthetic audio')

                real_spawn=asyncio.create_subprocess_exec
                async def spawn(*args, **kwargs):
                    output=Path(args[args.index('--output')+1])
                    proc=await real_spawn(sys.executable, '-c',
                        'import pathlib,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                        f'pathlib.Path({str(output)!r}).write_bytes(b"partial"); time.sleep(30)',
                        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                    children.append(proc)
                    while not output.exists(): await asyncio.sleep(0.002)
                    started.set()
                    return proc

                adapter.transcribe=transcribe; adapter.reply=answer; adapter.speak=speak
                store=Store(Path(tmp)/'state.db'); store.provision('test','a'*48)
                conversation=store.conversation('test')
                app=make_app(store,adapter,ha=SimpleNamespace(dispatch=dispatch) if boundary=='dispatch' else None)
                client=TestClient(TestServer(app)); await client.start_server()
                buf=io.BytesIO()
                with wave.open(buf,'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
                    wav.writeframes(b'\0\0'*16000)
                headers={'Authorization':'Bearer '+'a'*48,'Content-Type':'audio/wav',
                         'X-Conversation':conversation,'Idempotency-Key':'first'}
                closing=None
                try:
                    with patch.object(module.asyncio,'create_subprocess_exec',spawn), \
                         patch.object(module,'TTS_TERMINATE_GRACE',0.02):
                        response=await client.post('/v1/turns',data=buf.getvalue(),headers=headers)
                        self.assertEqual(response.status,202); turn=(await response.json())['turn']
                        await asyncio.wait_for(started.wait(),1)
                        expected='uncertain' if boundary=='dispatch' else 'cancelled'
                        for _ in range(2):
                            response=await client.post('/v1/turns/'+turn+'/cancel',json={},headers=headers)
                            self.assertEqual((await response.json())['state'],expected)
                        replay=await client.post('/v1/turns',data=buf.getvalue(),headers=headers)
                        self.assertEqual((await replay.json())['turn'],turn)
                        if boundary=='native':
                            busy=await client.post('/v1/turns',data=buf.getvalue(),headers={**headers,'Idempotency-Key':'busy'})
                            self.assertEqual((await busy.json())['error'],'voice_worker_busy')
                            self.assertFalse(native_done.is_set()); self.assertTrue(clips[0].exists())
                            closing=asyncio.create_task(client.close())
                            await asyncio.sleep(0.02)
                            self.assertFalse(closing.done(), 'cleanup abandoned native owner')
                            release.set(); await asyncio.wait_for(closing,1)
                            self.assertTrue(native_done.is_set()); self.assertFalse(clips[0].exists())
                            # Same app/Store, new synthetic transport after cleanup.
                            client=TestClient(TestServer(app)); await client.start_server()
                        else:
                            async with asyncio.timeout(1):
                                while list((Path(tmp)/'media').iterdir()): await asyncio.sleep(0.002)
                        self.assertFalse((Path(tmp)/'media'/(turn+'.mp3')).exists())
                        self.assertTrue(all(p.returncode is not None for p in children))
                        if boundary=='dispatch':
                            row=store.get('test',turn)
                            self.assertIn('outcome unknown',row['detail'])
                            store.recover(); self.assertEqual(store.get('test',turn),row)
                            blocked=await client.post('/v1/turns',data=buf.getvalue(),headers={**headers,'Idempotency-Key':'blocked'})
                            self.assertEqual((await blocked.json())['error'],'conversation_busy_or_uncertain')
                            self.assertEqual(store.db.execute('SELECT count(*) FROM dispatches').fetchone()[0],1)
                            headers['X-Conversation']=store.conversation('test')
                        response=await client.post('/v1/turns',data=buf.getvalue(),headers={**headers,'Idempotency-Key':'followup'})
                        self.assertEqual(response.status,202); followup=(await response.json())['turn']
                        async with asyncio.timeout(1):
                            while store.get('test',followup)['state']!='done': await asyncio.sleep(0.002)
                        self.assertEqual(store.get('test',followup)['detail'],'normal followup')
                        self.assertEqual(store.get('test',turn)['state'],expected)
                        self.assertEqual(len(calls),1 if boundary=='dispatch' else 0)
                finally:
                    release.set()
                    if closing: await closing
                    await client.close(); store.close()
                    for child in children:
                        if child.returncode is None: child.kill()
                        await child.wait()


class TTSTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, stage, mode, *, fail=False, ignores_term=True):
        adapter, _ = runtime()
        children = []
        real_spawn = asyncio.create_subprocess_exec
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'reply.mp3'
            ready = asyncio.Event()

            async def factory(*args, **kwargs):
                current = 'encode' if args[0] == '/usr/bin/ffmpeg' else 'speech'
                output = Path(args[-1]) if current == 'encode' else Path(args[args.index('--output') + 1])
                hangs = current == stage
                code = ('import pathlib,signal,time; '
                        f'signal.signal(signal.SIGTERM,signal.{"SIG_IGN" if ignores_term else "SIG_DFL"}); '
                        f'pathlib.Path({str(output)!r}).write_bytes(b"partial"); '
                        + ('time.sleep(30)' if hangs else ''))
                if fail and hangs:
                    code = code.replace('time.sleep(30)', 'raise SystemExit(7)')
                proc = await real_spawn(sys.executable, '-c', code,
                                        stdin=asyncio.subprocess.PIPE,
                                        stdout=asyncio.subprocess.DEVNULL,
                                        stderr=asyncio.subprocess.DEVNULL)
                children.append(proc)
                if hangs:
                    # Child has installed SIGTERM handler and written partial output.
                    while not output.exists():
                        await asyncio.sleep(0.002)
                    ready.set()
                    if mode == 'spawn_cancel':
                        # Cancellation between process creation and handle return.
                        await asyncio.sleep(0.03)
                return proc

            task = None
            try:
                with patch.object(module.asyncio, 'create_subprocess_exec', factory), \
                     patch.object(module, 'TTS_STAGE_SECONDS', 0.08, create=True), \
                     patch.object(module, 'TTS_TERMINATE_GRACE', 0.02, create=True):
                    task = asyncio.create_task(adapter.speak('synthetic text', target))
                    if mode in ('cancel', 'spawn_cancel', 'repeat_cancel'):
                        await asyncio.wait_for(ready.wait(), 1)
                        self.assertFalse(target.exists(), 'in-progress audio published')
                        task.cancel()
                        if mode == 'repeat_cancel':
                            await asyncio.sleep(0.005)
                            task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await task
                    elif mode == 'success':
                        await task
                    elif fail:
                        with self.assertRaisesRegex(RuntimeError, '^tts_encoding_failed$'):
                            await task
                    else:
                        # Pre-fix outer timeout returns with child still alive.
                        with self.assertRaises(TimeoutError):
                            await asyncio.wait_for(task, 0.3)
                self.assertTrue(children)
                self.assertTrue(all(child.returncode is not None for child in children),
                                'TTS returned while subprocess remains alive')
                if mode == 'success':
                    self.assertEqual(target.read_bytes(), b'partial')  # Synthetic child output, not real MP3.
                    self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(list(Path(tmp).iterdir()), [target])
                else:
                    if not fail:
                        expected = signal.SIGKILL if ignores_term else signal.SIGTERM
                        self.assertEqual(children[-1].returncode, -expected)
                    self.assertFalse(target.exists(), 'partial audio published')
                    self.assertEqual(list(Path(tmp).iterdir()), [], 'temporary audio leaked')
            finally:
                if task and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                # Keep intentionally failing pre-fix probes harmless.
                for child in children:
                    if child.returncode is None:
                        child.kill()
                    await child.wait()

    async def test_speech_deadline_kills_reaps(self):
        await self.probe('speech', 'timeout')

    async def test_encoder_deadline_kills_reaps_no_partial(self):
        await self.probe('encode', 'timeout')

    async def test_speech_cancellation_kills_reaps(self):
        await self.probe('speech', 'cancel')

    async def test_encoder_cancellation_kills_reaps_no_partial(self):
        await self.probe('encode', 'cancel')

    async def test_encoder_failure_does_not_publish_partial(self):
        await self.probe('encode', 'failure', fail=True)

    async def test_spawn_cancellation_retains_handle_and_reaps(self):
        await self.probe('speech', 'spawn_cancel')

    async def test_repeated_cancellation_does_not_interrupt_reap(self):
        await self.probe('encode', 'repeat_cancel')

    async def test_graceful_termination_reaps(self):
        await self.probe('speech', 'cancel', ignores_term=False)

    async def test_success_publishes_only_final_private_audio(self):
        await self.probe(None, 'success')


if __name__ == '__main__':
    unittest.main()
