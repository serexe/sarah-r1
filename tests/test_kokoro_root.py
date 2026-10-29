"""Synthetic assets/runtime only: root selection, not real synthesis proof."""
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bridge import kokoro_tts


class KokoroRoot(unittest.TestCase):
    def run_worker(self, base, override=None, missing=None):
        default = base / '.build/kokoro-audition'
        root = default if override is None else override
        # Populate default too: missing override must not silently fall back.
        for directory in {default, root}:
            directory.mkdir(parents=True, exist_ok=True)
            for name in ('kokoro-v1.0.onnx', 'voices-v1.0.bin'):
                if directory != root or name != missing:
                    (directory / name).touch()
        session = Mock(return_value=object())
        model = Mock()
        model.create.return_value = ([0.0], 24000)
        kokoro = Mock()
        kokoro.from_session.return_value = model
        write = Mock()
        modules = {
            'numpy': SimpleNamespace(all=lambda x: True, isfinite=lambda x: True),
            'onnxruntime': SimpleNamespace(SessionOptions=SimpleNamespace, InferenceSession=session),
            'soundfile': SimpleNamespace(write=write),
            'kokoro_onnx': SimpleNamespace(Kokoro=kokoro),
        }
        with patch.dict(os.environ, {}, clear=True):
            if override is not None:
                os.environ['R1_KOKORO_ROOT'] = str(override)
            with patch.object(kokoro_tts, '__file__', str(base / 'bridge/kokoro_tts.py')), \
                    patch.object(kokoro_tts.sys, 'argv', ['kokoro_tts', '--output', str(base / 'out.wav')]), \
                    patch.object(kokoro_tts.sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(b'Hello.'))), \
                    patch.dict('sys.modules', modules):
                if missing:
                    with self.assertRaisesRegex(RuntimeError, '^local_kokoro_assets_missing$'):
                        kokoro_tts.main()
                    session.assert_not_called()
                    write.assert_not_called()
                    return
                kokoro_tts.main()
        self.assertEqual(session.call_args.args, (str(root / 'kokoro-v1.0.onnx'),))
        self.assertEqual(session.call_args.kwargs['providers'], ['CPUExecutionProvider'])
        options = session.call_args.kwargs['sess_options']
        self.assertEqual((options.intra_op_num_threads, options.inter_op_num_threads), (4, 1))
        kokoro.from_session.assert_called_once_with(session.return_value, str(root / 'voices-v1.0.bin'))
        model.create.assert_called_once_with('Hello.', voice='af_heart', speed=1.05, lang='en-us')
        write.assert_called_once_with(base / 'out.wav', [0.0], 24000, subtype='PCM_16')

    def test_default_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_worker(Path(tmp))

    def test_override_selects_both_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_worker(Path(tmp), Path(tmp) / 'alternate assets')

    def test_missing_override_asset_never_uses_default(self):
        for missing in ('kokoro-v1.0.onnx', 'voices-v1.0.bin'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                self.run_worker(Path(tmp), Path(tmp) / 'alternate', missing)


class KokoroParentRoot(unittest.IsolatedAsyncioTestCase):
    async def test_parent_interpreter_uses_worker_root(self):
        from bridge import runtime
        for override in (None, 'alternate assets'):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                root = base / ('.build/kokoro-audition' if override is None else override)
                calls = []

                async def process(*args, **kwargs):
                    calls.append(args)
                    if args[0] == '/usr/bin/ffmpeg':
                        Path(args[-1]).write_bytes(b'synthetic encoded audio')

                with patch.dict(os.environ, {}, clear=True), \
                        patch.object(runtime, '__file__', str(base / 'bridge/runtime.py')), \
                        patch.object(runtime, '_tts_process', process):
                    if override is not None:
                        os.environ['R1_KOKORO_ROOT'] = str(root)
                    target = base / 'out.mp3'
                    await runtime.VoiceRuntime.__new__(runtime.VoiceRuntime).speak('Hello.', target)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0][:4], (
                    str(root / 'venv/bin/python'), '-I',
                    str(base / 'bridge/kokoro_tts.py'), '--output'))
                self.assertEqual(target.read_bytes(), b'synthetic encoded audio')
