"""Natural light production regressions; grammar eligibility intentionally removed.

Open-conversation tests own paraphrase/context/quoted-discussion coverage. This
module keeps original reported status/off, cancellation and uncertain POST proof.
"""
from test_ha_slice import Slice as Base


class NaturalLight(Base):
    async def test_reported_status_query(self):
        self.transcript = 'Can you tell me what lights are on?'
        self.callname = 'ha_get_state'; self.args = {'entity_id':'light.example_bulb_c'}
        self.state = 'on'
        row = await self.submit()
        self.assertIn('light.example_bulb_c is on.', row['detail'])
        self.assertEqual(self.requests, [('GET','/api/states/light.example_bulb_c')])
        self.assertEqual(len(self.wire[0]['tools']), 18)
        self.assertEqual(self.spoken, [row['detail']])

    async def test_requested_turnoff_once(self):
        self.transcript = 'Turn off the lights.'; self.state = 'on'
        self.args = self.args | {'service':'turn_off'}
        first = await self.submit(); second = await self.submit()
        self.assertIn('State verified.', first['detail']); self.assertIn('is off.', first['detail'])
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.requests, [('GET','/api/services'), ('GET','/api/states/light.example_bulb_c'), ('POST','/api/services/light/turn_off'),
                                         ('GET','/api/states/light.example_bulb_c')])
        self.assertEqual(self.spoken, [first['detail']])

    async def test_natural_cancel_before_dispatch(self):
        self.transcript = 'Turn off the lights.'
        original = self.adapter.reply
        async def cancelled(*args, **kwargs):
            self.store.cancel('one', self.turn)
            return await original(*args, **kwargs)
        self.adapter.reply = cancelled
        row = await self.submit()
        self.assertEqual(row['state'], 'cancelled')
        self.assertEqual(self.requests, []); self.assertEqual(self.spoken, [])

    async def test_natural_lost_post_no_replay_or_forged_success(self):
        self.transcript = 'Turn off the lights.'; self.state = 'on'
        self.args = self.args | {'service':'turn_off'}
        self.drop_response = True
        first = await self.submit(); second = await self.submit()
        expected = 'Home Assistant dispatch attempted. Outcome not verified. No automatic retry.'
        self.assertEqual(first['detail'], expected)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(self.requests, [('GET','/api/services'),('GET','/api/states/light.example_bulb_c'),('POST','/api/services/light/turn_off')])
        self.assertEqual(self.spoken, [expected])


for name in list(dir(Base)):
    if name.startswith('test_') and name not in NaturalLight.__dict__:
        setattr(NaturalLight, name, None)
del Base
