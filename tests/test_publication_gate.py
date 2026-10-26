"""Synthetic fail-closed publication-input controls. No live credentials."""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bridge.tvtime import TVTimeDispatcher
from test_public_defaults import scanner


def inventory(root, *paths):
    (root / 'PUBLICATION-MANIFEST.txt').write_text(
        '\n'.join(('PUBLICATION-MANIFEST.txt', *paths)) + '\n')


@pytest.mark.parametrize('directory', ['build', 'package', '.venv', '.verify', '__pycache__', '.pytest_cache'])
def test_excluded_directories_never_hide_source_or_secrets(tmp_path, directory):
    target = tmp_path / directory / 'source.py'
    target.parent.mkdir()
    target.write_text('TOKEN="' + 'synthetic' * 5 + '"\n')
    inventory(tmp_path, directory + '/source.py')
    kinds = {kind for _, _, kind in scanner.scan(tmp_path)}
    assert 'forbidden-directory' in kinds
    assert 'literal-secret-assignment' in kinds


@pytest.mark.parametrize('name', ['secret.env', '.env.local', '.env.production', 'credentials.env', 'private.env.backup'])
def test_private_environment_filenames_rejected(tmp_path, name):
    (tmp_path / name).write_text('synthetic configuration')
    inventory(tmp_path, name)
    assert any(kind == 'private-or-generated-file' for _, _, kind in scanner.scan(tmp_path))


@pytest.mark.parametrize('assignment', ['API_KEY=', 'access_token: ', '"password": ', 'export SECRET = '])
def test_unquoted_and_mapping_secret_assignments(tmp_path, assignment):
    (tmp_path / 'source.py').write_text(assignment + 'synthetic' * 5)
    inventory(tmp_path, 'source.py')
    assert any(kind == 'literal-secret-assignment' for _, _, kind in scanner.scan(tmp_path))


def test_allowed_host_does_not_allow_url_credentials(tmp_path):
    inventory(tmp_path, 'source.py')
    for url in ('https://' + 'chatgpt.com/?access_token=' + 'synthetic' * 5,
                'https://' + 'synthetic:synthetic' + '@' + 'chatgpt.com/'):
        (tmp_path / 'source.py').write_text(url)
        assert any(kind == 'url-credentials' for _, _, kind in scanner.scan(tmp_path))


@pytest.mark.parametrize('name,content', [('ignored.py', b'ordinary source'), ('.hidden', b'hidden'), ('payload.bin', b'\x00synthetic\xff')])
def test_unmanifested_ignored_hidden_binary_files_fail_closed(tmp_path, name, content):
    inventory(tmp_path)
    (tmp_path / '.gitignore').write_text('*\n')
    (tmp_path / name).write_bytes(content)
    assert any(path == name and kind == 'unmanifested-file' for path, _, kind in scanner.scan(tmp_path))


def test_missing_manifest_and_missing_root_fail_closed(tmp_path):
    assert scanner.scan(tmp_path)
    assert scanner.scan(tmp_path / 'absent')


def test_manifest_missing_entry_and_binary_fail_closed(tmp_path):
    inventory(tmp_path, 'missing.py', 'binary.txt')
    (tmp_path / 'binary.txt').write_bytes(b'\x00binary')
    kinds = {kind for _, _, kind in scanner.scan(tmp_path)}
    assert 'missing-manifest-entry' in kinds
    assert 'unreviewed-binary' in kinds


def test_private_key_under_package_is_not_skipped(tmp_path):
    (tmp_path / 'package').mkdir()
    (tmp_path / 'package' / 'source.txt').write_text('-----BEGIN ' + 'PRIVATE KEY-----')
    inventory(tmp_path, 'package/source.txt')
    kinds = {kind for _, _, kind in scanner.scan(tmp_path)}
    assert 'forbidden-directory' in kinds
    assert 'private-key' in kinds


@pytest.mark.parametrize('entry', ['../outside', '/absolute', 'source.py/../other', './source.py', 'PUBLICATION-MANIFEST.txt'])
def test_malformed_or_duplicate_inventory_rejected(tmp_path, entry):
    inventory(tmp_path, entry)
    assert any(kind == 'invalid-or-missing-manifest' for _, _, kind in scanner.scan(tmp_path))


def test_unreadable_directory_is_finding(tmp_path, monkeypatch):
    inventory(tmp_path)
    def fail_walk(root, followlinks, onerror):
        onerror(PermissionError('synthetic denied'))
        return iter(())
    monkeypatch.setattr(scanner.os, 'walk', fail_walk)
    assert any(kind == 'unreadable-directory' for _, _, kind in scanner.scan(tmp_path))


def test_constructor_rejects_relative_tv_script():
    with pytest.raises(ValueError, match='tvtime_script_must_be_absolute'):
        TVTimeDispatcher('relative.py')


def test_reviewed_historical_png_only(tmp_path):
    root = Path(__file__).resolve().parents[1]
    data = (root / scanner.REVIEWED_ASSET).read_bytes()
    target = tmp_path / scanner.REVIEWED_ASSET
    target.parent.mkdir()
    target.write_bytes(data)
    inventory(tmp_path, scanner.REVIEWED_ASSET)
    assert scanner.reviewed_png(data)
    assert scanner.scan(tmp_path) == []
    target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    assert scanner.scan(tmp_path)


@pytest.mark.parametrize('name', ['assets/another.png', 'renamed.png', 'assets/nested/sarah-r1-native-redacted.png'])
def test_reviewed_image_new_path_or_additional_image_rejected(tmp_path, name):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((root / scanner.REVIEWED_ASSET).read_bytes())
    inventory(tmp_path, name)
    assert any(kind == 'private-or-generated-file' for _, _, kind in scanner.scan(tmp_path))


@pytest.mark.parametrize('kind', [b'tEXt', b'eXIf', b'iTXt'])
def test_reviewed_png_metadata_rejected_even_if_hash_reapproved(tmp_path, monkeypatch, kind):
    import hashlib
    import struct
    import zlib
    data = (Path(__file__).resolve().parents[1] / scanner.REVIEWED_ASSET).read_bytes()
    payload = b'synthetic metadata'
    chunk = struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
    changed = data[:33] + chunk + data[33:]
    assert not scanner.reviewed_png(changed)
    monkeypatch.setattr(scanner, 'REVIEWED_SHA256', hashlib.sha256(changed).hexdigest())
    target = tmp_path / scanner.REVIEWED_ASSET
    target.parent.mkdir()
    target.write_bytes(changed)
    inventory(tmp_path, scanner.REVIEWED_ASSET)
    assert scanner.scan(tmp_path)


@pytest.mark.parametrize('suffix', [b'private trailing bytes', b'\x00'])
def test_reviewed_png_trailing_data_rejected(suffix):
    data = (Path(__file__).resolve().parents[1] / scanner.REVIEWED_ASSET).read_bytes()
    assert not scanner.reviewed_png(data + suffix)


def test_private_literal_review_remains_explicit(tmp_path):
    inventory(tmp_path, 'source.py')
    (tmp_path / 'source.py').write_text('synthetic owner calendar canary')
    assert any(kind == 'private-literal' for _, _, kind in scanner.scan(tmp_path, ('synthetic owner calendar canary',)))


def test_tv_relative_path_rejected_and_configuration_captured(tmp_path, monkeypatch):
    script = tmp_path / 'workflow.py'
    script.write_text('pass\n')
    monkeypatch.chdir(tmp_path)
    with patch.dict(os.environ, {'R1_ENABLE_TVTIME': '1', 'R1_TVTIME_SCRIPT': 'workflow.py'}, clear=True):
        assert TVTimeDispatcher.from_env() is None
        os.environ['R1_TVTIME_SCRIPT'] = str(script)
        dispatcher = TVTimeDispatcher.from_env()
        assert dispatcher is not None
        os.environ['R1_TVTIME_SCRIPT'] = str(tmp_path / 'other.py')
        assert dispatcher.command == ('/usr/bin/python3', str(script))
