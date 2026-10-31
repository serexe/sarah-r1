# Android golden v44

User-authorized cumulative accepted source and public ARM64 phone APK. Golden means approved development baseline, not comprehensive device/runtime certification.

- APK: [sarah-v44-golden-arm64.apk](https://github.com/serexe/sarah-r1/releases/download/android-golden-v44/sarah-v44-golden-arm64.apk)
- Package: `com.serexe.sarah`
- Version code: **44**; version name: `0.1.44-golden`
- ABI: **arm64-v8a only**; five native libraries verified as AArch64.
- Size: **47332923 bytes**
- SHA-256: `a4e26bad8ce1351d1d8faafb75b12437e4c8554f9a1eead175d2f1dd8e7e3c4f`
- Signer SHA-256: `79c9b26baac4b0b60563430ebdf0023808cdf4e04b4d1d719fa950a7f3d5fa7d`
- Build: **signed local-review/debug build; debuggable; not a production-signed consumer release**. Same signer/package as preceding review APKs; metadata/signature upgrade-compatible. Physical upgrade of these rebuilt bytes remains pending.
- Annotated golden tag: `android-golden-v44`.
- Exact public build-source commit: `c860714267527376c592756462764142bc2e5dbf`.
- Exact source tree: `a76210fc23ba71799d6e6268e49a172dedfdc189`.
- Release: https://github.com/serexe/sarah-r1/releases/tag/android-golden-v44

## Included accepted work

Cumulative earlier Companion UI, waveform and response-speed work; retained warm local voice worker and opt-in first-sentence MP3 sequence with bounded acknowledgement/backpressure; bounded warm ACP conversation worker reuse with per-turn ownership and fail-closed uncertainty; uncertain-request reconciliation, retained submission diagnostics, explicit sanitized Send/Share diagnostics, and exact-approved local-recovery source.

This public bridge is the maintained sanitized variant, not a wholesale copy of a private deployment. Diagnostics routes retain the existing authentication guard. Publication does not deploy/restart a bridge, repair a binding, replay a request, alter pairing/history/ACK state, or install an APK.

## Public build differs from private v43 candidate

Earlier v43 behavior was manually accepted. That candidate embedded private one-off request/conversation approval hashes. Its APK is **not** published publicly. Public v44 retains the same Android source except version metadata; private recovery approval inputs are deliberately omitted. Thus exact-target recovery is disabled/fail-closed in this public build, not generalized to other requests. No private identifiers, target hashes, pairing, credentials or state are supplied. Do not reset/re-pair or resend an uncertain request to bypass a recovery guard.

The v44 APK was rebuilt once for public-safe inputs and a unique version code. Prior phone acceptance is not relabeled as testing these new bytes. Native libraries and assets (17 entries) and permissions are byte-identical/equal to v43. Signing and alignment verified.

## Actual checks and limits

- Final `assembleDebug` and focused JVM checks: **BUILD SUCCESSFUL**; **15 tests passed**, zero failures/errors/skips (exact recovery, sanitized diagnostics and existing resolved-cancellation handoff).
- Final public bridge composition: **18 synthetic tests passed**, covering warm ACP reuse/ownership/cancellation, sentence MP3 ordering/backpressure/acknowledgement, warm voice cleanup and authenticated diagnostics. No production model/tool traffic.
- `git diff --check`; APK package/version/ABI/ELF/signature/alignment/permissions/hash verification; private approval/signing-input byte scan; newly reachable source blobs and commit metadata privacy review. Heuristic privacy checks are not security certification.
- Existing stage benchmarks and user warm-response acceptance do not measure phone first-audible latency. No first-audible or comprehensive physical Stop/screen-off/wake/battery guarantee.
- **Pending:** physical update-install and runtime validation of this exact v44 APK; device layout/font/History, sentence playback/codec feel, Stop followed by the next question, successive offscreen wakes and battery behavior. No VM/emulator/device install or lifecycle operation occurred during release work.

Historical tags/releases remain unchanged. Original snapshot, licensing/dependency and upstream-notice limitations still apply.

## Future work baseline

Branch from current `main`; preserve the annotated golden tag and exact APK. **Android versionCode floor is 44**: future APKs must use a greater code. Main may add baseline/download documentation after the tag; this APK is tied to the exact source commit/tree above, not later docs. Do not copy private deployment/configuration/state into this repository or its release assets.
