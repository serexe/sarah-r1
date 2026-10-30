# SARAH selected encoder provenance

Original official model archive, NOT the batch-one mobile-converted encoder:
https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2
SHA256 f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a

Original archive README explicitly declares Apache License 2.0, retained unchanged.
Mobile converted encoder failed genuine sherpa-onnx 2.0.1 host inference with ONNX Reshape error; replaced by original dynamic-batch int8 encoder. Decoder/joiner/tokens/BPE identical assets from original model. SentencePiece-generated keyword file added for spoken HEY SARAH; result alias HEY_SARAH.
