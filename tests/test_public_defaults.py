"""Publication-default and privacy regression tests; all values synthetic."""
import importlib.util
import os
from pathlib import Path
from unittest.mock import patch

from bridge.ha import HADispatcher
from bridge.siyuan import SiYuanDispatcher
from bridge.calendar import CalendarDispatcher, ZONE
from bridge.tvtime import TVTimeDispatcher

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('privacy_scan', ROOT/'tools/privacy_scan.py')
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


def test_integrations_require_explicit_enable_even_with_credentials():
    values = {'R1_HA_ORIGIN':'https://ha.example.invalid', 'R1_HA_TOKEN':'synthetic',
              'SIYUAN_INTERNAL_URL':'https://notes.example.invalid', 'SIYUAN_API_TOKEN':'synthetic',
              'MATON_AI_API_KEY':'synthetic', 'R1_CALENDAR_ID':'example-calendar',
              'R1_TVTIME_SCRIPT':'/opt/sarah/bin/tvtime'}
    with patch.dict(os.environ, values, clear=True):
        assert all(cls.from_env() is None for cls in (HADispatcher, SiYuanDispatcher, CalendarDispatcher, TVTimeDispatcher))
    assert ZONE == 'UTC'


def test_explicit_ha_and_notes_opt_in_construct_without_network():
    with patch.dict(os.environ, {'R1_ENABLE_HA':'1','R1_HA_ORIGIN':'https://ha.example.invalid', 'R1_HA_TOKEN':'synthetic'}, clear=True):
        assert isinstance(HADispatcher.from_env(), HADispatcher)
    with patch.dict(os.environ, {'R1_ENABLE_SIYUAN':'1','SIYUAN_INTERNAL_URL':'https://notes.example.invalid','SIYUAN_API_TOKEN':'synthetic'}, clear=True):
        assert isinstance(SiYuanDispatcher.from_env(), SiYuanDispatcher)


def test_calendar_requires_explicit_scope():
    import pytest
    with patch.dict(os.environ, {'R1_ENABLE_CALENDAR':'1','MATON_AI_API_KEY':'synthetic'}, clear=True):
        with pytest.raises(ValueError, match='calendar_id_required'):
            CalendarDispatcher.from_env()
    CalendarDispatcher('synthetic', 'example-calendar')


def test_privacy_scan_positive_and_negative_controls(tmp_path):
    (tmp_path/'PUBLICATION-MANIFEST.txt').write_text('PUBLICATION-MANIFEST.txt\nsource.py\n')
    sample = tmp_path/'source.py'
    sample.write_text('origin = "https://ha.example.invalid"\n')
    assert scanner.scan(tmp_path) == []
    sample.write_text('private origin = "http://' + '.'.join(('10','20','30','40')) + '"\n')
    assert any(kind == 'non-example-address' for _,_,kind in scanner.scan(tmp_path))
    sample.write_text('synthetic-private-canary')
    assert any(kind == 'private-literal' for _,_,kind in scanner.scan(tmp_path, ('synthetic-private-canary',)))
    sample.unlink()
    (tmp_path/'server.key').write_text('synthetic')
    assert any(kind == 'private-or-generated-file' for _,_,kind in scanner.scan(tmp_path))
    (tmp_path/'pointer').symlink_to(tmp_path/'server.key')
    assert any(kind == 'symlink' for _,_,kind in scanner.scan(tmp_path))


def test_project_mit_license_metadata():
    import json
    license_text = (ROOT / "LICENSE").read_text()
    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 serexe\n")
    assert "Permission is hereby granted, free of charge" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert json.loads((ROOT / "manifest.json").read_text())["license"] == "MIT"
    assert "LICENSE" in (ROOT / "PUBLICATION-MANIFEST.txt").read_text().splitlines()


def test_public_source_privacy_hygiene():
    assert scanner.scan(ROOT) == []
