package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class WakeReadinessBoundaryTest {
 @Test fun onlyArmedRecordingOwnerCanPublishAndRecorderClockIsBoundedMetadata() {
  val gate=ListenerGate()
  var emits=0
  var owner=true
  var notification=true
  val publish={ armed:Boolean, recording:Boolean ->
   gate.publishReady(armed,recording,{owner && notification},{emits++})
  }
  assertTrue(gate.start(true))
  assertFalse(publish(false,false)) // initialization, before model arm
  assertFalse(publish(true,false)) // model armed, startRecording not confirmed
  assertFalse(publish(false,true))
  owner=false;assertFalse(publish(true,true)) // stale owner
  owner=true;notification=false;assertFalse(publish(true,true))
  notification=true;assertTrue(publish(true,true))
  assertEquals(1,emits)
  gate.stop();assertFalse(publish(true,true)) // late worker after Stop
  assertEquals(1,emits)
  assertTrue(gate.start(true));assertTrue(gate.hit())
  assertFalse(publish(true,true)) // released/hit cycle cannot restore Ready

  var mono=500L
  val diagnostic=WakeCaptureDiagnostics(1234) { mono }
  assertTrue(diagnostic.summary().contains("recordingStartedAtMs=-1"))
  val before=System.currentTimeMillis()
  diagnostic.recordingStarted()
  val after=System.currentTimeMillis()
  val wall=Regex("recordingStartedAtMs=(\\d+)").find(diagnostic.timedSummary())!!.groupValues[1].toLong()
  assertTrue(wall in before..after)
  assertTrue(diagnostic.timedSummary().contains("recordingStartedElapsedMs=500"))
  mono=1500L;diagnostic.samples(shortArrayOf(10),1);diagnostic.fedModel()
  assertTrue(diagnostic.timedSummary().contains("1s reads=1 samples=1"))
  assertFalse(diagnostic.timedSummary().contains("10,")) // no PCM array
 }
}
