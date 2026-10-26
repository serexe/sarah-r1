"""R1-only local Kokoro worker. Run with isolated audition venv Python -I.

No network/download/provider fallback. One owned process per reply allows the
bridge's existing deadline/cancellation path to terminate and reap synthesis.
"""
import argparse
import os
import sys
from pathlib import Path

VOICE = 'af_heart'
SPEED = 1.05
LANGUAGE = 'en-us'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    text = sys.stdin.buffer.read(48_001).decode('utf-8')
    if not text.strip() or len(text) > 12_000:
        raise ValueError('empty_or_oversize_tts_text')
    root = Path(os.getenv('R1_KOKORO_ROOT', str(Path(__file__).resolve().parents[1] / '.build/kokoro-audition')))
    # Fail closed before importing runtime; never try to fetch missing assets.
    model_path = root / 'kokoro-v1.0.onnx'
    voices_path = root / 'voices-v1.0.bin'
    if not model_path.is_file() or not voices_path.is_file():
        raise RuntimeError('local_kokoro_assets_missing')
    import numpy as np
    import onnxruntime as ort
    import soundfile as sf
    from kokoro_onnx import Kokoro
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(model_path), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    model = Kokoro.from_session(session, str(voices_path))
    audio, sample_rate = model.create(text, voice=VOICE, speed=SPEED, lang=LANGUAGE)
    if sample_rate != 24000 or not len(audio) or not np.all(np.isfinite(audio)):
        raise RuntimeError('local_kokoro_invalid_audio')
    sf.write(args.output, audio, sample_rate, subtype='PCM_16')


if __name__ == '__main__':
    main()
