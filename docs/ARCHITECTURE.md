# Architecture and trust boundaries

Client → HTTPS bearer-authenticated bridge → local STT → Codex conversation → optional explicitly configured dispatchers → local TTS → authenticated media download.

API routes: `GET /v1/health`, `POST /v1/conversations`, `POST /v1/turns`, `GET /v1/requests/{request}`, `GET /v1/turns/{turn}`, `GET /v1/turns/{turn}/audio`, and turn `/cancel` and `/confirmation` POSTs. Health requires device authentication too. Audio upload requires `Content-Type: audio/wav`, `X-Conversation`, and `Idempotency-Key`.

SQLite stores devices as token hashes; conversations, turn transcript/detail and dispatch metadata are persisted. Restart marks unfinished turns uncertain, not replayable. Action claims are durable before dispatch; cancellation is not rollback. Model-generated success cannot override dispatcher receipts. Mixed mutation turns use server-owned receipts; pure read/conversation turns retain model prose. HA group success requires stable membership and all-member readback.

Runtime imports Hermes `agent.credential_pool.load_pool` and `agent.codex_headers.codex_cloudflare_headers` only when explicitly constructed at server startup. It is coupled to those internal APIs, not a generic Hermes HTTP endpoint. Tests bypass construction and provide synthetic pool/transport objects. Runtime uses only the fixed Codex backend origin; environment proxies and redirects are disabled. Model selection is configurable; account/model availability is not guaranteed.

Local speech model assets are not bundled or downloaded implicitly. Whisper defaults to `base`, CPU/int8, English. Kokoro defaults to `af_heart`, speed 1.05, `en-us`; an isolated subprocess is terminated/reaped on timeout/cancellation, and MP3 publication is atomic. Missing TTS yields text-only replies. Missing STT fails the turn.

The optional idle-power policy holds suspend for 3600 seconds after fresh physical input, with a hard 300-second active-operation cap. It has no network listener and never forces suspend/unlock. Installing a privileged helper changes power behavior and requires separate device review. Historical Wi-Fi repair/deployment programs and private observation tooling are intentionally not distributed.
