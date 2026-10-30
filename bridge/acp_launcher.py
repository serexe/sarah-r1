"""Dedicated composition of installed Hermes ACP. Never stock broad ACP CLI.

Run only as owned stdio child. Integration credentials stay in voice server.
Provider resolver reuses supported shared global Codex OAuth pool, including
supported token rotation and auth bookkeeping; profile is not an OAuth sandbox.
"""
import asyncio
import contextlib
import json
import os
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

    class ScopedAgent(AIAgent):
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
        if state is None or not state.is_running or state.cancel_event.is_set():
            raise ValueError('acp_no_active_turn')
        future = asyncio.run_coroutine_threadsafe(server._conn.ext_method('sarah/dispatch', {
            'sessionId': sid, 'policy': identity(), 'name': name, 'arguments': args}), loop)
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
                            ephemeral_system_prompt=GUIDANCE, session_db=db, session_id=session_id,
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
