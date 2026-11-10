"""Local STT, TTS, and speech formatting for SARAH ACP voice."""
import asyncio
import os
import re
import threading
from pathlib import Path
from .clock import spoken_clocks
from faster_whisper import WhisperModel

TTS_STAGE_SECONDS = 20
TTS_TERMINATE_GRACE = 1


async def _settle(task):
    """Finish owned cleanup even if its caller receives repeated cancellation."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


async def _reap_spawn(spawn):
    # Shielding spawn prevents losing the process handle at the fork/exec await.
    proc = await spawn
    if proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), TTS_TERMINATE_GRACE)
        except TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
    await proc.wait()  # Always reap, including successful/nonzero exits.


async def _tts_process(*args, input=None, failure, **kwargs):
    spawn = asyncio.create_task(asyncio.create_subprocess_exec(*args, **kwargs))
    try:
        async with asyncio.timeout(TTS_STAGE_SECONDS):
            proc = await asyncio.shield(spawn)
            await proc.communicate(input)
            if proc.returncode:
                raise RuntimeError(failure)
    finally:
        await _settle(asyncio.create_task(_reap_spawn(spawn)))


def _money_words(match):
    """Bounded English dollar amounts only; no general numeric/prose parser."""
    before, after, amount, fraction = match.groups()
    if before and after:
        return match.group(0)
    digits = amount.replace(',', '')
    if len(digits) > 12:
        return match.group(0)
    dollars = int(digits)
    small = ('zero one two three four five six seven eight nine ten eleven twelve '
             'thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split()
    tens = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
    def words(n):
        if n < 20:
            return small[n]
        if n < 100:
            return tens[n // 10] + (' ' + small[n % 10] if n % 10 else '')
        for scale, label in ((10**9, 'billion'), (10**6, 'million'),
                             (1000, 'thousand'), (100, 'hundred')):
            if n >= scale:
                return words(n // scale) + ' ' + label + (' ' + words(n % scale) if n % scale else '')
    cents = int(fraction or '0')
    parts = []
    if dollars or not cents:
        parts.append(words(dollars) + (' dollar' if dollars == 1 else ' dollars'))
    if cents:
        parts.append(words(cents) + (' cent' if cents == 1 else ' cents'))
    return ('minus ' if (before or after) and (dollars or cents) else '') + ' and '.join(parts)


def speech_text(text):
    """Remove presentation Markdown only at the speech boundary, not from history.

    Keep code contents/escaped symbols literal; never globally delete punctuation.
    Conservative delimiter boundaries preserve arithmetic and model identifiers.
    """
    literals = []
    def protect(value):
        literals.append(value)
        return '\x00' + str(len(literals) - 1) + '\x00'
    def literal(match):
        return protect(match.group(1))
    text = re.sub(r'(?m)^ {0,3}(`{3,}|~{3,})[^\n`~]*\n([\s\S]*?)^ {0,3}\1[ \t]*(?:\n|$)',
                  lambda m: protect(m.group(2)), text)
    text = re.sub(r'(?m)^ {0,3}(?:`{3,}|~{3,})[\w+-]*[ \t]*(?:\n|$)', '', text)
    text = re.sub(r'`+([^`\n]+)`+', literal, text)
    text = re.sub(r'\\([\\`*_{}\[\]()#+.!>~$-])', literal, text)
    text = re.sub(r'!?\[([^\]\n]+)\]\((?:[^()\n]|\([^()\n]*\))*\)', r'\1', text)
    text = re.sub(r'(?m)^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$', r'\1', text)
    text = re.sub(r'(?m)^[ \t]*(?:[-+*]|\d+[.)])[ \t]+', '', text)
    for marker in ('***', '___', '**', '__', '*', '_'):
        pattern = r'(?<!\w)' + re.escape(marker) + r'(\S(?:[^\n]*?\S)?)' + re.escape(marker) + r'(?!\w)'
        text = re.sub(pattern, r'\1', text)
    # Before literal restoration: code and escaped dollars never become money.
    text = re.sub(r'(?<![\w\\$+./-])(-)?\$(-)?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]{2}))?(?![\w$/-]|[.,]\d)',
                  _money_words, text)
    text = spoken_clocks(text)
    return re.sub(r'\x00(\d+)\x00', lambda m: literals[int(m.group(1))], text).strip()


class VoiceRuntime:
    """Shared local voice utilities. Reasoning belongs to ACPRuntime only."""
    def __init__(self):
        self.whisper = None
        self.lock = threading.Lock()

    def transcribe(self, path):
        # Local-only: missing model fails; never cloud fallback/download.
        with self.lock:
            if self.whisper is None:
                self.whisper = WhisperModel('base', device='cpu', compute_type='int8', download_root=os.getenv('R1_WHISPER_MODELS', str(Path(__file__).resolve().parents[1]/'.build/whisper-models')), local_files_only=True)
            segments, _ = self.whisper.transcribe(str(path), beam_size=3, language='en', vad_filter=True)
            text = ' '.join(s.text.strip() for s in segments).strip()
        if not text or len(text)>8000:
            raise ValueError('empty_or_oversize_transcript')
        return text

    async def speak(self, text, path):
        # Local CPU voice; no external speech fallback.
        # No eSpeak speech route, download, cloud or paid fallback.
        import tempfile
        path = Path(path)
        root = Path(os.getenv('R1_KOKORO_ROOT', str(Path(__file__).resolve().parents[1]/'.build/kokoro-audition')))
        # Same-filesystem private scratch; final media name never holds partial
        # output. No await between successful encode and atomic publication.
        with tempfile.TemporaryDirectory(prefix='.r1-tts-', dir=path.parent) as tmp:
            wav=Path(tmp)/'speech.wav'
            encoded=Path(tmp)/'speech.mp3'
            from .warm_voice import WarmVoice
            if not hasattr(self, '_warm_voice'):
                self._warm_voice = WarmVoice(root/'venv/bin/python', Path(__file__).with_name('kokoro_tts.py'))
            await self._warm_voice.synthesize(speech_text(text), wav)
            await _tts_process('/usr/bin/ffmpeg','-nostdin','-loglevel','error','-y','-i',str(wav),'-codec:a','libmp3lame',str(encoded),
                failure='tts_encoding_failed',stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
            if not encoded.is_file() or encoded.stat().st_size == 0:
                raise RuntimeError('tts_encoding_failed')
            encoded.chmod(0o600)
            encoded.replace(path)
