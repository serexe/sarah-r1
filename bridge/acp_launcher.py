"""Dedicated composition of installed Hermes ACP. Never stock broad ACP CLI.

Run only as owned stdio child. Integration credentials stay in voice server.
Provider resolver reuses supported shared global Codex OAuth pool, including
supported token rotation and auth bookkeeping; profile is not an OAuth sandbox.
"""
import asyncio
from contextvars import ContextVar
import contextlib
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import sys

SOURCE = Path('/opt/hermes-agent')
PROFILE = Path('/var/lib/sarah/acp')
REVIEWED_SOUL = (
    b'# Sarah ACP bootstrap sentinel\n\n'
    b'Inert dedicated-profile bootstrap marker; not a persona or runtime context.\n'
)


def validate_profile():
    """Exact dedicated bootstrap bytes only; never seed or repair at launch.

    Installed Hermes seeds absent/legacy SOUL.md even with context loading off.
    This non-legacy inert marker prevents seeding; agent context stays disabled.
    """
    expected = Path(__file__).with_name('sarah-acp.yaml').read_bytes()
    config = PROFILE/'config.yaml'
    if not PROFILE.is_dir() or config.is_symlink() or config.read_bytes() != expected:
        raise ValueError('acp_reviewed_profile_required')
    for name in ('.env', 'AGENTS.md'):
        path = PROFILE/name
        if path.exists() or path.is_symlink():
            raise ValueError('acp_unreviewed_profile_content')
    soul = PROFILE/'SOUL.md'
    try:
        if not soul.is_symlink() and soul.read_bytes() == REVIEWED_SOUL:
            return
    except OSError:
        pass
    raise ValueError('acp_unreviewed_profile_content')


def compose(loop, db, runtime_resolver=None):
    from acp_adapter.server import HermesACPAgent
    from acp_adapter.session import SessionManager
    from run_agent import AIAgent
    from tools.registry import registry
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from .acp_policy import NAMES, SCHEMAS, TOOLSET, GUIDANCE, identity, validate, normalized

    turn_owner = ContextVar("sarah_turn_owner", default=None)

    class ScopedAgent(AIAgent):
        def run_conversation(self, user_message, system_message=None,
                             conversation_history=None, task_id=None,
                             stream_callback=None, persist_user_message=None,
                             persist_user_timestamp=None, moa_config=None):
            # API-only context: keep wire text, durable dialogue and cached
            # system prompt literal. Sample on EVERY turn, never on restore.
            if not isinstance(user_message, str):
                raise ValueError('acp_text_prompt_required')
            now = datetime.now(timezone.utc)
            local = now.astimezone(ZoneInfo('America/Chicago'))
            context = (
                'Server clock snapshot for this turn: UTC: '
                + now.isoformat(timespec='seconds') + '; America/Chicago: '
                + local.isoformat(timespec='seconds') + ' ' + (local.tzname() or 'America/Chicago') + '. '
                'Use this sampled clock for current time and today/tomorrow; '
                'historical timestamps are not current. This is a turn-start '
                'snapshot, not a continuously running clock.\n\n')
            turn_owner.set(getattr(self, "_sarah_nonce", None))
            return super().run_conversation(
                context + user_message, system_message=system_message,
                conversation_history=conversation_history, task_id=task_id,
                stream_callback=stream_callback,
                persist_user_message=user_message if persist_user_message is None else persist_user_message,
                persist_user_timestamp=persist_user_timestamp, moa_config=moa_config)

        def _execute_tool_calls(self, assistant_message, *args, **kwargs):
            calls = assistant_message.tool_calls or []
            for call in calls:
                if call.function.name not in NAMES:
                    raise ValueError('acp_scoped_tool_denied')
            return super()._execute_tool_calls(assistant_message, *args, **kwargs)

    holder = {}
    def dispatch(name, args, **kwargs):
        validate(name, args)
        sid = kwargs.get('task_id')
        server = holder['server']
        state = server.session_manager.get_session(sid) if sid else None
        if (state is None or not state.is_running or state.cancel_event.is_set()
                or not turn_owner.get() or turn_owner.get() != getattr(state.agent, '_sarah_nonce', None)):
            raise ValueError('acp_no_active_turn')
        future = asyncio.run_coroutine_threadsafe(server._conn.ext_method('sarah/dispatch', {
            'sessionId': sid, 'policy': identity(), 'name': name, 'arguments': args, 'nonce': turn_owner.get()}), loop)
        try:
            return json.dumps(future.result(timeout=100))
        finally:
            if not future.done(): future.cancel()

    # run_agent imports/discovers builtins first; overwrite colliding HA names
    # only inside this dedicated child registry, never in installed source.
    for schema in SCHEMAS:
        fn = schema['function']
        name = fn['name']
        registry.register(name=name, toolset=TOOLSET, schema=fn,
                          handler=lambda args, _name=name, **kw: dispatch(_name, args, **kw),
                          check_fn=lambda: True, override=True)

    def factory(*, session_id, cwd):
        runtime = (runtime_resolver or resolve_runtime_provider)(requested='openai-codex')
        if runtime.get('provider') != 'openai-codex' or runtime.get('api_mode') not in ('codex_responses', 'responses'):
            raise ValueError('acp_provider_route_denied')
        if runtime.get('base_url', '').rstrip('/') != 'https://chatgpt.com/backend-api/codex':
            raise ValueError('acp_provider_endpoint_denied')
        agent = ScopedAgent(model='gpt-6.1-sol', provider=runtime['provider'],
                            api_key=runtime.get('api_key'), base_url=runtime.get('base_url'),
                            api_mode=runtime.get('api_mode'), enabled_toolsets=[TOOLSET],
                            disabled_toolsets=[], quiet_mode=True, max_iterations=10,
                            skip_context_files=True, load_soul_identity=False, skip_memory=True,
                            ephemeral_system_prompt=GUIDANCE + (
                                ' Use the server clock snapshot supplied with the current turn '
                                'for current time; no clock tool is required. Never treat '
                                'conversation-start or historical timestamps as current.'),
                            session_db=db, session_id=session_id,
                            fallback_model=None, checkpoints_enabled=False, platform='acp')
        if (normalized(sorted(agent.tools, key=lambda t: t['function']['name'])) != normalized(sorted(SCHEMAS, key=lambda t: t['function']['name']))
                or agent.valid_tool_names != NAMES):
            raise ValueError('acp_effective_schema_mismatch')
        if agent._fallback_chain:
            raise ValueError('acp_fallback_denied')
        agent._print_fn = lambda *a, **kw: print(*a, file=sys.stderr)
        agent.session_cwd = cwd
        agent._skip_mcp_refresh = True
        return agent

    class ScopedSessions(SessionManager):
        def _make_agent(self, *, session_id, cwd, **kwargs):
            # Installed no-arg factory loses the ACP persistence identity.
            # Preserve existing manager persistence with exact construction ID.
            return self._agent_factory(session_id=session_id, cwd=cwd)

    class SarahACP(HermesACPAgent):
        async def ext_method(self, method, params):
            if method == 'sarah/policy' and params == {}:
                return {'policy': identity(), 'schemas': SCHEMAS}
            if method == 'sarah/turn' and isinstance(params, dict) and set(params) == {'sessionId','nonce','dialogue'}:
                state = self.session_manager.get_session(params['sessionId'])
                nonce, dialogue = params['nonce'], params['dialogue']
                if (state is None or state.is_running or not isinstance(nonce,str) or len(nonce)!=64
                        or any(c not in '0123456789abcdef' for c in nonce)
                        or not isinstance(dialogue,list) or len(dialogue)>4000):
                    raise ValueError('acp_turn_binding_denied')
                for i,m in enumerate(dialogue):
                    if (not isinstance(m,dict) or set(m)!={'role','content'}
                            or m['role'] != ('user' if i%2==0 else 'assistant')
                            or not isinstance(m['content'],str)):
                        raise ValueError('acp_local_history_denied')
                if len(dialogue)%2 or sum(len(m['content']) for m in dialogue)>128000:
                    raise ValueError('acp_local_history_denied')
                if dialogue:
                    head = state.agent.session_id
                    for message in dialogue:
                        db.append_message(session_id=head, role=message['role'], content=message['content'])
                    state.history = db.get_messages_as_conversation(head)
                state.agent._sarah_nonce = nonce
                return {}
            raise ValueError('acp_extension_denied')

        async def load_session(self, cwd, session_id, mcp_servers=None, **kwargs):
            if mcp_servers or self.session_manager.get_session(session_id) is None:
                raise ValueError('acp_exact_session_missing')
            return await super().load_session(cwd, session_id, [], **kwargs)

        async def _register_session_mcp_servers(self, state, mcp_servers):
            if mcp_servers: raise ValueError('acp_mcp_denied')

    server = SarahACP(session_manager=ScopedSessions(agent_factory=factory, db=db))
    holder['server'] = server
    return server


async def serve():
    import acp
    from hermes_state import SessionDB
    db = SessionDB(db_path=PROFILE/'state.db')
    await acp.run_agent(compose(asyncio.get_running_loop(), db))


def main():
    # Must be provisioned deliberately after review. No clone, .env, memory,
    # skills, plugins, or inherited profile configuration.
    validate_profile()
    os.environ['HERMES_HOME'] = str(PROFILE)
    sys.path.insert(0, str(SOURCE))
    with contextlib.redirect_stdout(sys.stderr):
        # Imports can print. Protocol stdout remains clean after imports.
        import acp_adapter.server
        import run_agent
    asyncio.run(serve())


if __name__ == '__main__': main()
