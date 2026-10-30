# Offline keyword engine dependency and model provenance

The source includes an opt-in persistent foreground-microphone listener using `HeySarahKeywordEngine`. This document records dependency/model provenance, not a claim of runtime validation of this exported snapshot. See [README.md](README.md) for consent and publication limits.

## Code
- Official sherpa-onnx **v2.0.1**, Apache-2.0: https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/LICENSE
- Official AAR: https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-2.0.1.aar
- SHA256 **a8d09d1d32f3eb8520482c6d3d43fae674681c5b050385967c70a3c2c9bf0ee7**, verified against GitHub API asset digest. Vendored unchanged `app/libs/sherpa-onnx-2.0.1.aar`.
- ABI filter: arm64-v8a + x86_64. Both contain libonnxruntime, sherpa C/C++ API and JNI libraries. No claim physical ARM64 execution.
- Upstream v2.0.1 Android runtime CMake pins ONNX Runtime **1.28.2**: https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/cmake/onnxruntime-android-aarch64.cmake
- ONNX Runtime MIT license and third-party notices from microsoft/onnxruntime **v1.28.2**, retained in APK assets/licenses along with engine Apache-2.0 license. Existing provisional 1.23.2 texts were replaced before final build.

## Model
- Official mobile artifact: https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01-mobile.tar.bz2
- Archive SHA256 **2e6ac2577310bfa2f4b6b5fab0478b868c9d0b2cb2c51b3e13b50581b588864d** (verify inventory).
- Model-specific README shipped inside official archive explicitly declares `license: Apache License 2.0`; it names author's repository https://www.modelscope.cn/pkufool/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.git. Upstream Kotlin API also points to this author's exact model. README preserved byte-for-byte in assets/kws; notes.md records SARAH's original-encoder selection; this is separate evidence from code license.
- Final selected archive: https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
- Original archive SHA256 **f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a**. Original README also explicitly declares Apache License 2.0. The mobile-converted encoder failed ONNX Reshape in real inference; replaced with original dynamic-batch int8 encoder. Decoder/joiner/tokens/BPE checked byte-identical between archives.
- GigaSpeech XL-trained 3.3M English model. Bundled original int8 encoder/joiner, float decoder, tokens.txt, bpe.model. No training audio/test_wavs bundled in production.
- HEY SARAH encoded with actual supplied SentencePiece bpe.model: `▁HE Y ▁SA RA H @HEY_SARAH`. Every token validated in supplied tokens.txt. Underscore is result alias only, not spoken phrase. Space in result alias fails sherpa keyword parser; discovered and corrected by real native inference.

## Runtime-proof limits
Host inference and the mobile-encoder failure described above are historical workspace provenance notes, not tests rerun for publication. The exported source now includes opt-in listener UI and lifecycle code. Their presence is not proof of wake reliability, recorder handoff, background recovery or battery behavior. Exact-APK emulator and approved physical ARM64/black-screen validation are outside this source-publication task. Never upload ambient audio or retain household PCM.
