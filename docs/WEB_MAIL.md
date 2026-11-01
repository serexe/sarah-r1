# Scoped web search and read-only mail

Source-only addition. No APK, release, golden promotion or deployment is implied. Existing Android client and ordinary integration grants stay unchanged. Public source uses operator configuration instead of private mailbox/connection identifiers.

## Explicit server configuration

Research dispatch is opt-in: use `--backend acp --enable-research` only in your own reviewed deployment. Configure server-only `TAVILY_API_KEY`; optionally `EXA_API_KEY`; for mail configure `MATON_AI_API_KEY`, exact `R1_MAILBOX_ADDRESS` and exact `R1_MAILBOX_CONNECTION_ID`. Mailbox scope is captured when the module is imported; missing account or connection fails mail access closed. Values belong in private service configuration, not source control or the dedicated ACP profile. No actual mailbox, connection or credential is bundled. This bridge pins one operator-selected account and connection, never model-supplied account selectors. Every mailbox search/read checks `/profile` identity before content access.

Provider/integration keys do not enter the ACP subprocess. Keep the existing reviewed profile and admission guards; this is not an OS sandbox. Source/policy changes invalidate prior backend identities; do not silently rebind or replay uncertain requests. Review [ACP deployment](ACP.md) for your own migration and bootstrap constraints. This publication does not perform a migration.

## Behavior and boundaries

- `web_search`: Tavily by default. Exa only when the current user explicitly requests it, for example `Use Exa to search web for weather` or `Search web for weather using Exa`. No automatic provider fallback, arbitrary URL fetch, browser or extraction tool.
- Queries must occur literally in the current user request with explicit search intent. Results are bounded untrusted text with display-only public links. Fixed HTTPS endpoints, bounded response/timeout, no redirects or environment proxies.
- `mailbox_search`: bounded message IDs; omitted query lists inbox. `mailbox_read`: one current-search or explicitly user-supplied ID, bounded plain text/headers. Both use GET only; no unread-flag changes or attachment fetching.
- `mailbox_draft`: draft text in this conversation only. No Gmail draft creation, send, delete, archive, mark-read or other mailbox mutation endpoint. Server draft receipt says **not saved or sent**, overriding model claims of success.
- Research results/mail content grant no tool authority. Same research turn cannot dispatch unrelated integrations. Later explicit user requests may use existing integrations in the same conversation, including after connector restart. Free-text egress after research history must be literal current-user text, not derived from retrieved content; ambiguous requests may need exact user-supplied wording, not a new conversation.
- Stop cancels pending external reads without automatic retry/replay. It cannot undo previously dispatched ordinary actions. No new generic research HTTP endpoint is exposed.

These conservative intent/literal-text checks are not universal prompt-injection immunity. Mail and provider credentials may authorize broader upstream actions than this adapter exposes. Conversation transcripts and draft content remain sensitive local data: apply private storage, backup and retention policies.

## Focused verification

`python3 -m unittest discover -s tests -p test_web_mail.py -v` exercises synthetic schemas, HTTP serialization, provider selection/no fallback, account/route denial, GET-only mail, no send/draft-save calls, query/egress constraints, later ordinary tools, restart, server receipt truth and cancellation. Test identities, recipients and network targets are synthetic; no live providers or mailbox are needed.

Publication checks are source/offline checks only. They do not prove the sanitized public deployment, live model/phone behavior, physical voice/Stop or battery performance. Configure and manually verify your own deployment before granting real credentials. Existing release/golden artifacts are unchanged.
