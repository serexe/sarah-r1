"""Offline provider selection and confinement checks for SARAH ACP."""
import asyncio
import os
import sys
from pathlib import Path

# Match actual SARAH child's installed Hermes source, not service venv checkout.
sys.path.insert(0, os.environ.get('HERMES_SOURCE', '/opt/hermes-agent'))
from unittest.mock import patch

import pytest

from bridge import acp_launcher
from bridge.acp_policy import NAMES, SCHEMAS, normalized


def _config(home, provider, model):
    home.mkdir()
    (home / 'config.yaml').write_text(f'model:\n  provider: {provider}\n  default: {model}\n')


def test_default_selection_and_scoped_home(tmp_path, monkeypatch):
    from hermes_constants import get_hermes_home
    dedicated = tmp_path / 'dedicated'
    dedicated.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(dedicated))
    for provider, model, mode, endpoint in (
        ('openai-codex', 'gpt-offline', 'codex_responses', 'https://chatgpt.com/backend-api/codex'),
        ('openrouter', 'vendor/offline', 'chat_completions', 'https://openrouter.ai/api/v1'),
    ):
        global_home = tmp_path / provider
        _config(global_home, provider, model)
        calls = []
        def resolver(**kwargs):
            calls.append((kwargs, get_hermes_home()))
            return dict(provider=provider, api_mode=mode, base_url=endpoint, api_key='fixture-only')
        with patch.object(acp_launcher, 'GLOBAL_HOME', global_home):
            selected, runtime = acp_launcher.resolve_default_runtime(resolver)
        assert selected == model and runtime['provider'] == provider
        assert calls == [({'requested': provider, 'target_model': model}, global_home)]
        assert get_hermes_home() == dedicated


def test_missing_unsupported_or_bad_runtime_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    with patch.object(acp_launcher, 'GLOBAL_HOME', tmp_path / 'absent'):
        with pytest.raises(ValueError, match='acp_global_default_missing'):
            acp_launcher.resolve_default_runtime(lambda **kw: {})
    for provider, model in (('auto', 'test'), ('moa', 'test'), ('openrouter', '')):
        home = tmp_path / ('config-' + provider + '-' + (model or 'blank'))
        _config(home, provider, model)
        with patch.object(acp_launcher, 'GLOBAL_HOME', home):
            with pytest.raises(ValueError, match='acp_global_default_missing'):
                acp_launcher.resolve_default_runtime(lambda **kw: {})
    home = tmp_path / 'bad-runtime'
    _config(home, 'openrouter', 'vendor/offline')
    with patch.object(acp_launcher, 'GLOBAL_HOME', home):
        with pytest.raises(ValueError, match='acp_provider_route_denied'):
            acp_launcher.resolve_default_runtime(lambda **kw: dict(provider='moa', api_mode='chat_completions', base_url='moa://local'))
        with pytest.raises(ValueError, match='acp_provider_route_denied'):
            acp_launcher.resolve_default_runtime(lambda **kw: dict(provider='openrouter', api_mode='unsupported_mode', base_url='https://openrouter.ai/api/v1'))
        with pytest.raises(ValueError, match='acp_provider_route_denied'):
            acp_launcher.resolve_default_runtime(lambda **kw: dict(provider='openrouter', api_mode='chat_completions', base_url='https://openrouter.ai/api/v1', extra_headers={'Authorization': 'fixture-only'}))


def test_installed_non_codex_resolver_uses_global_scoped_secret(tmp_path, monkeypatch):
    home = tmp_path / 'global-runtime'
    _config(home, 'openrouter', 'vendor/offline')
    (home / '.env').write_text('OPENROUTER_API_KEY=offline-placeholder-key\n')
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'dedicated-home'))
    with patch.object(acp_launcher, 'GLOBAL_HOME', home):
        model, runtime = acp_launcher.resolve_default_runtime()
    assert model == 'vendor/offline' and runtime['provider'] == 'openrouter'
    assert runtime['api_mode'] == 'chat_completions'
    assert runtime['api_key'] == 'offline-placeholder-key'
    assert runtime['base_url'].startswith('https://openrouter.ai')
    assert os.environ['HERMES_HOME'] == str(tmp_path / 'dedicated-home')


def test_non_codex_agent_keeps_exact_tools(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    home = tmp_path / 'global'
    _config(home, 'openrouter', 'vendor/offline')
    dedicated = tmp_path / 'dedicated'
    dedicated.mkdir()
    (dedicated / 'config.yaml').write_bytes(Path('bridge/sarah-acp.yaml').read_bytes())
    (dedicated / 'SOUL.md').write_bytes(acp_launcher.REVIEWED_SOUL)
    monkeypatch.setenv('HERMES_HOME', str(dedicated))
    def resolver(**kwargs):
        return dict(provider='openrouter', api_mode='chat_completions',
                    base_url='https://openrouter.ai/api/v1', api_key='fixture-only')
    with patch.object(acp_launcher, 'GLOBAL_HOME', home):
        db = SessionDB(db_path=dedicated / 'state.db')
        server = acp_launcher.compose(asyncio.new_event_loop(), db, resolver)
        state = server.session_manager.create_session(cwd=str(dedicated))
    agent = state.agent
    assert agent.model == 'vendor/offline' and agent.provider == 'openrouter'
    assert normalized(sorted(agent.tools, key=lambda t: t['function']['name'])) == normalized(sorted(SCHEMAS, key=lambda t: t['function']['name']))
    assert agent.valid_tool_names == NAMES and agent._fallback_chain == []
    assert agent.skip_context_files and agent.load_soul_identity is False
    assert agent._memory_store is None and not agent._memory_enabled
    assert agent._skip_mcp_refresh is True
    # Existing session resumes with same history/session but newly configured
    # default; no old-provider pin from persisted model metadata.
    session = state.session_id
    db.append_message(session_id=session, role='user', content='original utterance')
    db.append_message(session_id=session, role='assistant', content='original answer')
    (home / 'config.yaml').write_text('model:\n  provider: openrouter\n  default: vendor/next\n')
    with patch.object(acp_launcher, 'GLOBAL_HOME', home):
        restored = acp_launcher.compose(asyncio.new_event_loop(), db, resolver).session_manager.get_session(session)
    assert restored.session_id == session and restored.agent.model == restored.model == 'vendor/next'
    assert [m['content'] for m in restored.history if m['role'] in ('user','assistant')] == ['original utterance', 'original answer']
