"""Recorded R1 stale group/action narration regressions; offline only."""
import asyncio
import copy
from unittest.mock import AsyncMock
from test_living_room_group import GroupReadback as GroupBase, ROOM, MEMBERS
from test_siyuan import Notes as NotesBase, DOC

class Convergence(GroupBase):
    async def test_realistic_member_then_group_delay_verifies_promptly(self):
        dispatcher=self.fixture(states={e:'on' for e in (ROOM,*MEMBERS)})
        original=dispatcher._request
        loop=asyncio.get_running_loop()
        started=loop.time()
        polls=[]
        async def request(method,path,data=None):
            nonlocal started
            row=await original(method,path,data)
            if method=='POST': started=loop.time()
            elif self.posts:
                elapsed=loop.time()-started
                if path.endswith(ROOM): polls.append(elapsed)
                if elapsed >= (1.25 if path.endswith(ROOM) else .25): row['state']='off'
            return row
        dispatcher._request=request
        result=await self.action(dispatcher)
        elapsed=loop.time()-started
        self.assertTrue(result['verified'],result)
        self.assertGreaterEqual(elapsed,1.25)
        self.assertLess(elapsed,2)
        self.assertLessEqual(len(polls),7)
        self.assertEqual(len(self.posts),1)
        self.assertEqual(len(result['states'][0]['members']),4)

    async def test_default_permanent_stale_stops_at_five_second_bound(self):
        dispatcher=self.fixture(states={e:'on' for e in (ROOM,*MEMBERS)})
        loop=asyncio.get_running_loop()
        start=loop.time()
        result=await self.action(dispatcher)
        elapsed=loop.time()-start
        self.assertFalse(result['verified'])
        self.assertGreaterEqual(elapsed,4.9)
        self.assertLess(elapsed,5.5)
        self.assertIn(' is still on.',result['reply'])
        self.assertEqual(len(self.posts),1)
        # One preflight plus at most 21 complete five-entity GET snapshots.
        self.assertLessEqual(len(self.reads),110)

    async def test_cancel_during_poll_sleep_stops_reads_and_single_post(self):
        dispatcher=self.fixture(states={e:'on' for e in (ROOM,*MEMBERS)})
        task=asyncio.create_task(self.action(dispatcher))
        while len(self.reads)<10: await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        reads=len(self.reads)
        await asyncio.sleep(.3)
        self.assertEqual(len(self.reads),reads)
        self.assertEqual(len(self.posts),1)

    async def test_outer_deadline_preempts_verification_window(self):
        dispatcher=self.fixture(states={e:'on' for e in (ROOM,*MEMBERS)})
        loop=asyncio.get_running_loop()
        start=loop.time()
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(.1): await self.action(dispatcher)
        self.assertLess(loop.time()-start,.5)
        self.assertEqual(len(self.posts),1)

    async def test_delayed_group_converges_one_post(self):
        dispatcher=self.fixture(states={e:'on' for e in (ROOM,*MEMBERS)})
        original=dispatcher._request
        rounds=0
        async def request(method,path,data=None):
            nonlocal rounds
            row=await original(method,path,data)
            if method=='GET' and self.posts:
                if path.endswith(ROOM): rounds+=1
                if rounds>=2: row['state']='off'
            return row
        dispatcher._request=request
        result=await self.action(dispatcher)
        self.assertTrue(result['verified'],result)
        self.assertEqual(len(self.posts),1)
        self.assertIn('off',result['reply'])
        self.assertNotIn('"states"',result['reply'])
        self.assertEqual(len(result['states'][0]['members']),4)

    async def test_permanent_stale_mixed_unavailable_uncertain(self):
        for bad in ('on','unavailable','unknown'):
            dispatcher=self.fixture(states={ROOM:'off',MEMBERS[0]:bad})
            dispatcher.convergence_seconds=.025
            dispatcher.convergence_interval=.005
            result=await self.action(dispatcher)
            self.assertFalse(result['verified'])
            explanation={'on':' is still on.','unavailable':" isn't responding.",'unknown':"Couldn't read the state of "}[bad]
            self.assertIn(explanation,result['reply'])
            self.assertIn('3 lights in ',result['reply'])
            self.assertNotIn('"attributes"',result['reply'])
            self.assertEqual(len(self.posts),1)

    async def test_cancel_during_readback_no_retry(self):
        dispatcher=self.fixture()
        original=dispatcher._request
        waiting=asyncio.Event()
        async def request(method,path,data=None):
            if self.posts and method=='GET':
                waiting.set()
                await asyncio.Event().wait()
            return await original(method,path,data)
        dispatcher._request=request
        task=asyncio.create_task(self.action(dispatcher))
        await waiting.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(len(self.posts),1)

    async def test_readback_timeout_bounded_and_unverified(self):
        dispatcher=self.fixture()
        dispatcher.convergence_seconds=.025
        original=dispatcher._request
        async def request(method,path,data=None):
            if self.posts and method=='GET': await asyncio.Event().wait()
            return await original(method,path,data)
        dispatcher._request=request
        async with asyncio.timeout(.2): result=await self.action(dispatcher)
        self.assertFalse(result['verified'])
        self.assertEqual(len(self.posts),1)

    async def test_missing_member_snapshot_not_vacuous_success(self):
        dispatcher=self.fixture()
        original=dispatcher.state
        async def state(entity,details=False):
            row=await original(entity,details)
            if self.posts: row['members']=[]
            return row
        dispatcher.state=state
        dispatcher.convergence_seconds=.025
        result=await self.action(dispatcher)
        self.assertFalse(result['verified'])

class Narration(NotesBase):
    async def test_mixed_note_failed_ha_drops_contradiction_and_raw_dump(self):
        self.calls=[('sy_read',{'document_id':DOC}),self.action()]
        self.failpost=True
        self.prose='Your note says Original body. The living room lights are off. {"states":[]}'
        row=await self.submit()
        self.assertNotIn('lights are off',row['detail'])
        self.assertNotIn('{',row['detail'])
        self.assertIn('Outcome not verified',row['detail'])
        self.assertEqual(self.spoken,[row['detail']])
        self.assertEqual(len(self.payloads),1)
        self.assertIn('Original body',str(self.wire[-1]['input']))

    async def test_verified_action_uses_server_summary_not_model_json(self):
        self.calls=[self.action()]
        self.prose='The lights are on. {"attributes":{"state":"on"}}'
        row=await self.submit()
        self.assertIn('Living Room is off.',row['detail'])
        self.assertNotIn('{',row['detail'])
        self.assertNotIn(self.prose,row['detail'])
        outputs=[i for i in self.wire[-1]['input'] if i.get('type')=='function_call_output']
        self.assertIn('"states"',outputs[-1]['output'])

for cls,base in ((Convergence,GroupBase),(Narration,NotesBase)):
    for name in dir(base):
        if name.startswith('test_') and name not in cls.__dict__: setattr(cls,name,None)
del GroupBase,NotesBase,cls,base
