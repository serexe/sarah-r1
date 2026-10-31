import asyncio
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest

from bridge.warm_voice import WarmVoice, sentence_chunks


class SentenceTests(unittest.TestCase):
    def test_boundaries(self):
        text = 'Dr. Jones paid 3.50 at 10:30 a.m. today. Ready? Final fragment'
        self.assertEqual(sentence_chunks(text), [
            'Dr. Jones paid 3.50 at 10:30 a.m. today.', 'Ready?', 'Final fragment'])
        self.assertEqual(sentence_chunks('One. Two.'), ['One.', 'Two.'])
        self.assertEqual(len(sentence_chunks('Yes. ' * 60)), 32)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_cancel_double_stop_and_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp)/'worker.py'
            script.write_text('''import sys,json,time,signal
signal.signal(signal.SIGTERM, signal.SIG_IGN)
for line in sys.stdin:
 r=json.loads(line)
 if r['text']=='block': time.sleep(60)
 print('{"ok":true}',flush=True)
''')
            worker = WarmVoice(sys.executable, script)
            job = asyncio.create_task(worker.synthesize('block', Path(tmp)/'out'))
            while worker.proc is None:
                await asyncio.sleep(.005)
            pid = worker.proc.pid
            await asyncio.sleep(.05)
            job.cancel()
            await asyncio.sleep(.02)
            self.assertTrue(worker.lock.locked())
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)
            self.assertIsNone(worker.proc)
            await worker.synthesize('ok', Path(tmp)/'next')
            next_pid = worker.proc.pid
            await worker.synthesize('ok', Path(tmp)/'next')
            self.assertEqual(next_pid, worker.proc.pid)
            await worker.close()

    async def test_failure_not_replayed(self):
        worker = WarmVoice(sys.executable, '/nonexistent/worker.py')
        with self.assertRaises(RuntimeError):
            await worker.synthesize('hello', '/unused')
        self.assertIsNone(worker.proc)
