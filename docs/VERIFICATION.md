# Verification record

Earlier sections below are historical private-review records, not current publication authorization.

## Scoped ACP source publication — 2026-10-30

Explicitly authorized narrow source port from accepted private ACP implementation, preserving the curated public baseline. Added four scoped adapter modules, credential-free generic bootstrap template and deployment guidance; selected backend defaults to the existing Codex route. Existing public integration opt-ins, one-mutation slot, receipt ownership and native client remain unchanged.

Focused offline verification, credential-isolated HOME/minimal environment and explicit publication inventory: **106 passed, 1 skipped, 10 subtests passed, 1 warning in 9.16s**. Command selected only `test_runtime.py`, `test_action_results.py`, `test_http.py`, `test_security.py`, `test_reconnect.py`, `test_public_defaults.py` and `test_publication_gate.py`; no full-suite rerun. The skipped installed-composition fixture requires optional `/opt/hermes-agent`. Warning remains existing aiohttp `NotAppKeyWarning`.

Inventory contains **91 files**. Final-manifest privacy scan and private deployment/account/path/LAN literal controls returned **0 findings**; heuristic only. **29 paths** covering native app/power/probes, public integration/core/runtime behavior and publication guards match baseline byte-for-byte. No private runtime profile, deployment unit, credentials, logs, DB, media or evidence files are included. Existing reviewed screenshot is unchanged. Public source port is not byte-identical to private activated source: generic paths/interpreter/persona, synthetic fixture isolation and explicit nonsecret timezone propagation are intentional publication adaptations.

No repeated independent safety review, provider prompt, live integration test, full suite, golden30/native probe, APK/VM/device build, service/config activation or other project work performed for this publication. Earlier accepted private live proofs do not prove this generic public deployment. Release/device/compatibility limitations below remain open.

No public release or public hosting is authorized by this record. The owner confirmed original authorship and selected MIT for the original project code; see ../LICENSE and ../LICENSE-STATUS.md. Third-party rights and binary distribution obligations remain separate and unaudited.

## Evidence before review corrections

The coordinator executed the complete safe offline Python suite: **205 passed, 44 subtests passed, 1 warning**. The then-current heuristic privacy scan returned **0 findings**. These results predate the scanner and TV-path corrections; they do not prove corrected source passed. Independent review found scanner blind spots, not actual secret/PII leaks.

## Correction verification

Synthetic negative controls were added before implementation. Initial run: **22 failed, 1 passed**. They exposed silently skipped directories, private environment filenames, long unquoted/mapping credentials, allowed-host URL credentials, unmanifested hidden/ignored/binary input, missing inventory/root, and stale import-time TV configuration. Corrected complete suite, with a temporary credential-isolated HOME, minimal environment, `PYTHONDONTWRITEBYTECODE=1` and `python -m pytest -q -p no:cacheprovider`: **236 passed, 44 subtests passed, 1 warning in 58.74s**. The warning is the existing aiohttp `NotAppKeyWarning` in bridge/server.py. An intermediate full run exposed the old manifest-description assertion (235 passed, 1 failed); that assertion now matches the corrected opt-in-integrations wording. No application behavior was changed to satisfy it. Final publication-input/privacy scan: **`privacy scan: 0 finding(s); heuristic only`** (exit 0). Final inventory: **79 files**, no generated/cache entries. Scanner was rerun after the final documentation update.

Publication input requires the explicit PUBLICATION-MANIFEST.txt inventory. Unknown/missing entries, forbidden generated directories, symlinks, unreadable/non-regular files and unreviewed binaries fail closed. The later presentation slice adds only the exact path/hash/validated-PNG exception documented below. Git ignore rules do not hide entries. Secret detection still uses heuristics. Independent manual review and a separately supplied private literal list remain required; zero findings cannot establish absence of PII or publication rights.

## MIT application verification

The owner confirmed original authorship and explicitly selected MIT. Canonical LICENSE text was obtained using `gh api licenses/mit`; only `[year]` and `[fullname]` were replaced with `2026` and `serexe`. Package metadata now declares `MIT`, and the explicit publication inventory includes LICENSE. No dependency/model/binary rights audit or publication approval is implied.

The complete safe offline suite was rerun with a temporary credential-isolated HOME, a minimal environment, `PYTHONDONTWRITEBYTECODE=1` and `python -m pytest -q -p no:cacheprovider tests`: **237 passed, 44 subtests passed, 1 warning in 58.64s**. The warning remains aiohttp `NotAppKeyWarning` in bridge/server.py. Final inventory: **80 files**, exactly matching PUBLICATION-MANIFEST.txt. Privacy scanner returned **`privacy scan: 0 finding(s); heuristic only`** (exit 0); it was rerun after this verification-record update. No private literal list was supplied for this slice, so this does not replace independent private-literal/manual review. No native rebuild or device test was performed, and no publication, deployment or archive creation occurred.

## GitHub presentation integration verification

The README and optional announcement now describe implemented capabilities separately from future experiments. MIT remains unchanged. One manually reviewed historical development screenshot is included at `assets/sarah-r1-native-redacted.png`; the conversation is visibly redacted. This is an intentional reviewed-image exception, not readable conversation history or evidence of installing this sanitized source on a device.

The scanner permits only that exact relative path with SHA-256 `1a818a483e5eaf2291e881dc0e5df5209eac74be7a95419a7b0da03e6cf93108`. It also validates PNG signature, chunk order and CRCs, RGB dimensions, compressed pixel length and scanline filters. Only IHDR, IDAT and IEND chunks are permitted; metadata and trailing data are rejected. All other binary/image paths remain prohibited, including byte-identical copies at other paths. Regression tests cover accepted original bytes, altered bytes, additional/renamed/nested images, metadata injection even with a substituted hash, and trailing data.

Final complete safe Python suite, with temporary credential-isolated HOME, minimal environment, `PYTHONDONTWRITEBYTECODE=1` and `python -m pytest -q -p no:cacheprovider tests`: **246 passed, 44 subtests passed, 1 warning in 58.79s** (exit 0). The warning remains the existing aiohttp `NotAppKeyWarning` in bridge/server.py. Final publication inventory: **82 files**, exactly matching PUBLICATION-MANIFEST.txt; additions are GITHUB-POST.md and the single reviewed image. Final scanner: **`privacy scan: 0 finding(s); heuristic only`** (exit 0). Relative README documentation/image links were checked against the tree. Scanner was rerun after this record update. No private literal list was supplied for this slice; heuristic results do not replace private-literal or independent visual review.

No native rebuild, device test, live integration access, service/profile change, publication, push, or archive creation occurred. The historical screenshot supplies presentation context only. Fresh SDK/device proof and all previously stated release gates remain open.

## Native evidence and limits

Coordinator native host ELF/build proof is retained outside this source candidate. It is historical evidence from before these corrections, **not a fresh rebuild**. No native rebuild, native probe execution, SDK/device-package acceptance, device installation, account access, or integration/service mutation was performed for this correction slice. Python pytest does not execute the retained C++ probes. Host ELF presence is not ARM64 Ubuntu Touch/device compatibility proof.

Tests use synthetic transports, mocked subprocesses and loopback fixtures. The socket monkeypatch is defense in depth, not a full network sandbox: it does not establish isolation of arbitrary future subprocess, DNS, UDP or Unix-socket behavior. Keep credential-isolated HOME and stronger CI/network isolation for unattended use. Optional model assets/dependencies and a tested Hermes internal API revision are not supplied or validated here. Manifest/CMake version mismatch, publisher identity, third-party rights/provenance and reporting channel remain release gates. MIT selection does not authorize publication.
