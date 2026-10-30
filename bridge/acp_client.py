"""Bounded ACP v1 stdio transport, adapted from friend's acp_client.py.

Only existing Hermes ACP. No shell, client filesystem/terminal, or permission grants.
"""
import asyncio
import contextlib
import hashlib
import json
import math
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path


class ACPError(RuntimeError):
    """Local reason codes only; never forward raw agent errors/payloads."""


async def settle(task):
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


@dataclass(frozen=True)
class ACPConfig:
    cwd: str
    command: tuple[str, ...] = (sys.executable, '-B', '-m', 'bridge.acp_launcher')
    timeout: float = 120

    def __post_init__(self):
        if not Path(self.cwd).is_absolute() or '\0' in self.cwd:
            raise ValueError('acp_absolute_cwd_required')
        if self.command != (sys.executable, '-B', '-m', 'bridge.acp_launcher'):
            raise ValueError('acp_dedicated_sarah_command_required')
        if not math.isfinite(self.timeout) or not 1 <= self.timeout <= 600:
            raise ValueError('acp_invalid_timeout')

    @property
    def identity(self):
        from .acp_policy import identity
        source = Path('/opt/hermes-agent')
        installed = {f: hashlib.sha256((source/f).read_bytes()).hexdigest() for f in
                     ('acp_adapter/server.py', 'acp_adapter/session.py', 'run_agent.py',
                      'agent/agent_init.py', 'agent/tool_executor.py', 'model_tools.py',
                      'tools/registry.py', 'toolsets.py', 'agent/conversation_loop.py',
                      'agent/agent_runtime_helpers.py', 'hermes_cli/runtime_provider.py',
                      'hermes_cli/auth.py', 'agent/credential_pool.py')}
        return hashlib.sha256(json.dumps([self.cwd, self.command, identity(), installed], sort_keys=True).encode()).hexdigest()


class ACPClient:
    LINE_BYTES = 256 * 1024
    TOTAL_BYTES = 4 * 1024 * 1024
    MAX_FRAMES = 8192
    ANSWER_CHARS = 12000

    def __init__(self, reader, writer, process=None):
        self.reader, self.writer, self.process = reader, writer, process
        self.sequence = self.total_bytes = self.frames = 0
        self.session_id = None
        self.collecting = False
        self.parts = []
        self.answer_chars = 0
        self.dispatch = None

    @classmethod
    async def connect(cls, config):
        # No inherited bridge/admin/provider secrets or HERMES_HOME overrides.
        # Preserve public calendar schema timezone, not arbitrary environment.
        from .calendar import ZONE
        env = {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
               'R1_TIMEZONE': ZONE}
        spawn = asyncio.create_task(asyncio.create_subprocess_exec(
            *config.command, cwd=str(Path(__file__).resolve().parents[1]), env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=cls.LINE_BYTES,
            start_new_session=True))
        try:
            process = await asyncio.shield(spawn)
        except BaseException:
            async def cleanup_spawn():
                with contextlib.suppress(Exception):
                    process = await spawn
                    await cls(process.stdout, process.stdin, process).close()
            await settle(asyncio.create_task(cleanup_spawn()))
            raise
        return cls(process.stdout, process.stdin, process)

    async def send(self, message):
        data = (json.dumps({'jsonrpc': '2.0', **message}, ensure_ascii=False) + '\n').encode()
        if len(data) > self.LINE_BYTES:
            raise ACPError('acp_outgoing_frame_limit')
        self.writer.write(data)
        await self.writer.drain()

    async def request(self, method, params):
        self.sequence += 1
        request_id = self.sequence
        await self.send({'id': request_id, 'method': method, 'params': params})
        while True:
            try:
                line = await self.reader.readline()
            except (ValueError, asyncio.LimitOverrunError):
                raise ACPError('acp_frame_limit') from None
            if not line or not line.endswith(b'\n'):
                raise ACPError('acp_disconnected')
            self.frames += 1
            self.total_bytes += len(line)
            if len(line) > self.LINE_BYTES or self.total_bytes > self.TOTAL_BYTES or self.frames > self.MAX_FRAMES:
                raise ACPError('acp_stream_limit')
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                raise ACPError('acp_invalid_json') from None
            if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
                raise ACPError('acp_invalid_message')
            if 'method' in message:
                await self.handle_agent(message)
                continue
            if message.get('id') != request_id or isinstance(message.get('id'), bool):
                raise ACPError('acp_unexpected_response')
            if 'error' in message:
                raise ACPError('acp_request_failed')
            if not isinstance(message.get('result'), dict):
                raise ACPError('acp_invalid_result')
            return message['result']

    async def handle_agent(self, message):
        if 'id' in message:
            if message['method'] == '_sarah/dispatch':
                from .acp_policy import identity, validate
                p = message.get('params')
                if (not self.collecting or self.dispatch is None or not isinstance(p, dict)
                        or set(p) != {'sessionId', 'policy', 'name', 'arguments'}
                        or p['sessionId'] != self.session_id or p['policy'] != identity()):
                    raise ACPError('acp_dispatch_binding_denied')
                validate(p['name'], p['arguments'])
                outcome = await self.dispatch(p['name'], p['arguments'])
                await self.send({'id': message['id'], 'result': outcome})
            elif message['method'] == 'session/request_permission':
                await self.send({'id': message['id'], 'result': {'outcome': {'outcome': 'cancelled'}}})
            else:
                await self.send({'id': message['id'], 'error': {'code': -32601, 'message': 'Unsupported client method'}})
            return
        if message['method'] != 'session/update' or not self.collecting:
            return
        params = message.get('params')
        if not isinstance(params, dict) or params.get('sessionId') != self.session_id:
            raise ACPError('acp_session_mismatch')
        update = params.get('update')
        if not isinstance(update, dict):
            raise ACPError('acp_invalid_update')
        if update.get('sessionUpdate') != 'agent_message_chunk':
            return  # No thoughts, tool output, usage, or history replay spoken.
        content = update.get('content')
        if not isinstance(content, dict) or content.get('type') != 'text':
            return
        text = content.get('text')
        if not isinstance(text, str):
            raise ACPError('acp_invalid_text')
        self.answer_chars += len(text)
        if self.answer_chars > self.ANSWER_CHARS:
            raise ACPError('acp_answer_limit')
        self.parts.append(text)

    async def initialize(self):
        result = await self.request('initialize', {
            'protocolVersion': 1, 'clientCapabilities': {},
            'clientInfo': {'name': 'sarah', 'version': '1'}})
        if result.get('protocolVersion') != 1:
            raise ACPError('acp_version_mismatch')
        return result.get('agentCapabilities') or {}

    async def prompt(self, session_id, text):
        self.session_id = session_id
        self.parts = []
        self.answer_chars = 0
        self.collecting = True
        result = await self.request('session/prompt', {
            'sessionId': session_id, 'prompt': [{'type': 'text', 'text': text}]})
        self.collecting = False
        answer = ''.join(self.parts).strip()
        if result.get('stopReason') != 'end_turn' or not answer:
            raise ACPError('acp_incomplete_turn')
        return answer

    async def cancel(self):
        if self.session_id is not None:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(1):
                    await self.send({'method': 'session/cancel', 'params': {'sessionId': self.session_id}})

    async def close(self):
        self.writer.close()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(1):
                await self.writer.wait_closed()
        if self.process is not None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                async with asyncio.timeout(1):
                    await self.process.wait()
            except TimeoutError:
                pass
            finally:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
