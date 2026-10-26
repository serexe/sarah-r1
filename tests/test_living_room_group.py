"""Offline room mapping/readback regression; no provider or live HA traffic."""
import unittest
from unittest.mock import AsyncMock
from bridge.ha import HADispatcher, TOOLS, validate
from bridge.core import Denied
from test_ha_slice import Slice

ROOM = 'light.example_room_group'
MEMBERS = ('light.example_bulb_b', 'light.example_bulb_a', 'light.example_bulb_d', 'light.example_bulb_c')

class GroupReadback(unittest.IsolatedAsyncioTestCase):
    def fixture(self, service='turn_off', states=None, membership=MEMBERS, brightness=102):
        self.posts = []
        self.reads = []
        dispatcher = HADispatcher('http://127.0.0.1', 'offline-only', [('light', service, ROOM)])
        async def request(method, path, data=None):
            if method == 'POST':
                self.posts.append((path, data)); return []
            if path=='/api/services': return [{'domain':'light','services':{'turn_off':{},'turn_on':{}}}]
            entity = path.rsplit('/', 1)[1]; self.reads.append(entity)
            attrs = {'entity_id':list(membership), 'is_hue_group':True, 'hue_type':'room'} if entity == ROOM else {}
            attrs |= {'brightness':brightness, 'supported_color_modes':['brightness']}
            state = (states or {}).get(entity, 'on' if service == 'turn_on' else 'off')
            if isinstance(state, Exception): raise state
            return {'entity_id':entity, 'state':state, 'attributes':attrs}
        dispatcher._request = request
        return dispatcher

    async def action(self, dispatcher, service='turn_off', data=None):
        return await dispatcher.dispatch('ha_call_service', {'domain':'light', 'service':service,
            'entity_id':ROOM, 'data':data or {}}, AsyncMock(return_value=True))

    async def test_exact_room_target_and_all_members_verified(self):
        dispatcher = self.fixture()
        result = await self.action(dispatcher)
        self.assertEqual(self.posts, [('/api/services/light/turn_off', {'entity_id':ROOM})])
        self.assertEqual(self.reads, [ROOM, *MEMBERS, ROOM, *MEMBERS])
        self.assertTrue(result['verified'], result)
        self.assertEqual({r['entity_id'] for r in result['states'][0]['members']}, set(MEMBERS))
        self.assertIn('State verified.', result['reply'])

    async def test_partial_unavailable_unknown_failed_member_never_room_success(self):
        for state in ('on', 'unavailable', 'unknown', RuntimeError('offline failure')):
            with self.subTest(state=state):
                dispatcher = self.fixture(states={'light.example_bulb_a':state})
                result = await self.action(dispatcher)
                self.assertFalse(result['verified'], result)
                # Current narration reports confirmed members and names the exception;
                # a generic legacy suffix is not required for truthful partial success.
                exception = ('light.example bulb a is still on.' if state == 'on' else
                             "light.example bulb a isn't responding." if state == 'unavailable' else
                             "Couldn't read the state of light.example bulb a.")
                self.assertEqual(result['reply'], '3 lights in light.example room group are off. '+exception)
                self.assertNotIn('State verified.', result['reply'])
                self.assertNotIn('{', result['reply'])
                self.assertIn('light.example_bulb_a', str(result['states']))
                self.assertEqual(len(self.posts), 1)

    async def test_changed_or_missing_membership_never_success(self):
        for members in ((), MEMBERS[:-1], (*MEMBERS, 'light.other')):
            dispatcher=self.fixture()
            original=dispatcher._request
            async def request(method,path,data=None):
                value=await original(method,path,data)
                if method=='GET' and path.endswith(ROOM) and self.posts: value['attributes']['entity_id']=list(members)
                return value
            dispatcher._request=request
            result = await self.action(dispatcher)
            self.assertFalse(result['verified'], result)

    async def test_group_unavailable_never_success(self):
        result = await self.action(self.fixture(states={ROOM:'unavailable'}))
        self.assertFalse(result['verified'])

    async def test_room_on_and_brightness_verified(self):
        for data in ({}, {'brightness_pct':40}):
            result = await self.action(self.fixture('turn_on'), 'turn_on', data)
            self.assertTrue(result['verified'], result)

    async def test_mixed_group_status_not_whole_room_state(self):
        dispatcher = self.fixture(states={'light.example_bulb_a':'on'})
        result = await dispatcher.dispatch('ha_get_state', {'entity_id':ROOM}, AsyncMock())
        self.assertIn('Whole-room state not verified.', result['reply'])

    async def test_group_status_reports_individual_states(self):
        dispatcher = self.fixture(states={'light.example_bulb_a':'unavailable'})
        result = await dispatcher.dispatch('ha_get_state', {'entity_id':ROOM}, AsyncMock())
        self.assertIn('light.example_bulb_a=unavailable', result['reply'])
        self.assertIn('not verified', result['reply'])

    async def test_group_brightness_checks_every_member(self):
        dispatcher = self.fixture('turn_on')
        original = dispatcher._request
        async def request(method, path, data=None):
            row = await original(method, path, data)
            if method == 'GET' and path.endswith('light.example_bulb_a'): row['attributes']['brightness'] = 255
            return row
        dispatcher._request = request
        result = await self.action(dispatcher, 'turn_on', {'brightness_pct':40})
        self.assertFalse(result['verified'], result)

    async def test_no_local_optin_or_member_fanout(self):
        dispatcher=self.fixture()
        result=await self.action(dispatcher)
        self.assertTrue(result['dispatched'])
        self.assertEqual(len(self.posts),1)
        self.assertEqual(self.posts[0][1],{'entity_id':ROOM})
        for member in MEMBERS:
            validate('ha_call_service',{'domain':'light','service':'turn_off','entity_id':member,'data':{}})

class RoomConversation(Slice):
    async def test_room_command_schema_guidance_target_readback_and_speech(self):
        self.transcript = 'turn off my living room lights'
        self.args = {'domain':'light','service':'turn_off','entity_id':ROOM,'data':{}}
        original = self.dispatcher._request
        async def request(method, path, data=None):
            if path=='/api/services': return await original(method,path,data)
            self.entity = ROOM if method == 'POST' else path.rsplit('/',1)[1]
            row = await original(method,path,data)
            if method == 'GET' and self.entity == ROOM:
                row['attributes'] |= {'entity_id':list(MEMBERS), 'is_hue_group':True, 'hue_type':'room'}
            return row
        self.dispatcher._request = request
        row = await self.submit()
        self.assertIn('State verified.', row['detail'])
        self.assertEqual(self.spoken, [row['detail']])
        self.assertEqual(self.requests, [('GET','/api/services'), *[('GET','/api/states/'+e) for e in (ROOM,*MEMBERS)], ('POST','/api/services/light/turn_off'), *[('GET','/api/states/'+e) for e in (ROOM,*MEMBERS)]])
        instructions = self.wire[0]['instructions']
        self.assertIn('room group', instructions)
        self.assertNotIn(ROOM, instructions)
        self.assertNotIn('use exactly that service and light.example_bulb_c', instructions)
        self.assertEqual(len(TOOLS),4)
        self.assertNotIn('enum',TOOLS[1]['parameters']['properties']['entity_id'])
        health = await (await self.client.get('/v1/health',headers=self.headers)).json()
        self.assertIn('Discover actual entities', health['reason'])

# Reuse fixture without duplicating inherited tests.
for name in list(dir(Slice)):
    if name.startswith('test_') and name not in RoomConversation.__dict__:
        setattr(RoomConversation, name, None)
del Slice
