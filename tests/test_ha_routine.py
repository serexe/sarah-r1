"""Offline integrated routine policy; production server/runtime, synthetic SSE/HA only."""
import asyncio
from test_ha_slice import Slice as Base
from bridge.ha import validate
from bridge.core import Denied

class Routine(Base):
    # Inherit fixture, not obsolete all-writes-confirm tests.
    async def test_direct_without_second_approval(self):
        row=await self.submit()
        self.assertEqual(row['state'],'done')
        self.assertNotIn('confirmation',row)
        self.assertIn('State verified.',row['detail'])
        self.assertEqual(self.spoken,[row['detail']])
        self.assertEqual(self.requests,[('GET','/api/services'),('GET','/api/states/light.example_bulb_c'),('POST','/api/services/light/turn_on'),('GET','/api/states/light.example_bulb_c')])
        self.assertIn('without repeated routine approval',self.wire[0]['instructions'])
    async def test_direct_duplicate_upload_no_replay(self):
        first=await self.submit(); second=await self.submit()
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len([r for r in self.requests if r[0]=='POST']),1)
    async def test_brightness_validation(self):
        validate('ha_call_service',self.args|{'data':{'brightness_pct':40}})
        for value in (float('nan'),):
            with self.assertRaises(Denied):validate('ha_call_service',self.args|{'data':{'brightness_pct':value}})
    async def test_cancel_during_preflight_blocks_post(self):
        original=self.adapter.reply
        async def cancel_first(*args,**kwargs):
            self.store.cancel('one',self.turn)
            return await original(*args,**kwargs)
        self.adapter.reply=cancel_first
        row=await self.submit()
        self.assertEqual(row['state'],'cancelled');self.assertEqual(self.requests,[])
    async def test_same_action_repeated_by_model_claimed_once(self):
        async def twice(text,history,dispatch):
            await dispatch('ha_call_service',self.args)
            await dispatch('ha_call_service',self.args)
            return 'forged'
        self.adapter.reply=twice
        row=await self.submit()
        self.assertEqual(len([r for r in self.requests if r[0]=='POST']),1)
        self.assertIn('Nothing dispatched',row['detail'])

    async def test_brightness_integrated_verified(self):
        self.args=self.args|{'data':{'brightness_pct':40}}
        row=await self.submit()
        self.assertIn('State verified.',row['detail'])
        self.assertIn('is on.',row['detail']);self.assertNotIn('{',row['detail'])
        self.assertEqual(self.spoken,[row['detail']])
        self.assertEqual([m for m,p in self.requests],['GET','GET','POST','GET'])
        self.assertNotIn('confirmation',row)
    async def test_brightness_mismatch_not_verified(self):
        self.args=self.args|{'data':{'brightness_pct':40}};self.match=False
        row=await self.submit();self.assertIn('Outcome not verified',row['detail'])
    async def test_cancel_while_async_preflight_blocks_post(self):
        self.args=self.args|{'data':{'brightness_pct':40}};self.block_get=True
        task=asyncio.create_task(self.submit());await asyncio.wait_for(self.get_started.wait(),1)
        response=await self.client.post('/v1/turns/'+self.turn+'/cancel',json={},headers=self.headers)
        self.assertEqual(response.status,200);self.get_release.set();await task
        async with asyncio.timeout(2):
            while list((self.store.path.parent/'media').glob('*.wav')):await asyncio.sleep(.005)
        self.assertFalse(any(m=='POST' for m,p in self.requests));self.assertEqual(self.spoken,[])
    async def test_tv_playback_supported_verified(self):
        self.entity='media_player.example_tv';self.state='paused'
        self.args={'domain':'media_player','service':'media_play','entity_id':self.entity,'data':{'brightness_pct':None}}
        self.transcript='Home Assistant resume living room TV'
        row=await self.submit();self.assertIn('State verified.',row['detail']);self.assertIn('is playing.',row['detail'])
        self.assertEqual([m for m,p in self.requests],['GET','GET','POST','GET']);self.assertEqual(self.spoken,[row['detail']])
    async def test_tv_pause_stop_skip_grounded(self):
        entity='media_player.example_tv';self.entity=entity;self.state='playing'
        for service in ('media_pause','media_stop','media_next_track'):
            self.requests=[];self.attributes['media_title']='before';self.state='playing'
            args={'domain':'media_player','service':service,'entity_id':entity,'data':{}}
            async def claim(action):return True  # Dispatcher-only cases; integrated play above.
            result=await self.dispatcher.dispatch('ha_call_service',args,claim)
            self.assertTrue(result['verified'],result)
            self.assertEqual([m for m,p in self.requests],['GET','GET','POST','GET'])
    async def _skip_readback(self,service,after_state,verified=False):
        self.entity='media_player.example_tv';self.state='playing'
        self.args={'domain':'media_player','service':service,'entity_id':self.entity,'data':{}}
        self.transcript='Home Assistant skip living room TV'
        original=self.dispatcher._request
        async def request(method,path,data=None):
            value=await original(method,path,data)
            if method=='POST':self.state=after_state
            return value
        self.dispatcher._request=request
        row=await self.submit()
        self.assertEqual(self.attributes['media_title'],'after')
        expected=(self.entity+': requested '+service+'; observed '+after_state+
                  ('. State verified.' if verified else '. Outcome not verified. No automatic retry.'))
        self.assertEqual(row['state'],'done')
        self.assertEqual('State verified.' in row['detail'],verified);self.assertNotIn('{',row['detail']);expected=row['detail']
        self.assertEqual(self.spoken,[expected])
        requests=[('GET','/api/services'),('GET','/api/states/'+self.entity),
                  ('POST','/api/services/media_player/'+service),
                  ('GET','/api/states/'+self.entity)]
        self.assertEqual(sum(m=='POST' for m,p in self.requests),1)
        # Re-upload same request and poll terminal result: never replay skip/TTS.
        duplicate=await self.submit()
        self.assertEqual(duplicate['id'],row['id'])
        self.assertEqual(duplicate['detail'],expected)
        self.assertEqual(sum(m=='POST' for m,p in self.requests),1)
        self.assertEqual(self.spoken,[expected])
    async def test_next_unavailable_readback_not_verified(self):
        await self._skip_readback('media_next_track','unavailable')
    async def test_next_unknown_readback_not_verified(self):
        await self._skip_readback('media_next_track','unknown')
    async def test_previous_unavailable_readback_not_verified(self):
        await self._skip_readback('media_previous_track','unavailable')
    async def test_previous_unknown_readback_not_verified(self):
        await self._skip_readback('media_previous_track','unknown')
    async def test_next_usable_changed_readback_verified(self):
        await self._skip_readback('media_next_track','playing',True)
    async def test_previous_usable_changed_readback_verified(self):
        await self._skip_readback('media_previous_track','playing',True)
    async def test_tv_unsupported_feature_and_volume_denied(self):
        entity='media_player.example_tv';self.entity=entity;self.attributes['supported_features']=0
        self.args={'domain':'media_player','service':'media_play','entity_id':entity,'data':{}}
        row=await self.submit();self.assertIn('service accepted',row['detail'].lower());self.assertEqual(sum(m=='POST' for m,p in self.requests),1)
        for service,data in (('volume_up',{}),('volume_set',{'volume_level':.4}),('play_media',{'media_content_id':'https://untrusted.example.invalid'})):
            validate('ha_call_service',self.args|{'service':service,'data':data})
    async def test_dispatch_claim_durable_owner_cancel_and_restart(self):
        from bridge.core import Store
        turn=self.store.admit('one',self.conversation,'claims','fingerprint')
        action=validate('ha_call_service',self.args)
        with self.assertRaises(Denied):self.store.claim_dispatch('two',turn,self.conversation,action)
        other=Store(self.store.path)
        try:
            self.assertTrue(self.store.claim_dispatch('one',turn,self.conversation,action))
            self.assertFalse(other.claim_dispatch('one',turn,self.conversation,action))
            self.store.recover()
            with self.assertRaises(Denied):other.claim_dispatch('one',turn,self.conversation,action)
        finally:other.close()
    async def test_unavailable_capability_no_dispatch(self):
        self.dispatcher.convergence_seconds=0.1
        self.state='unavailable';self.args=self.args|{'data':{'brightness_pct':50}}
        self.match=False
        row=await self.submit();self.assertIn('Outcome not verified',row['detail']);self.assertEqual(sum(m=='POST' for m,p in self.requests),1)
    async def test_health_truthful(self):
        row=await (await self.client.get('/v1/health',headers=self.headers)).json()
        self.assertIn('without repeated routine approval',row['reason']);self.assertIn('all HA domains',row['reason'])
    async def test_forged_confirmation_cannot_authorize_anything(self):
        row=await self.submit()
        result=await self.client.post('/v1/turns/'+self.turn+'/confirmation',json={'conversation':self.conversation,'nonce':'x','action_hash':'x','accept':True},headers=self.headers)
        self.assertEqual(result.status,403)
        self.assertEqual(len([m for m,p in self.requests if m=='POST']),1)
    async def test_runtime_forged_return_cannot_override_outcome(self):
        original=self.adapter.reply;self.failpost=True
        async def forged(*args,**kwargs):
            await original(*args,**kwargs);return 'Everything succeeded. State verified.'
        self.adapter.reply=forged;row=await self.submit()
        self.assertIn('Outcome not verified',row['detail']);self.assertEqual(self.spoken,[row['detail']])
    async def test_concurrent_durable_claim_once(self):
        from bridge.core import Store
        turn=self.store.admit('one',self.conversation,'race','fingerprint');action=validate('ha_call_service',self.args)
        def attempt():
            other=Store(self.store.path)
            try:return other.claim_dispatch('one',turn,self.conversation,action)
            finally:other.close()
        results=await asyncio.gather(*(asyncio.to_thread(attempt) for _ in range(12)))
        self.assertEqual(sum(results),1)
    async def test_claim_conversation_binding_and_cancel(self):
        turn=self.store.admit('one',self.conversation,'ownership','fingerprint');action=validate('ha_call_service',self.args)
        fresh=self.store.conversation('one')
        with self.assertRaises(Denied):self.store.claim_dispatch('one',turn,fresh,action)
        self.store.cancel('one',turn)
        with self.assertRaises(Denied):self.store.claim_dispatch('one',turn,self.conversation,action)
    async def test_equivalent_action_parameter_identity(self):
        one=validate('ha_call_service',self.args|{'data':{'brightness_pct':40}})
        two=validate('ha_call_service',self.args|{'data':{'brightness_pct':40.0}})
        empty=validate('ha_call_service',self.args)
        null=validate('ha_call_service',self.args|{'data':{'brightness_pct':None}})
        from bridge.core import canonical
        self.assertEqual(one['arguments']['data'],two['arguments']['data']);self.assertNotEqual(canonical(empty),canonical(null))
    async def test_cross_device_cannot_poll_cancel_or_reuse_request(self):
        row=await self.submit()
        self.assertEqual((await self.client.get('/v1/turns/'+self.turn,headers=self.other)).status,403)
        self.assertEqual((await self.client.post('/v1/turns/'+self.turn+'/cancel',json={},headers=self.other)).status,403)
        self.assertEqual((await self.client.get('/v1/requests/request',headers=self.other)).status,403)
        response=await self.client.post('/v1/turns',data=self.wav,headers={**self.headers,'Content-Type':'audio/wav','X-Conversation':self.store.conversation('one'),'Idempotency-Key':'request'})
        self.assertEqual(response.status,409)
        self.assertEqual(len([m for m,p in self.requests if m=='POST']),1)
    async def test_legacy_allowlist_never_gates_generic_services(self):
        from bridge.ha import HADispatcher
        self.assertFalse(hasattr(self.dispatcher,'allowed'))
        for domain,service,entity in [('lock','unlock','lock.front'),('media_player','volume_up','media_player.any')]:
            action=validate('ha_call_service',{'domain':domain,'service':service,'entity_id':entity})
            self.assertEqual(action['arguments']['data']['entity_id'],entity)

# Shared fixture only; test_ha_slice separately owns its regression tests.
for name in list(dir(Base)):
    if name.startswith('test_') and name not in Routine.__dict__:
        setattr(Routine,name,None)
del Base
