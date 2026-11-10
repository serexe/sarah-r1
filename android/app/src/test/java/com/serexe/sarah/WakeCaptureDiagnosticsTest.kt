package com.serexe.sarah

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WakeCaptureDiagnosticsTest {
 @Test fun readPacingBacksOffOnlyWhenNoSamples() {
  assertEquals(20L,wakeReadDelayMs(0))
  assertEquals(0L,wakeReadDelayMs(1))
  assertEquals(0L,wakeReadDelayMs(320))
 }
 @Test fun initialAndSilentCycle() {
  val d=WakeCaptureDiagnostics(1234)
  d.phase("record-start")
  d.recordingStarted()
  d.phase("read")
  d.samples(shortArrayOf(0,0),2)
  d.finish(null)
  assertTrue(d.summary().matches(Regex("timeMs=1234 recordingStartedAtMs=\\d+ result=ended phase=read recordingStarted=true reads=1 samples=2 nonzero=0 modelFeeds=0 peak=0 rms=0")))
 }
 @Test fun aggregatesOnlyAndCategorizesFailure() {
  val d=WakeCaptureDiagnostics(5678)
  d.phase("model-feed")
  d.samples(shortArrayOf(100,-100,0),3)
  d.fedModel()
  d.finish(IllegalStateException("private transcript / token"))
  val summary=d.summary()
  assertTrue(summary.contains("result=state-exception phase=model-feed"))
  assertTrue(summary.contains("reads=1 samples=3 nonzero=2 modelFeeds=1 peak=100 rms=81"))
  assertFalse(summary.contains("private transcript"))
  assertFalse(summary.contains("token"))
 }
 @Test fun boundedRecordingRelativeBucketsAndHit() {
  var now=400L
  val d=WakeCaptureDiagnostics(9876) { now }
  d.recordingStarted()
  d.samples(shortArrayOf(100,-100),2); d.fedModel()
  now=1400L
  d.samples(shortArrayOf(0,200),2); d.fedModel(); d.hit()
  now=32400L
  d.samples(shortArrayOf(32767),1); d.fedModel()
  val rows=d.timedSummary()
  assertTrue(rows.contains("timeMs=9876 recordingStartedAtMs="))
  assertTrue(rows.contains("recordingStartedElapsedMs=400 recordingStarted=true coverageMs=32000 bucketMs=1000 hitOffsetMs=1000"))
  assertTrue(rows.contains("0s reads=1 samples=2 nonzero=2 feeds=1 peak=100 rms=100 hit=false"))
  assertTrue(rows.contains("1s reads=1 samples=2 nonzero=1 feeds=1 peak=200 rms=141 hit=true"))
  assertFalse(rows.contains("32767"))
  assertFalse(rows.contains("32s reads="))
  assertTrue(d.summary().contains("reads=3 samples=5"))
 }
 @Test fun neverStoresAudioOrExceptionTextInTimedRows() {
  var now=0L
  val d=WakeCaptureDiagnostics(333) { now }
  d.recordingStarted(); now=100
  d.samples(shortArrayOf(-32768),1); d.fedModel()
  d.finish(IllegalStateException("private spoken phrase"))
  val rows=d.timedSummary()
  assertTrue(rows.contains("peak=32768 rms=32768"))
  assertFalse(rows.contains("private spoken phrase"))
  assertFalse(rows.contains("-32768"))
 }
}
