# Build and setup

## Native client

Requires Qt 5.15 development packages for Core, Gui, Qml, Quick, Multimedia and Network, a C++17 compiler, CMake 3.16+, and Lomiri.Components 1.3 at runtime. Ubuntu Touch ARM64 framework is `ubuntu-touch-24.04-1.x` as specified by `clickable.yaml` and `manifest.json`.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
cmake --install build --prefix "$PWD/package"
```

Use an appropriate Ubuntu Touch ARM64 SDK/Clickable 8.10+ environment for a device package; a normal host build is not a device-compatible package. `clickable build` is the conventional SDK build entry point. No package upload or device installation is automatic. Metadata still uses the generic local package namespace `hermes-touch-voice.local`; choose a publisher-controlled namespace and maintainer contact before publishing. Keep C++ application identity, QML applicationName, package metadata, confinement and private-data paths consistent when changing it. Manifest version 0.2.6 is retained source metadata, not proof of a public release. CMake's 0.1.0 project version is likewise historical.

Optional native probes are retained as C++ source. They require Qt test/runtime libraries, local fixtures and isolated HOME. Historical shell harnesses depended on a private SDK/device layout and are deliberately omitted rather than presented as portable scripts. Native probes are not automatically exercised by pytest.

## Bridge

Use a dedicated unprivileged account and private directory; do not run a public listener as root. Python dependencies are in `requirements.txt`. `requirements-dev.txt` adds pytest. Supply an independently installed, compatible Hermes source tree and server-side authorized Codex pool. This repository does not include Hermes or its credentials. Verify internal API compatibility before enabling runtime; no tested Hermes release constraint is available.

Obtain Whisper model assets explicitly into `R1_WHISPER_MODELS` (default `.build/whisper-models`); the runtime uses `local_files_only=True`. Obtain independently licensed Kokoro ONNX/voice assets, install `kokoro-onnx`, `onnxruntime`, `numpy`, `soundfile` in `R1_KOKORO_ROOT/venv`, and put `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `R1_KOKORO_ROOT` (default `.build/kokoro-audition`). This optional TTS environment is invoked using its Python with `-I`; OS `ffmpeg` with libmp3lame is needed. Model/dependency versions and redistribution rights require separate validation; no assets are bundled.

Provision locally (creates credentials: never commit or share output files):

```sh
umask 077
python -m bridge.prepare --state .state --origin https://companion.example.invalid:8787 --device example-device
```

Replace that reserved origin with your own hostname. Generate/provision a TLS certificate and private key outside source control whose SAN matches that hostname. For a private CA, put the CA certificate (not private key) into the app's private data directory as `server-ca.pem`. Normal hostname and peer verification remain enabled. Transfer only the generated device settings securely into the app private data directory as `settings.json`, or enter origin/device token in the setup UI. Keep file mode 0600 and directory mode 0700. Never supply Codex or HA credentials to the app.

```sh
python -m bridge.server --db .state/state.db --cert .state/server-ca.pem --key .state/server.key --hermes-source /opt/hermes --bind 127.0.0.1 --port 8787
```

Those are explicit generic paths. The server requires real local TLS and Hermes inputs; this command was not run against accounts/services during preparation. Loopback is the default; expose to devices only through an authenticated, appropriately firewalled TLS path. See configuration/security before enabling integrations. No systemd units are included because inherited ones were deployment-specific; use your service manager with private environment files, explicit paths, restrictive umask, no unnecessary privilege and a single bridge process.

## Optional power helper

See `power/README.md`. No helper service is installed automatically.
