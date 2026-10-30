"""Existing-Hermes ACP seam; admission requires reviewed dedicated profile.

Durable binding adapted from friend's acp_runtime.py. Deployed STT/TTS retained.
"""
import asyncio
import threading
from pathlib import Path

from .acp_client import ACPClient, ACPConfig, ACPError, settle
from .runtime import VoiceRuntime


class ACPRuntime(VoiceRuntime):
    backend = 'acp'
    ready = False
    reason = 'acp_reviewed_profile_required'

    def __init__(self, store, source, config=None):
        # Speech initialization only. No provider resolution/model load here.
        self.whisper = None
        self.lock = threading.Lock()
        self.store = store
        self.source = Path(source)
        self.config = config or ACPConfig(cwd='/var/lib/sarah/acp/workspace')
        from .acp_launcher import PROFILE, validate_profile
        try:
            if self.config.cwd == str(PROFILE/'workspace'):
                validate_profile()
                self.ready = True
        except (OSError, ValueError):
            self.ready = False
        if self.ready:
            self.reason = 'Scoped Hermes ACP active; shared Codex OAuth pool; cancelled or uncertain sessions require a fresh conversation. No automatic fallback or replay.'
        self.store.db.execute('''CREATE TABLE IF NOT EXISTS acp_sessions(
            device TEXT NOT NULL, conversation TEXT NOT NULL,
            backend TEXT NOT NULL, session TEXT NOT NULL, state TEXT NOT NULL,
            PRIMARY KEY(device,conversation), UNIQUE(backend,session))''')

    async def reply(self, *args, **kwargs):
        # Never inherit VoiceRuntime's direct Codex route, even if mis-called.
        raise ACPError(self.reason)

    async def reply_turn(self, text, history, *, device, conversation, dispatch=None):
        # Durable binding owns ACP tool/receipt execution.
        return await self._reply_bound(text, history, device=device,
                                       conversation=conversation, dispatch=dispatch)

    async def _reply_bound(self, text, history, *, device, conversation, dispatch=None):
        """Exact session/policy binding; no new-session fallback or prompt replay."""
        self.store.own(device, conversation)
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ACPError('acp_invalid_prompt')
        if text.lstrip().startswith('/'):
            raise ACPError('acp_commands_denied')
        row = self.store.db.execute(
            'SELECT backend,session,state FROM acp_sessions WHERE device=? AND conversation=?',
            (device, conversation)).fetchone()
        if row and (row['backend'] != self.config.identity or row['state'] != 'ready'):
            raise ACPError('acp_session_uncertain_or_changed')
        prior = self.store.db.execute(
            "SELECT 1 FROM turns WHERE device=? AND conversation=? AND state='done' LIMIT 1",
            (device, conversation)).fetchone()
        if not row and (history or prior):
            raise ACPError('acp_backend_requires_new_conversation')
        client = None
        admitted = False
        try:
            async with asyncio.timeout(self.config.timeout):
                client = await ACPClient.connect(self.config)
                capabilities = await client.initialize()
                if not isinstance(capabilities, dict) or capabilities.get('loadSession') is not True:
                    raise ACPError('acp_session_load_unsupported')
                from .acp_policy import identity, SCHEMAS
                policy = await client.request('_sarah/policy', {})
                if policy != {'policy': identity(), 'schemas': SCHEMAS}:
                    raise ACPError('acp_policy_mismatch')
                params = {'cwd': self.config.cwd, 'mcpServers': []}
                if row:
                    session_id = row['session']
                    await client.request('session/load', {**params, 'sessionId': session_id})
                else:
                    result = await client.request('session/new', params)
                    session_id = result.get('sessionId')
                    if (not isinstance(session_id, str) or not session_id or len(session_id) > 256
                            or any(ord(c) < 32 for c in session_id)):
                        raise ACPError('acp_invalid_session')
                    self.store.db.execute('INSERT INTO acp_sessions VALUES(?,?,?,?,?)',
                        (device, conversation, self.config.identity, session_id, 'ready'))
                claimed = self.store.db.execute(
                    "UPDATE acp_sessions SET state='inflight' WHERE device=? AND conversation=? AND state='ready'",
                    (device, conversation))
                if claimed.rowcount != 1:
                    raise ACPError('acp_session_busy')
                admitted = True
                client.dispatch = dispatch
                answer = await client.prompt(session_id, text)
                self.store.db.execute(
                    "UPDATE acp_sessions SET state='ready' WHERE device=? AND conversation=?",
                    (device, conversation))
                admitted = False
                return answer
        except BaseException:
            if admitted:
                self.store.db.execute(
                    "UPDATE acp_sessions SET state='uncertain' WHERE device=? AND conversation=?",
                    (device, conversation))
            raise
        finally:
            if client is not None:
                async def cleanup():
                    if admitted:
                        await client.cancel()
                    await client.close()
                await settle(asyncio.create_task(cleanup()))


def create_runtime(store, source, backend='codex'):
    # Manual selector only. Never automatic backend fallback or prompt replay.
    if backend == 'codex':
        return VoiceRuntime(source)
    if backend == 'acp':
        return ACPRuntime(store, source)
    raise ValueError('unsupported_voice_backend')
