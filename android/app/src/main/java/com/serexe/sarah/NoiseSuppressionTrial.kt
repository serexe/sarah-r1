package com.serexe.sarah

import android.media.audiofx.AudioEffect
import android.media.audiofx.NoiseSuppressor
import android.util.Log

/** Per-recorder, Lenovo-only opt-in. No global audio policy or source changes. */
internal class NoiseSuppressionTrial private constructor(
 private var effect: Effect?,
 private val lane: String,
 private val report: (String) -> Unit
) {
 interface Effect {
  fun enable(): Int
  fun enabled(): Boolean
  fun hasControl(): Boolean
  fun release()
 }
 interface Factory {
  fun available(): Boolean
  fun create(sessionId: Int): Effect?
 }
 companion object {
  private val androidFactory = object: Factory {
   override fun available() = NoiseSuppressor.isAvailable()
   override fun create(sessionId: Int): Effect? = NoiseSuppressor.create(sessionId)?.let { ns ->
    object: Effect {
     override fun enable() = ns.setEnabled(true)
     override fun enabled() = ns.enabled
     override fun hasControl() = ns.hasControl()
     override fun release() = ns.release()
    }
   }
  }

  fun attach(sessionId: Int, lane: String, factory: Factory = androidFactory,
             report: (String) -> Unit = { Log.i("SarahNoiseTrial", it) }): NoiseSuppressionTrial {
   // Only fixed categories, never session IDs, audio or exception contents.
   val available = try {factory.available()} catch (_: Exception) {false} catch (_: LinkageError) {false}
   if(!available) {
    runCatching {report("$lane NS available=false attached=false enabled=false fallback=unavailable")}
    return NoiseSuppressionTrial(null,lane,report)
   }
   val effect = try {factory.create(sessionId)} catch (_: Exception) {null} catch (_: LinkageError) {null}
   if(effect==null) {
    runCatching {report("$lane NS available=true attached=false enabled=false fallback=create")}
    return NoiseSuppressionTrial(null,lane,report)
   }
   val enabled = try {
    effect.enable()==AudioEffect.SUCCESS && effect.hasControl() && effect.enabled()
   } catch (_: Exception) {false} catch (_: LinkageError) {false}
   if(!enabled) {
    // Failed enable must not hold recorder or change baseline capture behavior.
    val released=try {effect.release();true} catch (_: Exception) {false} catch (_: LinkageError) {false}
    runCatching {report("$lane NS available=true attached=false enabled=false fallback=${if(released) "enable" else "enable-release"}")}
    return NoiseSuppressionTrial(null,lane,report)
   }
   runCatching {report("$lane NS available=true attached=true enabled=true fallback=none")}
   return NoiseSuppressionTrial(effect,lane,report)
  }
 }

 /** Once only, by same recorder owner, before its AudioRecord.release(). */
 fun close(): Boolean {
  val owned=effect ?: return true
  effect=null
  val released=try {owned.release();true} catch (_: Exception) {false} catch (_: LinkageError) {false}
  if(!released) runCatching {report("$lane NS release=failed")}
  return released
 }
}