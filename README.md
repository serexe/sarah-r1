# S.A.R.A.H

### A small voice companion for an R1 running Ubuntu Touch.

Tap to talk, hear a reply, and keep the conversation on screen. S.A.R.A.H pairs a native Qt/QML client with a self-hosted Python bridge for local speech processing, Codex conversation, and optional tools for your home, notes, and calendar.

By **serexe**. **Ubuntu Touch, not Android.** This is experimental source for people comfortable building and configuring their own setup, not a ready-to-install consumer assistant.

<p align="center">
  <img src="assets/sarah-r1-native-redacted.png" width="320" alt="Actual S.A.R.A.H native app on an R1: Connected · Armed status, New conversation control, and orange Tap to talk button. Conversation area visibly redacted." />
</p>
<p align="center"><sub>Actual R1 screenshot from an earlier development build. System bar cropped; conversation visibly redacted for privacy. Not a mockup or proof that this public source candidate has been installed.</sub></p>

[Get started](docs/SETUP.md) · [Configuration](docs/CONFIGURATION.md) · [Architecture](docs/ARCHITECTURE.md) · [Security](SECURITY.md) · [Verification](docs/VERIFICATION.md)

## What does S.A.R.A.H mean?

**Self Actuated Residential Automated Habitat** — a nod to SARAH, the smart house from the TV series *Eureka*. This S.A.R.A.H lives on an R1 rather than in a house.

## Why this exists

Sometimes a dedicated button and a short spoken answer are enough. This project explores that idea with a small native interface: one large talk button, a visible conversation, and a bridge you run yourself.

The device is the interface, not the credential vault. Speech models and integration credentials live on your bridge host. The app stores its bridge connection settings, a revocable device token, conversation/turn identifiers, and the local transcript in private app storage. Protect that device data as well as bridge-side transcripts, audio, and credentials.

## What is here today

These are implemented source capabilities. Integrations need your own configuration; they are not connected out of the box.

| Capability | Current behavior | What you provide |
| --- | --- | --- |
| Native voice interface | Qt 5/QML UI, connection and turn status, scrollable transcript, new conversation, cancellation, and stoppable reply playback | Compatible Ubuntu Touch device, native build, microphone/audio support |
| Tap-to-record | Explicit recording, capped at 30 seconds; cancel discards capture | A working device microphone; no always-listening mode |
| Speech recognition | Local faster-whisper on the bridge; default English, CPU/int8 | Python dependencies and separately obtained Whisper model files |
| Conversation | Server-side Codex adapter through Hermes credential-pool internals | A compatible, separately installed Hermes source tree and authorized Codex pool |
| Spoken replies | Optional local Kokoro synthesis and FFmpeg encoding; text-only replies if TTS is unavailable | Separate TTS environment, ONNX/voice assets, and FFmpeg |
| Home Assistant | Entity/service discovery, state reads, and discovered service calls; outcome readback where supported, including group-member checks for lights | Explicit enable flag, your HA origin, and a suitably scoped token |
| SiYuan notes | Discovery, reading, creating, editing, appending, and deleting individual childless documents; local rollback exports for deletion | Explicit enable flag, your SiYuan endpoint and API token |
| Google Calendar | List/read/create/update/delete individual events through the Maton gateway; configured-calendar ownership checks | Explicit enable flag, Maton authorization, explicit calendar ID, and timezone |
| Optional TV hook | One administrator-selected Python script, with no model-supplied command arguments | Your own audited implementation; no TV-control workflow is bundled |
| Optional idle-power helper | Bounded suspend holds from validated native input/operation events | Separate privileged Ubuntu Touch helper setup and device-specific review |

All integration flags are off by default. See [configuration](docs/CONFIGURATION.md) for exact variables, limits, and permissions.

**Important:** enabling Home Assistant authorizes discovered services available to its token, including potentially sensitive ones, without repeated confirmation. The retained confirmation screen is **not** a mandatory approval policy. Do not enable it unless that trust model suits your setup.

## How it fits together

```text
R1 · Ubuntu Touch
  Native Qt/QML app
  microphone → bounded recording
          │ HTTPS + revocable device token
          ▼
Your bridge host · Python / aiohttp / SQLite
  local Whisper → Codex conversation → optional tool dispatch
                         │
                         ├─ Home Assistant
                         ├─ SiYuan
                         ├─ Google Calendar via Maton
                         └─ Your optional TV script
  text reply + optional local Kokoro speech
          │ authenticated reply/audio download
          ▼
R1 · transcript + playback
```

**Self-hosted does not mean fully offline.** Speech processing can run locally on the bridge. Conversation uses the remote Codex backend; calendar access uses Maton. Enabled tools may send relevant conversation or tool data to their configured services.

### Connection and action handling

- TLS hostname/peer validation and bearer authentication protect the app-to-bridge connection. Upstream provider and integration credentials stay server-side.
- Durable request IDs and SQLite action claims support reconnect reconciliation. Reconnecting does not automatically resend a recording.
- Suspending the app discards pending capture and stops audio. This is not a background listening assistant.
- Interrupted work is marked uncertain rather than automatically replayed. Action receipts take precedence over model-written success claims.
- One mutation slot is shared across tools per turn. Cancellation does not undo an action already dispatched; there is no distributed exactly-once guarantee.

Read [architecture](docs/ARCHITECTURE.md) and [security](SECURITY.md) before connecting real accounts. Transcripts, audio, and rollback exports need a private retention policy; no automatic cleanup scheduler is included.

## Try the source

### 1. Run the offline Python checks

Requires Python 3.11+. Dependency installation needs access to package repositories; the tests use synthetic providers and loopback fixtures, not your live accounts.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider tests
```

Tests do not download speech models or establish device compatibility. Native C++ probes are separate and are not run by pytest. See the [verification record](docs/VERIFICATION.md) for the checked candidate and remaining gaps.

### 2. Build the native client

Follow [Build and setup → Native client](docs/SETUP.md#native-client). The source targets Qt 5.15, Lomiri, ARM64, and the `ubuntu-touch-24.04-1.x` framework. Device packaging requires an appropriate Ubuntu Touch SDK/Clickable environment; a host build alone is not an R1 package.

There is no bundled device binary or automatic installation. The retained package namespace is local metadata, not a public-store identity.

### 3. Configure your bridge

Follow [Build and setup → Bridge](docs/SETUP.md#bridge) for dependencies, model assets, local provisioning, TLS, and server startup. Use [the environment example](config/bridge.env.example) alongside [configuration](docs/CONFIGURATION.md); the example is not loaded automatically.

Start with voice conversation only. Enable tools individually after reviewing their permissions. In the app, enter your HTTPS bridge origin and revocable device token, **never** Hermes, Codex, or Home Assistant credentials.

## Status and limits

This repository is a sanitized **source preparation candidate**, not a published or device-verified release. Earlier private development established a native R1 UI and local package delivery; that does not certify this sanitized source, its integrations, or other devices.

- No credentials, recordings, readable conversation history, model assets, generated binaries, or deployment-specific service units are supplied. The sole reviewed image is an intentional exception: a privacy-redacted historical development screenshot, not evidence of a sanitized-source device installation.
- The Codex adapter depends on internal Hermes APIs. A tested Hermes release/revision constraint has not been established; compatibility needs checking.
- Manifest `0.2.6` is retained development metadata, not a public release number. CMake still carries historical `0.1.0` metadata.
- Fresh SDK packaging, native probes, device acceptance, publisher metadata, and third-party redistribution review remain release work. Physical battery/suspend behavior is not verified for this candidate.
- SiYuan naming exclusions are not a complete authorization system. Calendar bulk/recurring-series editing is not supported. TV script acceptance is not proof that a television is ready.
- Privacy scanning and offline tests reduce risk; they are not security certification or proof that every identifying detail has been removed.

## Possible next experiments

Ideas only: **not implemented as the features described here, not commitments, and no timeline.**

- A documented, repeatable public ARM64 packaging and device-validation workflow.
- A backend adapter boundary that does not rely on Hermes internal credential-pool APIs.
- Explicit per-tool permissions and consistently enforced approval policies.
- Built-in retention controls for transcripts, audio, and rollback exports.
- A reviewed first-run setup flow and clearer compatibility guidance for other Ubuntu Touch hardware.

No wake word, always-on microphone, or fully offline conversation backend is included in the current source.

## License

Original project code is **MIT licensed**, copyright © 2026 **serexe**. See [LICENSE](LICENSE), [license scope](LICENSE-STATUS.md), and [third-party notices](THIRD-PARTY-NOTICES.md).

Dependencies, model weights, voices, and other third-party assets retain their own licenses and terms. They are not bundled or relicensed by this project. Source availability is not approval to redistribute a device image, model package, or third-party binary.
