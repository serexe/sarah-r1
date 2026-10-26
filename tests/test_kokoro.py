"""Offline production TTS command contract; no synthesis/network required."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import runtime


class KokoroContract(unittest.IsolatedAsyncioTestCase):
    def test_example_selected_voice_parameters_are_fixed(self):
        from bridge.kokoro_tts import VOICE, SPEED, LANGUAGE
        self.assertEqual((VOICE, SPEED, LANGUAGE), ('af_heart', 1.05, 'en-us'))

    async def test_selected_local_helper_is_only_synthesis_route(self):
        calls = []
        async def process(*args, input=None, failure, **kwargs):
            calls.append((args, input, failure, kwargs))
            if args[0] == '/usr/bin/ffmpeg':
                Path(args[-1]).write_bytes(b'synthetic encoded audio')
            else:
                self.assertEqual(args[1], '-I')
                self.assertEqual(Path(args[0]), Path(runtime.__file__).resolve().parents[1] / '.build/kokoro-audition/venv/bin/python')
                self.assertEqual(Path(args[2]), Path(runtime.__file__).with_name('kokoro_tts.py'))
                self.assertEqual(args[3], '--output')
                self.assertEqual(input, 'Hello example. State verified.'.encode())
                self.assertEqual(kwargs['stdin'], asyncio.subprocess.PIPE)
                Path(args[4]).write_bytes(b'synthetic wav')
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, '_tts_process', process):
            target = Path(tmp) / 'out.mp3'
            await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak('Hello example. State verified.', target)
            self.assertEqual(target.read_bytes(), b'synthetic encoded audio')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(tmp).iterdir()), [target])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][2], 'local_tts_failed')
        self.assertEqual(calls[1][2], 'tts_encoding_failed')

    async def test_synthesis_failure_has_no_fallback_or_publication(self):
        calls = []
        async def fail(*args, **kwargs):
            calls.append(args)
            raise RuntimeError('local_tts_failed')
        with tempfile.TemporaryDirectory() as tmp, patch.object(runtime, '_tts_process', fail):
            target = Path(tmp) / 'out.mp3'
            with self.assertRaisesRegex(RuntimeError, '^local_tts_failed$'):
                await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak('Hello.', target)
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertEqual(len(calls), 1)
