# S.A.R.A.H Android

Kotlin/Compose Android voice client for an HTTPS S.A.R.A.H bridge. This directory is a **sanitized source snapshot**, not a new APK release or a claim that these exact source bytes produced a previously tested APK. The repository's existing `app/` remains the separate Ubuntu Touch client.

## Included source

- Manual voice capture, HTTPS bridge communication, reply playback and local pairing storage.
- Android assistant-role entry points and an explicitly enabled foreground-microphone service for local “Hey Sarah” detection.
- Production source, JVM unit-test source, one standalone screenshot-policy instrumentation test, launcher artwork, Gradle wrapper, pinned sherpa-onnx AAR, model files and upstream notices.

The declared source version is `0.1.29-persistent-wake-review` (version code `30`), package `com.serexe.sarah`. These are source declarations, not installed-device or tested-APK evidence. Physical-phone black-screen behavior, battery use and wake reliability are not established by publication.

## Privacy and setup

Provide your own HTTPS bridge origin and separate revocable device token at runtime. Example origin: `https://companion.example.invalid`. Never put provider credentials, tokens, private CA keys or personal configuration into source control.

The source implements local Android Keystore-backed storage and disables Android backups. Clearing local pairing or conversation does not delete server history or undo server actions. Reply playback uses temporary app-cache storage; process death may leave cache data until eviction. Do not treat this publication or static inspection as a runtime security audit.

Assistant-role invocation alone does not start microphone capture. Persistent local wake listening requires a separate visible opt-in and foreground microphone notification; it can continue after closing the activity until explicitly stopped. Unlocked wake can record and submit a command to the paired bridge; locked wake is notification-only. Review the source and platform permissions before enabling it. No real pairing, transcript, recording or device configuration is included here.

## Build prerequisites and limits

Use JDK 17 and Android SDK platform/build-tools 35. Configure `ANDROID_HOME` for your own SDK installation. Gradle wrapper and declared dependencies require network access on an uncached machine.

From this directory, the ordinary source checks are:

```sh
./gradlew --no-daemon :app:testDebugUnitTest :app:lintDebug
```

These commands were **not run as part of this publication**. No rebuild, device install or service restart was performed.

The original `localReview` debug-signing configuration is unchanged. Its `.local-review/review.jks` and `.local-review/signing-pass` inputs are deliberately absent. Debug APK assembly/install therefore requires your own separately authorized private signing setup. Existing keys were not copied, read or regenerated. Do not commit signing materials. Release signing is not configured here.

Environment-specific installed-APK instrumentation harnesses, their certificate/key containers and raw audio fixtures were excluded rather than published. The retained screenshot-policy instrumentation test is not the complete private instrumentation suite. Do not infer full device-test reproducibility or prior pass results from this snapshot.

## Snapshot and dependency provenance

See [SOURCE-SNAPSHOT.md](SOURCE-SNAPSHOT.md), [DEPENDENCIES.md](DEPENDENCIES.md) and [KWS-DEPENDENCIES.md](KWS-DEPENDENCIES.md). Upstream dependency/license authorship is preserved; it is not personal configuration belonging to the app operator.

## Licensing ambiguity retained

The repository already contains an [MIT license](../LICENSE). The pre-publication Android dependency inventory separately recorded that Android source had no explicit distribution-license declaration. This snapshot does not silently resolve that pre-existing ambiguity or make a new Android-specific license grant. The owner should clarify Android licensing before downstream redistribution. Third-party license terms and attribution remain unchanged; the dependency inventory is not a transitive license clearance.
