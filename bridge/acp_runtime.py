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

    def legacy_migration_plan(self, *, device, conversation):
        """Operator-only dry-run fingerprint. Never called by request admission."""
        self.store.own(device, conversation)
        if self.store.db.execute(
                'SELECT 1 FROM acp_sessions WHERE device=? AND conversation=?',
                (device, conversation)).fetchone():
            raise ACPError('acp_migration_binding_exists')
        rows = self.store.db.execute(
            'SELECT id,state,transcript,detail FROM turns WHERE device=? AND conversation=? ORDER BY rowid',
            (device, conversation)).fetchall()
        history = []
        for row in rows:
            # Failed requests are never imported as executable pending prompts.
            # Unknown/cancelled/active outcomes need separate reconciliation.
            if row['state'] not in ('done', 'error'):
                raise ACPError('acp_migration_reconciliation_required')
            if row['state'] == 'error':
                if self.store.db.execute('SELECT 1 FROM dispatches WHERE turn=?', (row['id'],)).fetchone():
                    raise ACPError('acp_migration_reconciliation_required')
                continue
            if not row['transcript'].strip() or not row['detail'].strip():
                raise ACPError('acp_migration_history_incomplete')
            history.extend([{'role': 'user', 'content': row['transcript']},
                            {'role': 'assistant', 'content': row['detail']}])
        if not history or len(history) > 2000 or sum(len(m['content']) for m in history) > 128000:
            raise ACPError('acp_migration_history_bounds')
        import hashlib
        import json
        snapshot = [device, conversation, self.config.identity, [dict(r) for r in rows]]
        digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
        return {'digest': digest, 'completed_turns': len(history) // 2}

    def migrate_legacy(self, *, device, conversation, expected_digest, session_db):
        """Explicit operator migration using supported Hermes SessionDB APIs.

        No HTTP/model path invokes this. Requires accepted dry-run fingerprint,
        preserves existing conversation, imports only literal completed dialogue,
        and never submits/retries a prompt. Any partial write stays fail-closed.
        Caller must supply the reviewed dedicated profile DB, never shared DB.
        """
        import uuid
        if Path(session_db.db_path).resolve() != (Path(self.config.cwd).parent / 'state.db').resolve():
            raise ACPError('acp_migration_dedicated_db_required')
        self.store.db.execute('BEGIN IMMEDIATE')
        try:
            plan = self.legacy_migration_plan(device=device, conversation=conversation)
            if expected_digest != plan['digest']:
                raise ACPError('acp_migration_snapshot_changed')
            rows = self.store.db.execute(
                "SELECT transcript,detail FROM turns WHERE device=? AND conversation=? AND state='done' ORDER BY rowid",
                (device, conversation)).fetchall()
            history = [message for row in rows for message in (
                {'role': 'user', 'content': row['transcript']},
                {'role': 'assistant', 'content': row['detail']})]
            session_id = str(uuid.uuid4())
            self.store.db.execute('INSERT INTO acp_sessions VALUES(?,?,?,?,?)',
                (device, conversation, self.config.identity, session_id, 'migrating'))
            self.store.db.execute('COMMIT')
        except BaseException:
            self.store.db.execute('ROLLBACK')
            raise
        # Reserve durable ownership before writing other DB. A crash/failure
        # cannot turn a partial import into a fresh session or a prompt replay.
        if session_db.get_session(session_id) is not None:
            raise ACPError('acp_migration_session_exists')
        session_db.create_session(session_id=session_id, source='acp', model='gpt-6.1-sol',
                                  model_config={'cwd': self.config.cwd})
        session_db.replace_messages(session_id, history)
        restored = session_db.get_messages_as_conversation(session_id)
        if [{'role': m['role'], 'content': m.get('content')} for m in restored] != history:
            raise ACPError('acp_migration_history_mismatch')
        self.store.db.execute(
            "UPDATE acp_sessions SET state='ready' WHERE device=? AND conversation=? AND session=? AND state='migrating'",
            (device, conversation, session_id))
        return plan

    async def reply(self, *args, **kwargs):
        # Never inherit VoiceRuntime's direct Codex route, even if mis-called.
        raise ACPError(self.reason)

    def _direct_rows(self, device, conversation):
        if not self.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='response_metrics'").fetchone():
            return []
        return self.store.db.execute("""SELECT t.id,t.transcript,t.detail FROM turns t
            JOIN response_metrics m ON m.turn=t.id WHERE t.device=? AND t.conversation=?
            AND t.state='done' AND m.route='direct_clock' ORDER BY t.rowid""",(device,conversation)).fetchall()

    def check_direct_reply(self, *, device, conversation):
        # A clock shortcut cannot evade existing migration/uncertain-session gates.
        self.store.own(device,conversation)
        row=self.store.db.execute('SELECT backend,state FROM acp_sessions WHERE device=? AND conversation=?',(device,conversation)).fetchone()
        if row and (row['backend']!=self.config.identity or row['state']!='ready'):
            raise ACPError('acp_session_uncertain_or_changed')
        if not row:
            local={r['id'] for r in self._direct_rows(device,conversation)}
            prior=self.store.db.execute("SELECT id FROM turns WHERE device=? AND conversation=? AND state='done'",(device,conversation)).fetchall()
            if any(r['id'] not in local for r in prior):
                raise ACPError('acp_backend_requires_new_conversation')

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
        direct_rows=self._direct_rows(device,conversation)
        local_ids={r['id'] for r in direct_rows}
        prior = self.store.db.execute(
            "SELECT id FROM turns WHERE device=? AND conversation=? AND state='done'",
            (device, conversation)).fetchall()
        if not row and ((history and not direct_rows) or any(r['id'] not in local_ids for r in prior)):
            raise ACPError('acp_backend_requires_new_conversation')
        if direct_rows:
            # Literal completed local dialogue; not a tool receipt or a replay.
            import json
            context=[{'user':r['transcript'],'assistant':r['detail']} for r in direct_rows[-4:]]
            text='Completed local-clock dialogue (context only):\n'+json.dumps(context)+'\nCurrent user request:\n'+text
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
