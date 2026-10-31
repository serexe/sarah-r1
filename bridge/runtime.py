"""Codex-only voice with optional exact HA functions; no generic agent routes."""
import asyncio
import os
import json
import re
import sys
import threading
from pathlib import Path
import httpx
from .clock import spoken_clocks
from faster_whisper import WhisperModel

BASE = 'https://chatgpt.com/backend-api/codex'
MODEL = os.getenv('R1_CODEX_MODEL', 'gpt-6.1-sol')
CODEX_TOTAL_SECONDS = 90
SSE_LINE_BYTES = 64 * 1024
SSE_TOTAL_BYTES = 1024 * 1024
TTS_STAGE_SECONDS = 20
TTS_TERMINATE_GRACE = 1


async def _sse_lines(response, deadline):
    # Raw identity bytes: do not let iter_lines or decompression accumulate an
    # unbounded line before our limits run. Count comments/metadata too.
    if response.headers.get('content-encoding', 'identity') != 'identity':
        raise RuntimeError('codex_sse_encoding_denied')
    pending = bytearray()
    total = 0
    async for chunk in response.aiter_raw():
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError('codex_deadline')
        total += len(chunk)
        if total > SSE_TOTAL_BYTES:
            raise RuntimeError('codex_sse_total_too_large')
        # Explicit LF boundaries preserve split UTF-8 and unfinished lines.
        pieces = chunk.split(b'\n')
        for index, piece in enumerate(pieces):
            if len(pending) + len(piece) > SSE_LINE_BYTES:
                raise RuntimeError('codex_sse_line_too_large')
            pending.extend(piece)
            if index < len(pieces) - 1:
                yield bytes(pending).rstrip(b'\r').decode('utf-8')
                pending.clear()
    if pending:
        yield bytes(pending).rstrip(b'\r').decode('utf-8')


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
    ready = True
    reason = 'Tools and Home Assistant disabled; Codex-only voice conversation'
    def __init__(self, source):
        source = Path(source).resolve(strict=True)
        if not (source/'agent/credential_pool.py').is_file():
            raise ValueError('invalid_hermes_source')
        sys.path.insert(0, str(source))
        from agent.credential_pool import load_pool
        from agent.codex_headers import codex_cloudflare_headers
        self.load_pool = load_pool
        self.headers = codex_cloudflare_headers
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

    async def reply(self, text, history=(), dispatch=None):
        # One deadline across all HTTP attempts, not a per-read timeout and not
        # wait_for(to_thread(...)): cancellation closes the owned upstream socket.
        deadline = asyncio.get_running_loop().time() + CODEX_TOTAL_SECONDS
        async with asyncio.timeout_at(deadline):
            inputs = list(history)+[{'role':'user','content':text}]
            results = []
            for _ in range(10):
                try:
                    result = await self._reply(text, history, deadline, inputs, dispatch is not None)
                except Exception:
                    if results: return 'I could not finish summarizing the tool results ('+type(sys.exc_info()[1]).__name__+').'
                    raise
                if isinstance(result, str):
                    return result
                if dispatch is None: raise RuntimeError('codex_tool_denied')
                for call in result:
                    try:
                        outcome = await dispatch(call['name'], json.loads(call['arguments']))
                    except (ValueError, TypeError, KeyError):
                        outcome = {'reply':'Home Assistant request denied. Nothing dispatched.'}
                    results.append(outcome)
                    inputs.extend([call, {'type':'function_call_output','call_id':call['call_id'],'output':json.dumps(outcome)}])
            return 'Tool request limit reached before I could finish the answer.'

    async def _reply(self, text, history, deadline, inputs=None, tools=False):
        pool = self.load_pool('openai-codex')
        entry = pool.select()
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=15), follow_redirects=False, trust_env=False) as client:
            for attempt in range(3):
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError('codex_deadline')
                if entry is None:
                    raise RuntimeError('codex_pool_unavailable_no_fallback')
                token = entry.runtime_api_key
                endpoint = (entry.runtime_base_url or BASE).rstrip('/')
                if entry.provider != 'openai-codex' or endpoint != BASE or not token:
                    raise RuntimeError('codex_route_denied')
                headers = self.headers(token, base_url=BASE)
                headers.update({'Authorization': 'Bearer '+token, 'Accept':'text/event-stream',
                                'Accept-Encoding':'identity'})
                from .ha import TOOLS as HA_TOOLS, LIGHT_GUIDANCE
                from .siyuan import TOOLS as SY_TOOLS, GUIDANCE
                from .calendar import TOOLS as CALENDAR_TOOLS, GUIDANCE as CALENDAR_GUIDANCE
                from datetime import datetime
                from zoneinfo import ZoneInfo
                calendar_clock=' Current server time in '+os.getenv('R1_TIMEZONE','UTC')+': '+datetime.now(ZoneInfo(os.getenv('R1_TIMEZONE','UTC'))).isoformat()+'. Resolve today/tomorrow against this clock, not training knowledge.'
                from .tvtime import TOOLS as TVTIME_TOOLS, GUIDANCE as TVTIME_GUIDANCE
                TOOLS=HA_TOOLS+SY_TOOLS+CALENDAR_TOOLS+TVTIME_TOOLS
                payload = {'model':MODEL, 'instructions':('You are S.A.R.A.H, pronounced Sarah, your R1 voice companion. This identity applies only to this R1 instance. Converse naturally and reply briefly. Interpret free language and contextual followups from conversation; no command phrase or Home Assistant prefix is required. Tools are available on every turn, not mandatory. Ordinary discussion, quoted examples and negation are not action requests. Only supplied HA, SiYuan, Calendar and TV time functions exist. '+LIGHT_GUIDANCE+' '+GUIDANCE+' '+CALENDAR_GUIDANCE+' '+TVTIME_GUIDANCE+' Use ha_get_state for detailed current state, ha_list_services for actual service parameters, and ha_call_service for requested actions without repeated routine approval. No entity/action allowlist or spoken authorization gate applies. Never invent entities, service availability, tool outcomes or physical success. An accepted service is not necessarily a verified outcome. Use actual returned states and errors; do not automatically retry uncertain writes. No host shell, administration or arbitrary network tool exists.' if tools else 'You are S.A.R.A.H, pronounced Sarah, your R1 voice companion. This identity applies only to this R1 instance. Reply briefly in plain spoken English. No tools or Home Assistant actions are available. Never claim actions were performed.'),
                           'input':inputs if inputs is not None else list(history)+[{'role':'user','content':text}], 'tools':TOOLS if tools else [], 'tool_choice':'auto' if tools else 'none', 'parallel_tool_calls':False, 'store':False, 'stream':True,
                           'reasoning':{'effort':'high'}}
                if tools: payload['instructions']+=calendar_clock
                parts=[]; completed=False; output_chars=0; calls=[]
                async with client.stream('POST',BASE+'/responses',headers=headers,json=payload) as response:
                    if response.status_code in (401,403,429):
                        entry=pool.mark_exhausted_and_rotate(status_code=response.status_code,api_key_hint=token,credential_id=entry.id)
                        continue
                    if response.status_code != 200:
                        raise RuntimeError('codex_http_'+str(response.status_code))
                    async for line in _sse_lines(response, deadline):
                        if not line.startswith('data: '):continue
                        if line[6:]=='[DONE]':continue
                        event=json.loads(line[6:]); kind=event.get('type','')
                        if kind=='response.output_text.delta':
                            delta=event.get('delta','')
                            output_chars += len(delta)
                            if output_chars>12000:raise RuntimeError('reply_too_long')
                            parts.append(delta)
                        if kind=='response.output_item.done' and event.get('item',{}).get('type')=='function_call':
                            calls.append(event['item'])
                        if kind=='response.completed':
                            final_calls=[i for i in (event.get('response',{}).get('output') or []) if i.get('type')=='function_call']
                            if final_calls: calls=final_calls
                            completed=True
                            break  # Completion is terminal; don't await an upstream EOF.
                        if kind in ('error','response.failed','response.incomplete'):
                            raise RuntimeError('codex_response_failed')
                result=''.join(parts).strip()
                if calls:
                    if not completed or not tools or len(calls)!=1: raise RuntimeError('codex_tool_denied')
                    call=calls[0]
                    if set(call)-{'type','id','status','call_id','name','arguments'} or not isinstance(call.get('call_id'),str) or not isinstance(call.get('arguments'),str) or len(call['arguments'])>20000: raise RuntimeError('codex_tool_denied')
                    return [{k:call[k] for k in ('type','call_id','name','arguments')}]
                if not completed or not result:raise RuntimeError('codex_incomplete_response')
                return result
        raise RuntimeError('codex_pool_exhausted_no_fallback')

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
