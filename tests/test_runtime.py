"""Offline production-runtime regressions. Synthetic pool, transport, and children only."""
import asyncio
import inspect
import io
import json
import signal
import sys
import tempfile
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

    async def test_cancelled_http_stream_expires_before_worker_reuse(self):
        await self.http_expiry(cancelled=True)

    async def http_expiry(self, cancelled=False):
        adapter, _ = runtime()
        adapter.transcribe = lambda path: 'synthetic transcript'

        async def speak(text, path):
            pass
        adapter.speak = speak
        streams = [Stream([b': heartbeat\n\n'] * 30 + [DONE], delay=0.01), Stream()]
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
                with patch.object(module, 'CODEX_TOTAL_SECONDS', 0.05, create=True), Transport([(200, s) for s in streams]):
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
                            busy = await client.post('/v1/turns', data=buf.getvalue(),
                                                     headers={**headers, 'Idempotency-Key': 'busy'})
                            self.assertEqual(busy.status, 409)
                            self.assertEqual((await busy.json())['error'], 'voice_worker_busy')
                            async with asyncio.timeout(1):
                                while not streams[0].closed:
                                    await asyncio.sleep(0.005)
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
