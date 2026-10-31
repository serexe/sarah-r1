"""Serialized owned local voice process; cancellation kills native ORT and reaps.

No eager startup: loads existing assets on first request; stays warm after success.
No retries after worker failure. One in-flight request, no internal request queue.
"""
import asyncio
import json
from pathlib import Path


class WarmVoice:
    def __init__(self, python, script):
        self.python, self.script = str(python), str(script)
        self.proc = None
        self.spawn = None
        self.lock = asyncio.Lock()

    async def _close(self):
        if self.spawn is not None:
            self.proc = await self.spawn
            self.spawn = None
        proc = self.proc
        if proc is None:
            return
        if proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), 1)
            except TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        await proc.wait()
        self.proc = None

    async def close(self):
        # A cancelled owner cannot release admission before actual native death.
        cleanup = asyncio.create_task(self._close())
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def synthesize(self, text, output):
        if self.lock.locked():
            raise RuntimeError('voice_worker_busy')
        async with self.lock:
            try:
                async with asyncio.timeout(20):
                    if self.proc is None:
                        self.spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                            self.python, '-I', self.script, '--serve',
                            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL, limit=1024))
                        self.proc = await asyncio.shield(self.spawn)
                        self.spawn = None
                    self.proc.stdin.write((json.dumps({'text': text, 'output': str(Path(output))})+'\n').encode())
                    await self.proc.stdin.drain()
                    if await self.proc.stdout.readline() != b'{"ok":true}\n':
                        raise RuntimeError('local_tts_worker_failed')
            except BaseException:
                await self.close()
                raise


def sentence_chunks(text):
    """Conservative sentence ends; ambiguous abbreviations remain together.

    Text bounded to existing 12k limit; at most 32 chunks. No shortening.
    Long fragments remain intact instead of introducing mid-word boundaries.
    """
    import re
    if not text.strip() or len(text) > 12000:
        raise ValueError('empty_or_oversize_tts_text')
    chunks = []
    start = 0
    for m in re.finditer(r'[.!?]+[\"\u201d\u2019\')\]]*(?=\s+|$)', text):
        end = m.end()
        prefix = text[start:end]
        token = prefix.split()[-1].strip('\"\u201d\u2019\')\]').lower()
        if token.endswith('.') and (re.search(r'(?:\b[a-z]\.)+$', token) or token in {
                'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.', 'st.',
                'vs.', 'etc.', 'e.g.', 'i.e.', 'a.m.', 'p.m.', 'no.', 'fig.'}):
            continue
        if len(chunks) == 31:
            break
        chunks.append(text[start:end].strip())
        start = end
    if text[start:].strip():
        chunks.append(text[start:].strip())
    return chunks
