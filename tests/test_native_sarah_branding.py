"""Native-only display branding; package/storage/security identities stay fixed."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_native_header_and_retained_history_presentation():
    qml = (ROOT / 'app/Main.qml').read_text()
    assert 'id: title; text: "S.A.R.A.H"' in qml
    # Display old persisted speaker headings without rewriting conversation storage.
    assert 'voice.transcript.replace(/(^|\\n\\n)HERMES\\n/g, "$1S.A.R.A.H\\n")' in qml
    assert 'Never enter Hermes, Codex, or Home Assistant credentials.' in qml
    assert 'applicationName: "hermes-touch-voice.local"' in qml


def test_new_assistant_speaker():
    cpp = (ROOT / 'app/Voice.cpp').read_text()
    assert 'm_transcript+="S.A.R.A.H\\n"+d+' in cpp
    assert 'm_transcript+="HERMES\\n"' not in cpp


def test_launcher_brand_and_unchanged_package_identity():
    desktop = (ROOT / 'app/voice.desktop').read_text()
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    assert 'Name=S.A.R.A.H\n' in desktop
    assert manifest['title'] == 'S.A.R.A.H'
    assert manifest['description'] == 'S.A.R.A.H Codex voice companion — local speech with opt-in integrations'
    assert manifest['name'] == 'hermes-touch-voice.local'
    assert manifest['hooks'] == {'voice': {'apparmor': 'voice.apparmor', 'desktop': 'voice.desktop'}}
    assert manifest['architecture'] == 'arm64'
    assert 'Exec=hermes-touch-voice' in desktop
    identity = (ROOT / 'app/AppIdentity.h').read_text()
    assert 'hermes-touch-voice.local' in identity
