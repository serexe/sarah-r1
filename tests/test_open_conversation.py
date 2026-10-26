"""Production HTTP -> VoiceRuntime -> synthetic Codex SSE -> loopback HA -> TTS.

Synthetic model decisions prove routing/transport contracts, NOT live model intent
accuracy. No provider, live HA, microphone, playback or credential loading.
"""
from test_ha_slice import Slice as Base


class OpenConversation(Base):
    async def assert_done(self, expected=None):
        row = await self.submit()
        self.assertEqual(row['state'], 'done')
        if expected is not None:
            self.assertIn('State verified.' if 'State verified.' in expected else expected, row['detail'])
        self.assertEqual(self.spoken[-1], row['detail'])
        self.assertEqual({t['name'] for t in self.wire[0]['tools']},
                         {t['name'] for t in __import__('bridge.ha',fromlist=['TOOLS']).TOOLS+__import__('bridge.siyuan',fromlist=['TOOLS']).TOOLS+__import__('bridge.calendar',fromlist=['TOOLS']).TOOLS+__import__('bridge.tvtime',fromlist=['TOOLS']).TOOLS})
        self.assertEqual(self.wire[0]['tool_choice'], 'auto')
        self.assertNotIn('confirmation', row)
        return row

    async def next_turn(self, key):
        response = await self.client.post('/v1/turns', data=self.wav, headers={
            **self.headers, 'Content-Type':'audio/wav',
            'X-Conversation':self.conversation, 'Idempotency-Key':key})
        self.assertEqual(response.status, 202)
        self.turn = (await response.json())['turn']
        return await self.wait('done', 'error')

    async def test_novel_light_paraphrase_tools_and_readback(self):
        self.transcript = 'It is gloomy in here; brighten things up for me.'
        await self.assert_done('light.example_bulb_c: requested on; observed on. State verified.')
        self.assertEqual(self.requests, [('GET','/api/services'), ('GET','/api/states/light.example_bulb_c'), ('POST','/api/services/light/turn_on'),
                                         ('GET','/api/states/light.example_bulb_c')])

    async def test_novel_tv_paraphrase_direct(self):
        self.transcript = 'Hold that thought on the big screen while I get a drink.'
        self.entity = 'media_player.example_tv'; self.state = 'playing'
        self.args = {'domain':'media_player','service':'media_pause',
                     'entity_id':self.entity,'data':{'brightness_pct':None}}
        await self.assert_done(self.entity+': requested paused; observed paused. State verified.')
        self.assertEqual([method for method, _ in self.requests], ['GET','GET','POST','GET'])

    async def test_contextual_followup_has_history_and_tools(self):
        self.transcript = 'It is gloomy in here; brighten things up for me.'
        first = await self.assert_done()
        self.transcript = 'Actually, undo that.'
        self.args = self.args | {'service':'turn_off'}
        row = await self.next_turn('followup')
        self.assertIn('State verified.', row['detail']); self.assertIn('is off.', row['detail'])
        followup = self.wire[2]
        self.assertEqual(followup['input'][:2], [
            {'role':'user','content':'It is gloomy in here; brighten things up for me.'},
            {'role':'assistant','content':first['detail']}])
        self.assertEqual(followup['input'][-1], {'role':'user','content':'Actually, undo that.'})
        self.assertEqual(len(followup['tools']), 18)
        self.assertEqual(len([m for m,p in self.requests if m=='POST']), 2)
        self.assertEqual(self.spoken[-1], row['detail'])

    async def test_ordinary_conversation_preserved_with_tools_available(self):
        self.transcript = 'What makes a good friendship?'
        self.model_prose = 'Trust, kindness, and showing up for each other.'
        await self.assert_done(self.model_prose)
        self.assertEqual(self.requests, [])

    async def test_no_tool_clarification_not_replaced_by_canned_outcome(self):
        self.transcript = 'Can you dim things a little?'
        self.model_prose = 'How dim would you like the living room light?'
        await self.assert_done(self.model_prose)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM dispatches').fetchone()[0], 0)

    async def test_quoted_negated_and_unknown_target_prose_reaches_model(self):
        self.model_prose = 'Just discussing it; I have not changed anything.'
        for index, text in enumerate(('Say “turn off the lights”.',
                'Home Assistant, ‘Turn off the lights.’',
                'Do not turn off the lights.', 'Turn off the bedroom lights.')):
            self.transcript = text
            row = await self.next_turn('discussion-'+str(index))
            self.assertEqual(row['state'], 'done')
            self.assertEqual(row['detail'], self.model_prose)
            self.assertEqual(len(self.wire[-1]['tools']), 18)
            self.assertEqual(self.wire[-1]['input'][-1]['content'], text)
        self.assertEqual(self.requests, [])

    async def test_failed_action_cannot_be_overridden_by_model(self):
        self.transcript = 'Bring some light into my evening.'; self.failpost = True
        row = await self.assert_done()
        self.assertIn('Outcome not verified. No automatic retry.', row['detail'])
        self.assertNotIn('Untrusted model', row['detail'])
        self.assertEqual(sum(m=='POST' for m,p in self.requests), 1)

    async def test_duplicate_upload_does_not_redispatch(self):
        self.transcript = 'Bring some light into my evening.'
        first = await self.assert_done(); second = await self.submit()
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.requests, [('GET','/api/services'), ('GET','/api/states/light.example_bulb_c'), ('POST','/api/services/light/turn_on'),
                                         ('GET','/api/states/light.example_bulb_c')])
        self.assertEqual(self.spoken, [first['detail']])

    async def test_repeated_model_call_does_not_redispatch(self):
        self.transcript = 'Bring some light into my evening.'
        self.repeat_calls = True
        row = await self.assert_done()
        self.assertEqual(len([m for m,p in self.requests if m=='POST']), 1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM dispatches').fetchone()[0], 1)
        self.assertIn('State verified.', row['detail'])
        self.assertIn('already claimed', row['detail'])

    async def test_unsupported_model_target_still_denied(self):
        self.transcript = 'Open up for our visitor.'
        self.args = {'domain':'lock','service':'unlock','entity_id':'lock.front','data':{}}
        row = await self.assert_done()
        self.assertIn('ha_service_unavailable', row['detail'])
        self.assertEqual(self.requests, [('GET','/api/services')])


# Share fixture only; original regressions run in owning module.
for name in list(dir(Base)):
    if name.startswith('test_') and name not in OpenConversation.__dict__:
        setattr(OpenConversation, name, None)
del Base
