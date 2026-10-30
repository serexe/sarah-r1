package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class AudioSafetyTest {
 @Test fun stopInvalidatesBeforeFrameworkCanRunQueuedRelease() {
  val session=ListenerSession();val events=mutableListOf<String>()
  assertTrue(session.gate.start(true));assertTrue(session.gate.hit())
  session.cancelBefore {
   events.add("framework-stop")
   // Simulates previously queued completion executing inside stopService boundary.
   session.releaseAfter({events.add("recorder-release");events.add("native-release");true},{true},{events.add("command")})
  }
  assertEquals(listOf("framework-stop","recorder-release","native-release"),events)
  assertTrue(session.released)
 }
 @Test fun commandOnlyAfterResourceCleanupAndEligibilityRecheck() {
  val session=ListenerSession();val events=mutableListOf<String>()
  session.gate.start(true);session.gate.hit()
  session.releaseAfter({events.add("recorder-release");events.add("native-release");true},{events.add("eligibility");true},{events.add("command")})
  assertEquals(listOf("recorder-release","native-release","eligibility","command"),events)
 }
 @Test fun invalidationDuringCleanupCancelsCommand() {
  val session=ListenerSession();var commands=0
  session.gate.start(true);session.gate.hit()
  session.releaseAfter({session.cancelBefore {};true},{true},{commands++})
  assertEquals(0,commands)
 }
 @Test fun stopRetainsExclusiveLeaseUntilRecorderAck() {
  val session=ListenerSession();val command=Any();val tts=Any()
  assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.cancelBefore {}
   assertFalse(session.released);assertFalse(AudioArbiter.acquire(command));assertFalse(AudioArbiter.acquire(tts))
   session.releaseAfter({true},{true},{fail("cancelled wake")})
   assertTrue(AudioArbiter.acquire(tts));assertFalse(AudioArbiter.acquire(command))
  } finally {AudioArbiter.release(session);AudioArbiter.release(tts);AudioArbiter.release(command)}
 }
 @Test fun eligibilityLostAfterReleaseDiscardsHit() {
  val session=ListenerSession();session.gate.start(true);session.gate.hit()
  session.releaseAfter({true}, {false},{fail("ineligible command")})
  assertTrue(session.released)
 }
}
