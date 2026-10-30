package com.serexe.sarah

import android.content.res.AssetManager
import com.k2fsa.sherpa.onnx.FeatureConfig
import com.k2fsa.sherpa.onnx.KeywordSpotter
import com.k2fsa.sherpa.onnx.KeywordSpotterConfig
import com.k2fsa.sherpa.onnx.OnlineModelConfig
import com.k2fsa.sherpa.onnx.OnlineTransducerModelConfig

/** Offline inference only. No microphone, files, network, UI launch, or implicit activation.
 * Owner must run on a dedicated worker and explicitly arm after user opt-in, role/permission/
 * mic-privacy/call checks and TTS completion. A hit disarms until explicit re-arm, preventing
 * duplicate wake dispatch. Suspend before command capture/TTS; never share recorder ownership.
 * All JNI operations serialized with close, so teardown cannot race feed.
 */
internal class HeySarahKeywordEngine(assets: AssetManager) : AutoCloseable {
    private val spotter = KeywordSpotter(assets, KeywordSpotterConfig(
        featConfig = FeatureConfig(sampleRate = SAMPLE_RATE, featureDim = 80),
        modelConfig = OnlineModelConfig(
            transducer = OnlineTransducerModelConfig(
                encoder = "kws/encoder-epoch-12-avg-2-chunk-16-left-64.int8.onnx",
                decoder = "kws/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
                joiner = "kws/joiner-epoch-12-avg-2-chunk-16-left-64.int8.onnx"
            ),
            tokens = "kws/tokens.txt", modelType = "zipformer2",
            provider = "cpu", numThreads = 1
        ),
        keywordsFile = "kws/keywords.txt",
        keywordsScore = 1.5f, keywordsThreshold = 0.25f, numTrailingBlanks = 2
    ))
    private var stream = try { spotter.createStream() } catch (e: Throwable) {
        spotter.release(); throw e
    }
    private var armed = false
    private var closed = false

    /** New utterance context: never replay buffered speech from before opt-in/recovery. */
    @Synchronized fun arm() {
        check(!closed) { "Keyword engine closed" }
        armed = false
        stream.release()
        stream = spotter.createStream()
        armed = true
    }

    @Synchronized fun suspendDetection() {
        if (closed) return
        armed = false
        spotter.reset(stream)
    }

    /** 16 kHz mono signed PCM16 from future AudioRecord owner. True only on model result. */
    @Synchronized fun acceptPcm16(samples: ShortArray, count: Int = samples.size): Boolean {
        check(!closed) { "Keyword engine closed" }
        require(count in 0..samples.size)
        if (!armed || count == 0) return false
        stream.acceptWaveform(FloatArray(count) { samples[it] / 32768.0f }, SAMPLE_RATE)
        while (spotter.isReady(stream)) {
            spotter.decode(stream)
            if (spotter.getResult(stream).keyword == "HEY_SARAH") {
                armed = false
                spotter.reset(stream)
                return true
            }
        }
        return false
    }

    @Synchronized override fun close() {
        if (closed) return
        closed = true
        armed = false
        try { stream.release() } finally { spotter.release() }
    }

    companion object { const val SAMPLE_RATE = 16000 }
}
