package com.serexe.sarah

import android.content.Context
import android.os.SystemClock
import kotlin.math.sqrt

/** One opt-in listener cycle. Counters only; never retains audio, recognition text, or exceptions. */
internal class WakeCaptureDiagnostics(
 private val startedAtMs: Long = System.currentTimeMillis(),
 private val monotonicMs: () -> Long = { SystemClock.elapsedRealtime() }
) {
 // First 32 seconds of recording only. One latest cycle + one latest hit, app-private.
 private class Bucket {
  var reads=0L; var samples=0L; var nonzero=0L; var feeds=0L
  var peak=0; var squares=0.0; var hit=false
  fun line(index:Int):String = "${index}s reads=$reads samples=$samples nonzero=$nonzero feeds=$feeds peak=$peak rms=${if(samples==0L) 0 else sqrt(squares/samples).toInt()} hit=$hit"
 }
 private val buckets=Array(32) { Bucket() }
 private var recordingAtMs:Long?=null
 private var recordingStartedAtMs:Long?=null
 private var lastBucket:Int?=null
 private var hitAtMs:Long?=null
 private var phase = "gate"
 private var result = "in-progress"
 private var started = false
 private var reads = 0L
 private var samples = 0L
 private var nonzero = 0L
 private var feeds = 0L
 private var peak = 0
 private var sumSquares = 0.0
 private val setupDurations=linkedMapOf<String,Long>()

 fun duration(name:String, milliseconds:Long) {
  require(name in setOf("focusMs","recorderMs","modelMs","warmupMs","armMs","recordStartMs"))
  setupDurations[name]=milliseconds
 }

 fun phase(value: String) {
  require(value in setOf("gate", "audio-focus", "recorder-create", "model-create", "record-start", "read", "model-feed"))
  phase = value
 }
 fun recordingStarted() { recordingAtMs=monotonicMs(); recordingStartedAtMs=System.currentTimeMillis(); started=true }
 private fun bucketIndex():Int? {
  val start=recordingAtMs ?: return null
  val elapsed=monotonicMs()-start
  return if(elapsed in 0 until 32000) (elapsed/1000).toInt() else null
 }
 fun samples(chunk: ShortArray, count: Int) {
  require(count in 0..chunk.size)
  if (count == 0) return
  val index=bucketIndex()
  lastBucket=index
  val bucket=index?.let { buckets[it] }
  reads++
  if(bucket!=null) { bucket.reads++; bucket.samples+=count }
  for (i in 0 until count) {
   val sample = chunk[i].toInt()
   val amplitude = if (sample == -32768) 32768 else kotlin.math.abs(sample)
   if (amplitude != 0) nonzero++
   if (amplitude > peak) peak = amplitude
   sumSquares += sample.toDouble() * sample
   if(bucket!=null) {
    if(amplitude!=0) bucket.nonzero++
    if(amplitude>bucket.peak) bucket.peak=amplitude
    bucket.squares+=sample.toDouble()*sample
   }
  }
  samples += count
 }
 fun fedModel() { feeds++; lastBucket?.let { buckets[it].feeds++ } }
 fun hit() { hitAtMs=monotonicMs()- (recordingAtMs ?: monotonicMs()); bucketIndex()?.let { buckets[it].hit=true } }
 fun finish(failure: Exception?) {
  result = when (failure) {
   null -> "ended"
   is SecurityException -> "security-exception"
   is IllegalStateException -> "state-exception"
   is IllegalArgumentException -> "argument-exception"
   else -> "other-exception"
  }
 }
 fun summary(): String = "timeMs=$startedAtMs recordingStartedAtMs=${recordingStartedAtMs ?: -1} result=$result phase=$phase recordingStarted=$started reads=$reads samples=$samples nonzero=$nonzero modelFeeds=$feeds peak=$peak rms=${if (samples == 0L) 0 else sqrt(sumSquares / samples).toInt()}" +
  setupDurations.entries.joinToString("") { " ${it.key}=${it.value}" }
 fun timedSummary():String = buildString {
  append("timeMs=$startedAtMs recordingStartedAtMs=${recordingStartedAtMs ?: -1} recordingStartedElapsedMs=${recordingAtMs ?: -1} recordingStarted=$started coverageMs=32000 bucketMs=1000 hitOffsetMs=${hitAtMs ?: -1} (only first 32s; later audio not measured)")
  buckets.forEachIndexed { index,b -> if(b.reads>0 || b.feeds>0 || b.hit) append('\n').append(b.line(index)) }
 }
 fun persist(context: Context) {
  val edit=context.getSharedPreferences("local-stage", Context.MODE_PRIVATE).edit()
   .putString("wake-capture-summary", summary())
   .putString("wake-timed-aggregate", timedSummary())
  if(hitAtMs!=null) edit.putString("wake-timed-last-hit",timedSummary())
  edit.apply()
 }
}
