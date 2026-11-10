# S.A.R.A.H Android

Kotlin/Compose Android voice client for an HTTPS S.A.R.A.H bridge. This shared source descends from **[Android golden v50](../SARAH_BASELINE.md)** reconstructed development source. Golden v50 tag and approved APK remain unchanged; **exact v50 source-to-APK reproducibility is unproven**; see [v50 provenance and proof limits](GOLDEN50-SOURCE.md). The repository's existing `app/` remains the separate Ubuntu Touch client.

## Included source

- Manual voice capture, HTTPS bridge communication, reply playback and local pairing storage.
- Android assistant-role entry points and an explicitly enabled foreground-microphone service for local wake detection (“Hey Sarah” on phone; experimental “Nova” on Lenovo).
- Production source, JVM unit-test source, one standalone screenshot-policy instrumentation test, launcher artwork, Gradle wrapper, pinned sherpa-onnx AAR, model files and upstream notices.

Current shared source has two **debug/local-review** variants. Both retain `com.serexe.sarah`, minSdk 26, targetSdk 35 and Keystore-backed pairing; they are alternative upgrades, not side-by-side installations. Phone: `phoneDebug`, ARM64 (`arm64-v8a`), `0.1.53-phone-review` / versionCode 53, retaining “Hey Sarah”, `HEY_SARAH` and threshold 0.25. Lenovo: `lenovoDebug`, ARMv7 (`armeabi-v7a`), `0.1.67-lenovo-nova-wake-review` / versionCode 67, using experimental “Nova”, exact `NOVA` result and threshold 0.24. Lenovo v66 introduced a per-recorder noise-suppression trial for wake listening and command/follow-up capture; v67 keeps it and changes only the Lenovo wake phrase/model keyword. The phone variant does not enable that suppression trial. These source variants are review candidates, not golden releases or published APKs. Installing the lower-version phone build over Lenovo 67 would be a downgrade; do not switch variants without planning a higher version. Earlier v50 includes local schedules, phone media and timer countdown/Cancel/Stop UI; compatible backend routes are not part of this Android source. [Wake-word testing and customization](WAKE-WORD-TESTING.md) explains what can be changed and what still needs physical validation.

## Privacy and setup

Provide your own HTTPS bridge origin and separate revocable device token at runtime. Example origin: `https://companion.example.invalid`. Never put provider credentials, tokens, private CA keys or personal configuration into source control.

The source implements local Android Keystore-backed storage and disables Android backups. Clearing local pairing or conversation does not delete server history or undo server actions. Reply playback uses temporary app-cache storage; process death may leave cache data until eviction. Do not treat this publication or static inspection as a runtime security audit.

Assistant-role invocation alone does not start microphone capture. Persistent local wake listening requires a separate visible opt-in and foreground microphone notification; it can continue after closing the activity until explicitly stopped. Unlocked wake can record and submit a command to the paired bridge; locked wake is notification-only. Review the source and platform permissions before enabling it. No real pairing, transcript, recording or device configuration is included here.

## Build prerequisites and limits

Use JDK 17 and Android SDK platform/build-tools 35. Configure `ANDROID_HOME` for your own SDK installation. Gradle wrapper and declared dependencies require network access on an uncached machine.

From this directory, build and run focused JVM checks separately:

```sh
./gradlew --no-daemon :app:testPhoneDebugUnitTest --tests 'com.serexe.sarah.LegacyWakeEligibilityTest' --tests 'com.serexe.sarah.WakePhraseTest' :app:testLenovoDebugUnitTest --tests 'com.serexe.sarah.LegacyWakeEligibilityTest' --tests 'com.serexe.sarah.WakePhraseTest' --tests 'com.serexe.sarah.WakeCaptureDiagnosticsTest' --tests 'com.serexe.sarah.WakeReadinessBoundaryTest' --tests 'com.serexe.sarah.ServiceCommandRearmTest' --tests 'com.serexe.sarah.ListenerModelWarmupTest' --tests 'com.serexe.sarah.SarahViewModelTest'
./gradlew --no-daemon :app:assemblePhoneDebug :app:assembleLenovoDebug
# Outputs: app/build/outputs/apk/phone/debug/app-phone-debug.apk
#          app/build/outputs/apk/lenovo/debug/app-lenovo-debug.apk
```

Keep these APKs separate. The selected ABI must have five native libraries in the final APK: `libandroidx.graphics.path.so`, `libonnxruntime.so`, `libsherpa-onnx-c-api.so`, `libsherpa-onnx-cxx-api.so` and `libsherpa-onnx-jni.so`. Check final APK contents, `aapt` metadata and `apksigner` before using any artifact. Do not use Gradle's aggregate `assembleDebug` as a substitute for explicit lane selection.

API 27/28 lacks `ROLE_ASSISTANT`; only there, the Lenovo-derived compatibility rule allows the persistent foreground microphone after visible user consent. API 29+ still requires the assistant role. Existing microphone permission, unlocked/privacy/audio-focus gates, notification and explicit Stop remain. No automatic always-listening, pairing reset, token change or bridge mutation is introduced. The Lenovo listener drains nonempty reads without a 20 ms post-read sleep; idle reads retain the backoff. App-private diagnostics retain bounded aggregate counters and timestamps, not audio or recognition text. `Wake listening` is emitted only after model arm and confirmed `AudioRecord` recording, with live owner/Stop/notification/deadline gates. This readiness cue does **not** prove acoustic detection. The v61 visible-wake handoff passes the service's exact live capability to the resumed Activity, allowing capture, spoken reply, and return to listening in the same foreground service only after native command cleanup ACK. Manual capture remains blocked while the service owns listening; Stop and original consent/deadline still apply. The v62 Lenovo rearm path preloads a model-only engine during command work after previous listener cleanup ACK, without opening microphone or taking capture lease. Next listener takes sole model ownership, arms a fresh stream and recorder, then reports readiness only after recording. Private bounded setup-phase durations can support future comparison; model-load time was not measured as v61's cause.

The v61 visible foreground conversation was physically accepted; v62 rearm was reported “much much quicker.” No v62 millisecond measurement, quantified comparison or repeatability claim is made here. Prior focused v61 tests passed (15/15); prior focused v62 tests passed (18/18) and Lenovo assembly succeeded offline. Exact installed local v62 review APK SHA-256: `34667632b3100e26d3d83c1b20c662283c6a426ee62cb27a46b58d476eb2c87d`; its installed bytes, signature/ABI/version and retained encrypted state were verified before this source publication, microphone left off. That earlier v62 source-publication commit performed no rebuild or device run. Real Lenovo “Sarah” recognition remains imperfect and screen-off reliability unproven. Phone physical behavior on this source is unverified. No APK or private diagnostic/voice fixture is included in this review commit; source-to-exact-v62-binary reproducibility is not established by the commit.

Lenovo v63 adds an A2 response screen with the existing playback-driven waveform, centered scrollable answer and compact status/Stop/Tap-to-talk/History footer. `speaking.detail` supplies the actual assistant answer before sentence-chunk audio; text reveals approximately as real playback position advances (18 characters/second across chunks), **not** word-aligned. Polling pauses the reveal; Stop/error preserves available text. New capture, local history clear, new conversation and pairing reset clear the live caption. Phone screen and recognition settings are unchanged. The focused caption JVM check passed (1/1), and Lenovo offline assembly succeeded. A broader 57-test ViewModel run had two failures, reproduced in isolation: `duplicateTapWaitsForRecorderAndLostAdmissionReconcilesReadOnly` and `leaseReleaseThenWakeListeningPreservesUncertainRequestWithoutReplay`; do not treat that run as green. The local v63 review APK was installed with matching bytes and encrypted-state metadata retained, microphone off; no APK is published here. Physical voice/visual review, exact source-to-APK reproducibility and screen-off reliability remain unproven.

Historical v50 evidence remains scoped to the immutable golden tag. Its Kotlin compilation and focused JVM cases passed; a broader three-class run had 65 tests and two older `SarahViewModelTest` expectation failures. This new branch is neither v50 promotion nor exact reproduction of its APK.

The original `localReview` debug-signing configuration is unchanged. Its `.local-review/review.jks` and `.local-review/signing-pass` inputs are deliberately absent from source control. Debug APK assembly/install requires your own separately authorized private signing setup. Published v50 uses the existing compatible signer; no new key was generated. Do not commit signing materials. Release signing is not configured here.

Exact-approved local recovery uses optional `.local-review/exact-local-recovery.properties` build inputs. Missing input disables it/fails closed. No private one-off target hashes or signing inputs are supplied with this source. Do not broaden the target, clear state or replay an uncertain request to bypass this boundary.

Environment-specific installed-APK instrumentation harnesses, their certificate/key containers and raw audio fixtures were excluded rather than published. The retained screenshot-policy instrumentation test is not the complete private instrumentation suite. Do not infer full device-test reproducibility or prior pass results from this snapshot.

## Snapshot and dependency provenance

See [SOURCE-SNAPSHOT.md](SOURCE-SNAPSHOT.md), [DEPENDENCIES.md](DEPENDENCIES.md) and [KWS-DEPENDENCIES.md](KWS-DEPENDENCIES.md). Upstream dependency/license authorship is preserved; it is not personal configuration belonging to the app operator.

## Licensing ambiguity retained

The repository already contains an [MIT license](../LICENSE). The pre-publication Android dependency inventory separately recorded that Android source had no explicit distribution-license declaration. This snapshot does not silently resolve that pre-existing ambiguity or make a new Android-specific license grant. The owner should clarify Android licensing before downstream redistribution. Third-party license terms and attribution remain unchanged; the dependency inventory is not a transitive license clearance.
