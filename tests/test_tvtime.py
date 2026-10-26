"""Offline only: synthetic SSE decisions, mocked canonical subprocess. Never power TV."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
from test_full_ha import FullHA as Base
from bridge.server import make_app
from bridge.tvtime import TVTimeDispatcher, COMMAND, TIMEOUT_SECONDS


class TVTimeConversation(Base):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.proc = type('Process', (), {})()
        self.proc.returncode = 0
        self.proc.wait = AsyncMock(return_value=0)
        self.spawn = patch('bridge.tvtime.asyncio.create_subprocess_exec', AsyncMock(return_value=self.proc))
        self.mock_spawn = self.spawn.start()
        self.tv = TVTimeDispatcher()
        await self.client.close()
        self.client = TestClient(TestServer(make_app(self.store, self.adapter, self.dispatcher, tvtime=self.tv)))
        await self.client.start_server()
        self.calls = [('tvtime_on', {})]
        self.prose = 'Everything is ready and verified!'

    async def asyncTearDown(self):
        await super().asyncTearDown()
        self.spawn.stop()

    async def test_phrase_wire_and_canonical_target_truth(self):
        for i, phrase in enumerate(('TV time', "Sarah, let's watch TV", 'Start TV time please')):
            self.transcript = phrase
            row = await self.submit('phrase-'+str(i))
            self.assertEqual(row['state'], 'done')
            self.assertEqual(row['detail'], 'TV time started. Device readiness not verified.')
            self.assertNotIn('confirmation', row)
            self.assertEqual(self.spoken[-1], row['detail'])
            wire = self.wire[-2]
            self.assertEqual(wire['input'][-1]['content'], phrase)
            self.assertIn('tvtime_on', {t['name'] for t in wire['tools']})
            self.assertIn('TV time', wire['instructions'])
            self.assertIn('natural variants', wire['instructions'])
            self.assertFalse(wire['parallel_tool_calls'])
        self.assertEqual(COMMAND, ('/usr/bin/python3', '/opt/sarah/bin/tvtime'))
        for call in self.mock_spawn.call_args_list:
            self.assertEqual(call.args, COMMAND)
            self.assertEqual(call.kwargs['stdout'], asyncio.subprocess.DEVNULL)
            self.assertEqual(call.kwargs['stderr'], asyncio.subprocess.DEVNULL)
        self.assertLessEqual(TIMEOUT_SECONDS, 70)
        self.assertEqual(self.requests, [])

    async def test_duplicate_model_upload_and_cross_tool_one_claim(self):
        self.calls += [('tvtime_on', {}), self.action()]
        first = await self.submit()
        second = await self.submit()
        self.assertEqual(first['id'], second['id'])
        self.mock_spawn.assert_awaited_once()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM dispatches').fetchone()[0], 1)
        self.assertIn('already claimed', first['detail'])
        self.assertEqual(self.payloads, [])

    async def test_failure_no_retry_no_fake_success(self):
        self.proc.returncode = 1
        self.calls += [('tvtime_on', {})]
        row = await self.submit()
        self.assertIn('Outcome unknown', row['detail'])
        self.assertIn('No automatic retry', row['detail'])
        self.assertNotIn(self.prose, row['detail'])
        self.mock_spawn.assert_awaited_once()

    async def test_unavailable_spawn_redacted(self):
        self.mock_spawn.side_effect = OSError('secret raw receipt')
        row = await self.submit()
        self.assertNotIn('secret', row['detail'])
        self.assertIn('Outcome unknown', row['detail'])
        self.mock_spawn.assert_awaited_once()

    async def test_cancel_before_claim(self):
        async def claim(action): return False
        result = await self.tv.dispatch('tvtime_on', {}, claim)
        self.assertFalse(result['dispatched'])
        self.mock_spawn.assert_not_awaited()

    async def test_cancel_after_dispatch_does_not_undo_or_speak(self):
        started = asyncio.Event(); release = asyncio.Event()
        async def wait():
            started.set(); await release.wait(); return 0
        self.proc.wait = wait
        task = asyncio.create_task(self.submit())
        await asyncio.wait_for(started.wait(), 2)
        turn = self.store.db.execute('SELECT id FROM turns').fetchone()[0]
        await self.client.post('/v1/turns/'+turn+'/cancel', json={}, headers=self.headers)
        release.set(); row = await task
        await asyncio.sleep(.05)
        self.assertEqual(row['state'], 'cancelled')
        self.assertEqual(self.spoken, [])
        self.mock_spawn.assert_awaited_once()

    async def test_timeout_reaps_process_no_retry(self):
        started = asyncio.Event(); stopped = asyncio.Event()
        self.proc.returncode = None
        async def wait():
            started.set(); await stopped.wait(); return -15
        def terminate():
            self.proc.returncode = -15; stopped.set()
        self.proc.wait = wait
        self.proc.terminate = terminate
        async def claim(action): return True
        with patch('bridge.tvtime.TIMEOUT_SECONDS', .01):
            result = await self.tv.dispatch('tvtime_on', {}, claim)
        self.assertTrue(stopped.is_set())
        self.assertIn('Outcome unknown', result['reply'])
        self.assertFalse(result['verified'])
        self.mock_spawn.assert_awaited_once()

    async def test_task_cancellation_reaps_and_propagates(self):
        started = asyncio.Event(); stopped = asyncio.Event()
        self.proc.returncode = None
        async def wait():
            started.set(); await stopped.wait(); return -15
        def terminate():
            self.proc.returncode = -15; stopped.set()
        self.proc.wait = wait; self.proc.terminate = terminate
        async def claim(action): return True
        task = asyncio.create_task(self.tv.dispatch('tvtime_on', {}, claim))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(stopped.is_set())
        self.mock_spawn.assert_awaited_once()

    async def test_reject_model_supplied_target(self):
        self.calls = [('tvtime_on', {'url':'https://untrusted.example.invalid', 'command':'anything'})]
        row = await self.submit()
        self.assertIn('denied', row['detail'])
        self.mock_spawn.assert_not_awaited()

    async def test_quoted_negated_discussion_preserved(self):
        self.calls = []; self.prose = 'No action requested.'
        self.transcript = 'Do not start TV time; explain what TV time means.'
        row = await self.submit()
        self.assertEqual(row['detail'], self.prose)
        self.assertIn(self.transcript, self.wire[0]['input'][-1]['content'])
        self.mock_spawn.assert_not_awaited()


for name in list(dir(Base)):
    if name.startswith('test_') and name not in TVTimeConversation.__dict__:
        setattr(TVTimeConversation, name, None)
del Base
