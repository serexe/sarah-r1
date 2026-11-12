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


def _pronunciation_cleanup(text):
    """Bounded spoken dates, names and units; never alter displayed answers."""
    from datetime import date
    months = ('January February March April May June July August September October November December').split()
    ordinals = ('first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth twenty-first twenty-second twenty-third twenty-fourth twenty-fifth twenty-sixth twenty-seventh twenty-eighth twenty-ninth thirtieth thirty-first').split()
    month_map = {name[:3]: i + 1 for i, name in enumerate(months)}
    small = ('zero one two three four five six seven eight nine ten eleven twelve '
             'thirteen fourteen fifteen sixteen seventeen eighteen nineteen').split()
    tens = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
    def number(n):
        if n < 20: return small[n]
        if n < 100: return tens[n // 10] + (' ' + small[n % 10] if n % 10 else '')
        if n < 1000: return number(n // 100) + ' hundred' + (' ' + number(n % 100) if n % 100 else '')
        return number(n // 1000) + ' thousand' + (' ' + number(n % 1000) if n % 1000 else '')
    def month_day(m):
        month, day = month_map[m[1][:3]], int(m[2])
        year = int(m[4]) if m[4] else None
        try: date(year if year is not None else 2000, month, day)
        except ValueError: return m[0]
        suffix = 'th' if 10 <= day % 100 <= 20 else {1:'st', 2:'nd', 3:'rd'}.get(day % 10, 'th')
        if m[3] and m[3].lower() != suffix: return m[0]
        spoken = months[month - 1] + ' ' + ordinals[day - 1]
        if year:
            spoken += ', ' + (number(year // 100) + ' ' + number(year % 100) if 2010 <= year <= 2099 else number(year))
        return spoken
    names = '|'.join(sorted(months + list(month_map), key=len, reverse=True))
    text = re.sub(r'(?<![\w./#-])(' + names + r')\.?\s*([0-9]{1,2})(st|nd|rd|th)?'
                  r'(?:,\s*(\d{4}))?(?![\w/-]|[.,]\d|,\s*\d{4}[-/])', month_day, text)
    text = re.sub(r'(?<![\w./-])(\d{1,9}(?:\.\d{1,4})?)\s*km/h(?![\w/-])',
                  lambda m: (number(int(m[1].split('.')[0])) +
                             (' point ' + ' '.join(small[int(c)] for c in m[1].split('.')[1]) if '.' in m[1] else '') +
                             (' kilometer per hour' if m[1] in ('1', '1.0', '1.00', '1.000', '1.0000') else ' kilometers per hour')), text)
    text = re.sub(r'(?<![\w./#-])(49ers|76ers)\b(?![-/])',
                  lambda m: {'49ers':'forty niners', '76ers':'seventy sixers'}[m[1]], text)
    titles = {'Dr.':'Doctor', 'Mr.':'Mister', 'Mrs.':'Misses', 'Ms.':'Miz'}
    text = re.sub(r'(?<![\w./#-])(Dr\.|Mr\.|Mrs\.|Ms\.)(?=\s+[A-Z][a-z]+\b)',
                  lambda m: titles[m[1]], text)
    return re.sub(r'(?<=\w)\s+vs\.(?=\s+\w)', ' versus', text)


def plain_answer(text, *, protect=None):
    """Remove common presentation markup; retain literal content and link targets."""
    literals = []
    def local_protect(value):
        literals.append(value)
        return '\x00' + str(len(literals) - 1) + '\x00'
    protect_span = protect if protect is not None else local_protect
    text = re.sub(r'(?m)^ {0,3}(`{3,}|~{3,})[^\n`~]*\n([\s\S]*?)^ {0,3}\1[ \t]*(?:\n|$)',
                  lambda m: protect_span(m.group(2)), text)
    text = re.sub(r'`+([^`\n]+)`+', lambda m: protect_span(m.group(1)), text)
    text = re.sub(r'\\([\\`*_{}\[\]()#+.!>~$-])', lambda m: protect_span(m.group(1)), text)
    def link(m):
        label, target = m.group(1), m.group(2)
        return label if label == target else label + ' (' + target + ')'
    text = re.sub(r'!?\[([^\]\n]+)\]\(((?:[^()\n]|\([^()\n]*\))*)\)', link, text)
    text = re.sub(r'(?:https?://|www\.)[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',
                  lambda m: protect_span(m[0]), text)
    text = re.sub(r'(?m)^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$', r'\1', text)
    text = re.sub(r'(?m)^[ \t]*(?:[-+*]|\d+[.)])[ \t]+', '', text)
    for marker in ('***', '___', '**', '__', '~~', '*', '_'):
        pattern = r'(?<!\w)' + re.escape(marker) + r'(\S(?:[^\n]*?\S)?)' + re.escape(marker) + r'(?!\w)'
        text = re.sub(pattern, r'\1', text)
    if literals:
        text = re.sub(r'\x00(\d+)\x00', lambda m: literals[int(m.group(1))], text)
    return text.strip()


def speech_text(text):
    """Normalize speech at output boundary, keeping stored dialogue untouched."""
    original = text
    literals = []
    def protect(value):
        literals.append(value)
        return '\x00' + str(len(literals) - 1) + '\x00'
    text = plain_answer(text, protect=protect)
    # Before literal restoration: code and escaped dollars never become money.
    text = re.sub(r'(?<![\w\\$+./-])(-)?\$(-)?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]{2}))?(?![\w$/-]|[.,]\d)',
                  _money_words, text)
    text = spoken_clocks(text)
    text = _pronunciation_cleanup(text)
    return re.sub(r'\x00(\d+)\x00', lambda m: literals[int(m.group(1))], text).strip() or original.strip()


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
