# Android golden v36

User-approved promotion of the exact v36 clean-layout APK. No rebuild, re-signing, internal version change, installation or runtime test occurred during promotion.

- APK: [sarah-v36-golden-arm64-x86_64.apk](https://github.com/serexe/sarah-r1/releases/download/android-golden-v36/sarah-v36-golden-arm64-x86_64.apk)
- Package: `com.serexe.sarah`
- Version code: **36**; version name: `0.1.36-clean-layout-review`
- ABI: **arm64-v8a + x86_64**
- Size: **83035970 bytes**
- SHA-256: `477b9a832d6270fcbcb6cc18d3ab8a335897d356e0573627ae3c09a2dcbdcadb`
- Signer SHA-256: `79c9b26baac4b0b60563430ebdf0023808cdf4e04b4d1d719fa950a7f3d5fa7d`
- Build: **signed local-review/debug build; debuggable; not a production-signed consumer release**.
- Annotated golden tag: `android-golden-v36`; public source commit: `08e08c7c09c6a3c9f2c6eeda6c12d414364467a6`.
- Exact approved local build-source commit: `9ea8bfd5a4163139288138b02445bddb8463a3db`. Private machine author/committer metadata was replaced with the public noreply identity before publication; all five cumulative commit trees/messages preserved. Original local review refs remain untouched. Final source Git tree is byte-identical: `d2ffac08a66611bcdfccbe0e22c4b793c476d176`. No production source changed during privacy sanitization.

## Scope and proof limits

Cumulative v32–v36 Companion UI, real playback-envelope waveform and clean bounded main/settings layout. Main transcript appears once in collapsed History; speaking displacement remains adaptive to finite canvas space.

Existing v36 build log records `BUILD SUCCESSFUL in 11s`; six focused ReplyEnvelope tests passed with zero failures/errors. Those are earlier build/unit checks, not a new full suite or physical-device proof. Publication privacy checks cover all newly published cumulative blobs/metadata, tracked text, the portrait image and APK ZIP manifest/Dex/resource strings. No concrete operator identifier/credential found after metadata sanitization; heuristic scanning is not exhaustive security or steganographic certification.

**Still pending:** real-device screen fit, increased-font behavior, History interaction, waveform/codec feel, Stop followed by the next question, physical screen-off successive wakes and battery behavior. Golden means approved baseline, not runtime-proven phone behavior. No device installation, service restart or deployment was performed.

Historical v31 APK-only source-provenance limitations remain unchanged. Old `serexe/sarah-android` archive, tags and releases remain untouched. Existing licensing/dependency caveats and upstream notices still apply.

## Future work baseline

Branch from current `main`; preserve this annotated tag and exact APK. Android versionCode floor is 36: future APKs must use a greater code. Main may add documentation commits after the tag; the APK is tied to the exact source tree above, not subsequent documentation. Release: https://github.com/serexe/sarah-r1/releases/tag/android-golden-v36
