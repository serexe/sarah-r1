# Android wake-word testing and customization

**Source-level review option, not a runtime setting or a fixed assistant identity.** SARAH remains the app name. Phone keeps “Hey Sarah”; the Lenovo v67 review source uses **“Nova” only for testing**. A later preferred word or phrase can replace it in a new build, subject to the bundled keyword model's tokenizer and real acoustic testing. Arbitrary spoken words are **not** guaranteed to work. This documentation does not change installed apps, publish an APK, or promote a golden release.

## Current review variants

| Variant | Spoken/display phrase | Exact native result alias | Keyword asset | Noise suppression |
| --- | --- | --- | --- | --- |
| `phoneDebug` (ARM64) | Hey Sarah | `HEY_SARAH` | `app/src/main/assets/kws/keywords.txt` | Off |
| `lenovoDebug` (ARMv7) | Nova (experimental) | `NOVA` | `app/src/lenovo/assets/kws/keywords.txt` | Lenovo-only trial, wake and command/follow-up recorders |

Lenovo noise suppression attaches to each `AudioRecord` session where Android offers an enabled `NoiseSuppressor`; unavailable or failed creation/enable falls back to the existing microphone path. `enabled=true` is not evidence of audible improvement or a working vendor DSP. Release follows the recorder owner. No AEC/AGC, global audio policy, phone suppression or audio upload is added.

## Testing the Lenovo candidate

On an approved, already-installed review build, open the app and **explicitly** enable persistent Nova listening, accepting microphone permission if prompted. Wait for “Wake listening” and speak a natural command such as “Nova, ask me a question.” Observe recognition, first-utterance behavior, reply and follow-up. Use **Stop Nova microphone** afterward. Do not infer detection from a readiness cue; it means recorder/model are armed, not that speech will be recognized. Do not collect or share household recordings or private transcripts in an issue.

The v67 offline checks passed focused Lenovo wake-phrase, suppression-lifecycle and rearm tests (17 cases), phone wake-phrase (1), and targeted follow-up tests (4). A synthetic host replay of the bundled model detected one “Nova” voice/speed and missed two slower speeds; synthetic results do not establish real-room reliability or false-positive rate. A broader selected Lenovo `SarahViewModelTest` run still had two pre-existing expectation failures (`duplicateTapWaitsForRecorderAndLostAdmissionReconcilesReadOnly` and `leaseReleaseThenWakeListeningPreservesUncertainRequestWithoutReplay`). Physical first-utterance misses remain unresolved; this source publication does not tune or fix them. No full-suite, physical acoustic or new release validation is claimed.

## Change the phrase in a future review build

1. Pick the target flavor. In `app/build.gradle.kts`, set that flavor's `WAKE_PHRASE` (visible UI wording) and `WAKE_RESULT_ALIAS` (exact, case-sensitive model result). Keep the other flavor unchanged unless intentionally updating it. App identity and name need not change.
2. Encode the spoken phrase using the **bundled** `app/src/main/assets/kws/bpe.model` SentencePiece tokenizer. Check that every resulting symbol exists in `app/src/main/assets/kws/tokens.txt`. Put its space-separated tokens and `@ALIAS` in that flavor's `kws/keywords.txt`; for example Lenovo's reviewed `▁NO V A @NOVA`. An alias is a result label, not phonetics; it must match `WAKE_RESULT_ALIAS` exactly. Do not assume letters or English spelling are tokenizer symbols, or that changing only the UI string changes detection.
3. Update `WakePhraseTest` for both flavors, run the selected flavor's JVM phrase/lifecycle tests and build its explicit APK target (`:app:assembleLenovoDebug` or `:app:assemblePhoneDebug`) with suitable SDK/signing setup. Check generated flavor `BuildConfig`, merged keyword asset, package/version/ABI/signature, and test results. Plan versionCode upgrades before switching installed variants; do not downgrade or clear pairing to test a keyword.
4. Test with consent on the target device in realistic noise and speaking styles. Include first utterance, repeated attempts and non-keyword speech; assess misses and false wakes before considering the phrase usable. Model/token compatibility is necessary but insufficient. Keep audio and private diagnostics out of public GitHub.

See [model provenance](KWS-DEPENDENCIES.md) and [Android build/consent limits](README.md). A new keyword needs a rebuilt, separately reviewed APK; this is not an arbitrary runtime UI customization or a universal accuracy promise.
