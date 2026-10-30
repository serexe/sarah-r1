# Direct dependency record (not a license clearance)

Recorded from local Gradle declarations; versions/claims below require upstream license and transitive review before redistribution. Screenshot regression adds Android instrumentation-test-only dependencies.

| Use | Dependency | Declared version | Preliminary upstream license family |
|---|---|---|---|
| Build | Android Gradle plugin | 8.9.2 | Apache-2.0; confirm components |
| Build | Kotlin Android + Compose plugin | 2.0.21 | Apache-2.0; confirm components |
| Runtime | Compose BOM | 2025.04.01 | AndroidX Apache-2.0 |
| Runtime | activity-compose | 1.10.1 | AndroidX Apache-2.0 |
| Runtime | compose ui / material3 / foundation | BOM-managed | AndroidX Apache-2.0 |
| Runtime | lifecycle-viewmodel-compose / lifecycle-runtime-compose | 2.9.0 | AndroidX Apache-2.0 |
| Runtime | kotlinx-coroutines-android | 1.10.2 | Apache-2.0 |
| Runtime | OkHttp | 4.12.0 | Apache-2.0 |
| Test | JUnit | 4.13.2 | EPL-1.0 (with secondary license; inspect upstream) |
| Test | MockWebServer / okhttp-tls | 4.12.0 | Apache-2.0 |
| Test | org.json | 20240303 | JSON.org license (“The Software shall be used for Good, not Evil”); test-only, not OSI-approved |
| Instrumentation test | androidx.test.ext:junit / androidx.test:core / androidx.test:runner | 1.2.1 / 1.6.1 / 1.6.2 | AndroidX Apache-2.0; confirm transitive components |

Android SDK/platform and Gradle wrapper distributions are separate toolchain inputs. This is an inventory, **not** a lockfile, transitive SBOM or permission to distribute. `org.json` is test-only; Android platform supplies runtime JSON. The original Android inventory recorded no separate distribution-license declaration; the existing repository MIT license and that ambiguity are documented in [README.md](README.md). This export establishes a source snapshot only, not an exact tested-APK linkage. See [SOURCE-SNAPSHOT.md](SOURCE-SNAPSHOT.md).
