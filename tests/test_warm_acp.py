"""Bounded warm ACP lifecycle; synthetic stdio fixture, no model/home calls."""
import asyncio
from unittest.mock import patch
from test_runtime import ACPTests as Base
from bridge.acp_client import ACPClient, ACPError

class WarmACPTests(Base):
    async def asyncSetUp(self):
        self.adapters=[]
    async def asyncTearDown(self):
        for a in self.adapters:
            await a.close()
    def adapter(self):
        a=super().adapter();self.adapters.append(a);return a
    def methods(self,name):
        return [c for c in self.calls if c.get('method')==name]
    async def test_two_prompts_one_exact_load_and_init(self):
        a=self.adapter()
        self.store.db.execute('INSERT INTO acp_sessions VALUES(?,?,?,?,?)',('a',self.conversation,self.config.identity,'known','ready'))
        with patch.object(ACPClient,'connect',self.connect):
            await self.bound(a);await self.bound(a)
        self.assertEqual(len(self.clients),1)
        self.assertEqual(len(self.methods('initialize')),1)
        self.assertEqual(len(self.methods('session/load')),1)
        self.assertEqual(self.methods('session/load')[0]['params']['sessionId'],'known')
        self.assertEqual(len(self.methods('session/new')),0)
        self.assertEqual(len(self.methods('session/prompt')),2)
        self.assertIsNone(self.clients[0].dispatch)
        self.assertIsNone(self.clients[0].turn_nonce)
        self.assertNotEqual(*[c['params']['nonce'] for c in self.methods('_sarah/turn')])
    async def test_isolation_eviction_ttl_shutdown(self):
        a=self.adapter();a.IDLE_SECONDS=.01
        with patch.object(ACPClient,'connect',self.connect):
            await self.bound(a)
            other=self.store.conversation('b')
            await self.bound(a,device='b',conversation=other)
            self.assertTrue(self.clients[0].writer.closed)
            self.assertEqual(len(self.clients),2)
            await asyncio.sleep(.04)
            self.assertTrue(self.clients[1].writer.closed)
            await self.bound(a,device='b',conversation=other)
            self.assertEqual(len(self.methods('session/load')),1)
            await a.close()
            self.assertTrue(self.clients[-1].writer.closed)
            with self.assertRaisesRegex(ACPError,'acp_worker_unavailable'):await self.bound(a,device='b',conversation=other)
    async def test_stop_double_stop_no_replay(self):
        a=self.adapter();self.stall=True
        with patch.object(ACPClient,'connect',self.connect):
            t=asyncio.create_task(self.bound(a));await self.entered.wait();t.cancel();t.cancel()
            with self.assertRaises(asyncio.CancelledError):await t
            self.assertTrue(self.clients[0].writer.closed)
            self.assertEqual(self.store.db.execute('SELECT state FROM acp_sessions').fetchone()[0],'uncertain')
            with self.assertRaisesRegex(ACPError,'acp_session_uncertain_or_changed'):await self.bound(a)
            self.stall=False
            await self.bound(a,conversation=self.store.conversation('a'))
        self.assertEqual(len(self.methods('session/prompt')),2)
    async def test_crash_and_policy_drift_no_replay(self):
        a=self.adapter()
        with patch.object(ACPClient,'connect',self.connect):
            await self.bound(a);self.disconnect_prompt=True
            with self.assertRaisesRegex(ACPError,'acp_disconnected'):await self.bound(a)
            with self.assertRaisesRegex(ACPError,'acp_session_uncertain_or_changed'):await self.bound(a)
        self.assertEqual(len(self.methods('session/prompt')),2)
        self.assertEqual(len(self.clients),1)
    async def test_policy_drift_evicts_before_connect(self):
        a=self.adapter()
        with patch.object(ACPClient,'connect',self.connect):await self.bound(a)
        with patch('bridge.acp_policy.identity',return_value='changed'):
            with patch.object(ACPClient,'connect',side_effect=AssertionError('no reconnect')):
                with self.assertRaisesRegex(ACPError,'acp_session_uncertain_or_changed'):await self.bound(a)
        self.assertTrue(self.clients[0].writer.closed)
    async def test_stale_nonce_denied_current_owner_used(self):
        from bridge.acp_policy import identity
        c=await self.connect(self.config);c.session_id='known';c.collecting=True;c.turn_nonce='new'
        seen=[]
        async def dispatch(name,args):seen.append('new owner');return {'reply':'receipt'}
        c.dispatch=dispatch
        p={'sessionId':'known','policy':identity(),'name':'ha_get_state','arguments':{'entity_id':'light.test'},'nonce':'old'}
        with self.assertRaisesRegex(ACPError,'acp_dispatch_binding_denied'):await c.handle_agent({'method':'_sarah/dispatch','id':'x','params':p})
        p['nonce']='new';await c.handle_agent({'method':'_sarah/dispatch','id':'x','params':p})
        self.assertEqual(seen,['new owner']);c.dispatch=None
        with self.assertRaisesRegex(ACPError,'acp_dispatch_binding_denied'):await c.handle_agent({'method':'_sarah/dispatch','id':'x','params':p})
        await c.close()
    async def test_native_child_reaped_before_cancel_returns(self):
        import sys
        a=self.adapter();self.stall=True
        process=await asyncio.create_subprocess_exec(sys.executable,'-c',
            'import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(60)',
            stdout=asyncio.subprocess.PIPE,start_new_session=True)
        await process.stdout.readline()
        async def connect(config):
            c=await self.connect(config);c.process=process;return c
        with patch.object(ACPClient,'connect',connect):
            t=asyncio.create_task(self.bound(a));await self.entered.wait();t.cancel()
            with self.assertRaises(asyncio.CancelledError):await t
        self.assertIsNotNone(process.returncode)
        self.assertEqual(self.store.db.execute('SELECT state FROM acp_sessions').fetchone()[0],'uncertain')

    async def test_clock_literal_synced_once_between_warm_prompts(self):
        from bridge.server import make_app
        from types import SimpleNamespace
        make_app(self.store,SimpleNamespace(ready=True))
        a=self.adapter()
        with patch.object(ACPClient,'connect',self.connect):
            await self.bound(a)
            t=self.store.admit('a',self.conversation,'clock','fixture')
            self.store.finish('a',t,'done',"It's 1:00 PM CDT.",'What time is it?')
            self.store.db.execute('INSERT INTO response_metrics VALUES(?,?,?)',(t,'direct_clock','{}'))
            await self.bound(a);await self.bound(a)
        contexts=[c['params']['dialogue'] for c in self.methods('_sarah/turn')]
        self.assertEqual(contexts,[[],[{'role':'user','content':'What time is it?'},{'role':'assistant','content':"It's 1:00 PM CDT."}],[]])
        self.assertTrue(all(c['params']['prompt'][0]['text']=='hello' for c in self.methods('session/prompt')))

for name in dir(Base):
    if name.startswith('test_') and name not in WarmACPTests.__dict__:setattr(WarmACPTests,name,None)
del Base
