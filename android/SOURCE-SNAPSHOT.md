# Android source snapshot

This is the first Git-tracked export of an untracked Android development tree. It is not reconstructed development history, a release, a verified build, or proof of a tested APK's exact source.

## Publication scope

Production source, build declarations, JVM tests, one standalone instrumentation test, required dependency/model payloads, upstream notices and launcher images are included. Application package/version and signing configuration were retained. No application-code or build/signing behavior was changed for publication.

Excluded: Gradle/Kotlin/build caches and outputs; local signing directory and passwords; APKs; environment-specific installed-APK test harnesses; instrumentation certificate/key containers; raw PCM/MP3 fixtures; local reports, logs and runtime configuration. Excluded material remains private in the development tree.

The public README replaces obsolete local-only instructions and private absolute paths. Dependency notes distinguish source inventory from unverified historical test claims. Original launcher artwork had ancillary generation/provenance identifiers removed without changing decoded pixels. Runtime launcher resources are unchanged.

## Verification performed for publication

- Selected source files were hashed before, during and after copying; the selected file set and bytes were stable across the snapshot interval.
- Every staged Android file, its path and executable mode were inventoried and scanned. Text, image chunks, raw binary strings and nested AAR/JAR members were inspected without executing source or dependencies.
- Launcher artwork and all launcher-resource variants received visual privacy inspection.
- The sherpa-onnx AAR SHA-256 matched the upstream GitHub release asset digest. Model files, vocabulary and model README matched members of the pinned official model archive byte for byte. The Gradle wrapper JAR matched the official wrapper checksum.
- Third-party notices and public upstream attribution were preserved. Upstream binaries contain generic upstream CI build paths and library-internal identifiers; these are not private operator paths or device identities.

This is a focused disclosure check, not a guarantee against steganography, unknown private markers, encoded secrets or defects in third-party binaries. No application tests, emulator/phone checks, build, install or runtime safety validation were performed.

No tested APK/source linkage is asserted. The source version declaration alone does not prove which APK was tested, installed or approved.
