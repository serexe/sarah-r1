# Explicit configuration

Optional `--backend acp` uses a dedicated, fail-closed Hermes composition; default remains `--backend codex`. Read [ACP deployment and limitations](ACP.md) before selecting it. Its fixed generic source/profile paths and pinned model differ from the legacy adapter; no actual configured profile is distributed.

`config/bridge.env.example` lists generic values; it is not loaded automatically. Export approved values or use a private service-manager environment file. Never source untrusted env files. Integration flags require literal `1`; credentials alone do not enable a backend. No credentials are shipped.

- `R1_CODEX_MODEL`: conversation model identifier; default retained from source. Account/provider must support it; no availability claim is made.
- `R1_WHISPER_MODELS`: local faster-whisper download/cache root, no automatic fetch.
- `R1_KOKORO_ROOT`: isolated TTS venv and ONNX/voice asset directory.
- `R1_TIMEZONE`: IANA timezone shared by calendar schemas, receipts and speech; default UTC. Set before process start. Invalid timezone fails startup/import. Restart your own bridge to change module-level schemas; never mix timezone values across components.
- HA: `R1_ENABLE_HA=1`, `R1_HA_ORIGIN`, `R1_HA_TOKEN`. Exact HTTP(S) origin only, no path/query/userinfo. Use HTTPS or a separately secured local network transport. **This backend permits any discovered HA service the token can invoke, including security-sensitive services, without repeated confirmation.** Narrow rights with a dedicated account/token and do not enable if this authorization model is unsuitable. The visible legacy confirmation UI is not an enforced HA approval policy.
- SiYuan: `R1_ENABLE_SIYUAN=1`, `SIYUAN_INTERNAL_URL` (or `SIYUAN_BASE_URL`), `SIYUAN_API_TOKEN`. Discovery/read/create/update/append/edit and exact childless-document deletion. Paths containing Private and root zArchive are excluded; that naming rule is not a comprehensive authorization system. Deletions have local rollback exports, which are sensitive.
- Calendar: `R1_ENABLE_CALENDAR=1`, `MATON_AI_API_KEY`, explicit `R1_CALENDAR_ID`, optional `R1_MATON_CONNECTION_ID`. Uses the public Maton Google Calendar gateway. Dispatcher checks configured calendar ownership. List/read/create/update/delete; no bulk or recurring-series edits. Empty configuration is not live authorization verification. Credentials may grant broader upstream access than this adapter uses.
- TV: `R1_ENABLE_TVTIME=1`, explicit absolute `R1_TVTIME_SCRIPT`. Runs administrator-selected Python script once with no model-supplied arguments. No implementation of a household-specific TV workflow is included; supply and audit your own. Exit zero proves local command acceptance only, not physical readiness. The subprocess is a privileged trust boundary for the service account, not a sandbox.

Optional backends passed directly to `make_app` are dependency injection for tests/embedding; the env enable gates apply to CLI discovery through `from_env`.

No built-in retention/deletion scheduler for bridge media, transcripts or rollback exports exists. Establish a private lifecycle policy and backups. Revoke a device using `Store.revoke(device_id)` from a trusted local administrative script; no unauthenticated admin endpoint exists. Re-provision intentionally rather than overwriting state.
