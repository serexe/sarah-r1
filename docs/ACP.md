# Optional scoped Hermes ACP backend

`--backend codex` remains default. `--backend acp` explicitly selects the existing Hermes ACP stdio implementation through a dedicated Sarah composition. No automatic fallback, reconnect replay or migration of earlier conversations occurs. This source port is not a device release or proof of this public deployment.

## Fixed, generic deployment contract

- Install compatible Hermes source at `/opt/hermes-agent`. The Python interpreter running the bridge must also have Hermes/ACP dependencies available: the child uses that exact `sys.executable`, never a shell or the stock broad `hermes acp` CLI.
- Provision a separate private directory `/var/lib/sarah/acp` owned by the bridge service account, mode 0700, plus its `workspace` subdirectory. These are generic deployment paths, not supplied runtime state.
- Deliberately copy the credential-free source template `bridge/sarah-acp.yaml` to that directory as `config.yaml`, mode 0600. Provision `SOUL.md`, mode 0600, with exactly the bytes of `bridge.acp_launcher.REVIEWED_SOUL`. Do not substitute a persona. Missing, altered or symlinked bootstrap files fail closed; `.env` and `AGENTS.md` are rejected. The launcher never repairs bootstrap content.
- Authorize the supported `openai-codex` resolver for your own bridge service account separately. No credentials are bundled or passed from the bridge environment. The provider resolver may use its supported shared OAuth pool and update authentication bookkeeping; the dedicated directory is **not** an OAuth or OS sandbox.
- Pass `--backend acp` to your own reviewed bridge invocation. For the legacy Codex path, `--hermes-source` retains its existing meaning; ACP uses the fixed `/opt/hermes-agent` contract. Start a **new conversation** after selecting another backend or changing its policy/source identity.

The composition pins `openai-codex`, its Codex endpoint and `gpt-6.1-sol`, with no fallback model/provider. Your provider/account must support that model. `R1_CODEX_MODEL` currently affects only the legacy Codex backend, not ACP. Changing the ACP model requires an explicit reviewed source/template change, which invalidates existing bindings. Hermes internal API compatibility is not version-pinned by this publication.

## Permissions and persistence

The exact existing 18 tool schemas are preserved: `calendar_create`, `calendar_delete`, `calendar_list`, `calendar_read`, `calendar_update`, `ha_call_service`, `ha_get_state`, `ha_list_entities`, `ha_list_services`, `sy_append`, `sy_create`, `sy_delete`, `sy_edit`, `sy_list_notebooks`, `sy_read`, `sy_search`, `sy_update`, `tvtime_on`.

Schemas are not live authorization: existing public integration enable flags and server dispatchers still control actual access. Credentials alone do not opt in. No generic shell, filesystem, browser, administrative tools, client execution, MCP servers, blanket permission bypass or additional default tools are granted. Tool extension requires deliberate source/schema/dispatcher authorization, not merely enabling an inherited Hermes toolset. Permission requests are denied. Public calendar timezone is the one explicit nonsecret configuration forwarded to the child, preserving schema agreement.

Binding is durable per device/conversation plus backend/policy/source identity. Followups load the exact existing ACP session; missing, changed, inflight or uncertain sessions never become replacement sessions. Stop cancels and reaps owned child work, marks uncertain binding where appropriate and requires a fresh conversation. It cannot undo previously dispatched actions. Existing SQLite mutation slots and server-owned action receipts remain authoritative; model text or completion events cannot manufacture successful actions.

Context files, soul identity, memory, user profile loading and skill creation nudges are disabled. This is not the main Hermes profile's memory/skills/context experience. It reuses Hermes' conversation/session engine with a narrowly composed capability set. The inert sentinel exists because installed Hermes can seed SOUL.md even when context loading is disabled.

## Explicit legacy migration and current-clock context

Legacy completed bridge dialogue without an ACP binding is refused before agent connection with `acp_backend_requires_new_conversation`. The device receives a specific migration-required message; uncertain upstream failures retain the generic unknown-outcome warning. No request automatically migrates, retries or creates a replacement conversation.

An operator may review `ACPRuntime.legacy_migration_plan(device=..., conversation=...)` and explicitly call `migrate_legacy` with that exact accepted digest and the dedicated profile's `SessionDB`. This imports literal completed user/assistant dialogue only, never failed requests or pending prompts. Changed snapshots, existing bindings, ambiguous outcomes and partial imports fail closed. Back up and review the exact deployment first; this is not a generic rebind path for changed backend identities.

Each new model turn receives one UTC clock sample and its America/Chicago conversion, including the applicable daylight/standard offset. This API-facing context does not alter literal persisted user messages or the cached system prompt. It is a trusted host turn-start snapshot, not independent clock synchronization or a continuously updated playback-time clock. Compatible Hermes persistence APIs must support the literal-message override. Installed session restoration may reallocate internal message row IDs while preserving message content and tool fields; storage-ID stability is not promised.

## Verification limits

Focused synthetic tests cover durable followups/device isolation, denied permissions/client execution, exact dispatch binding/schema policy, transport loss/Stop without replay, inactive admission, and exact bootstrap bytes. An optional installed-composition fixture runs only when `/opt/hermes-agent` exists; it is not needed for ordinary offline tests. Source hashes prevent silently reusing sessions after changes.

Earlier separately accepted private activation proved actual provider/STT/TTS and a harmless lookup, not the sanitized public deployment. No new provider prompts, integration calls, native build, golden30 run, device acceptance, service changes or configuration activation were performed for publication. Native client, existing public integration guards and receipt logic remain unchanged. Configure and test your own deployment before enabling real action credentials.
