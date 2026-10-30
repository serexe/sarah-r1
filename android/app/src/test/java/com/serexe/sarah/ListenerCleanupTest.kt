package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.Executors

/** Same cleanup runner, session ACK and teardown gate used by service finally/complete.
 * Only native/framework operations substituted; no Android callback/device proof implied.
 */
@RunWith(Parameterized::class)
class ListenerCleanupTest(private val reason:String,private val step:Int) {
 companion object {
  @JvmStatic @Parameterized.Parameters(name="{0}/cleanup-step-{1}")
  fun cases():List<Array<Any>> = listOf("Stop","notification-loss").flatMap {reason ->
   (0..5).map {step -> arrayOf<Any>(reason,step)}
  }
 }
 private class Boundary {
  val session=ListenerSession()
  val cleanup=ListenerCleanup()
  val next=Any()
  var notification=true
  var worker=true
  var removals=0
  var wakes=0
  var releasedStages=0
  var off=false
  val service=ServiceTeardown({session.stopListening()},
   {!worker && cleanup.complete && session.released}, {removals++;off=true})
  init {assertTrue(AudioArbiter.acquire(session));session.gate.start(true);session.gate.hit();cleanup.begin()}
  fun stop(reason:String) {
   if(reason=="notification-loss") notification=false
   service.stop()
  }
  fun complete():Boolean = session.releaseAfter({cleanup.complete}, {notification}, {wakes++},
   {worker=false;releasedStages++})
  fun blocked() {
   assertFalse(cleanup.complete);assertFalse(session.released)
   assertFalse(service.finish());assertFalse(off);assertEquals(0,removals)
   assertEquals(0,wakes);assertEquals(0,releasedStages)
   assertFalse(AudioArbiter.idle());assertFalse(AudioArbiter.acquire(next))
  }
  fun dispose() {AudioArbiter.release(session);AudioArbiter.release(next)}
 }
 private fun finish(b:Boundary,ops:List<()->Unit>) = b.cleanup.finish(ops[0],ops[1],ops[2],ops[3],ops[4],ops[5])

 @Test fun failedProductionCleanupNeverAcknowledgesOrTeardowns() {
  val b=Boundary();val attempts=mutableListOf<Int>()
  try {
   b.stop(reason)
   val ops=(0..5).map {i -> {attempts.add(i);if(i==step) error("injected-cleanup-failure");Unit}}
   assertFalse(finish(b,ops));assertEquals((0..5).toList(),attempts)
   assertFalse(b.complete());b.blocked()
   // Repeated application Stop or queued completion must not free failed owner.
   b.stop(reason);assertFalse(b.complete());b.blocked()
  } finally {b.dispose()}
 }
 @Test fun delayedProductionCleanupRetainsLeaseAndFgsUntilActualAck() {
  val b=Boundary();val entered=CountDownLatch(1);val allow=CountDownLatch(1)
  val executor=Executors.newSingleThreadExecutor()
  try {
   val ops=(0..5).map {i -> {if(i==step) {entered.countDown();check(allow.await(3,TimeUnit.SECONDS))};Unit}}
   val pending=executor.submit<Boolean> {finish(b,ops)}
   assertTrue(entered.await(3,TimeUnit.SECONDS))
   b.stop(reason);assertFalse(b.complete());b.blocked()
   allow.countDown();assertTrue(pending.get(3,TimeUnit.SECONDS))
   assertTrue(b.complete());assertTrue(b.session.released);assertEquals(1,b.releasedStages)
   assertEquals(0,b.wakes);assertTrue(b.service.finish());assertFalse(b.service.finish())
   assertTrue(b.off);assertEquals(1,b.removals);assertTrue(AudioArbiter.acquire(b.next))
  } finally {allow.countDown();executor.shutdownNow();b.dispose()}
 }
 @Test fun uncertainConstructorCannotBecomeSuccessfulCleanup() {
  val b=Boundary()
  try {
   b.stop(reason)
   assertTrue(runCatching {b.cleanup.construct<Any> {error("native-construction-uncertain")}}.isFailure)
   assertFalse(finish(b,List(6) {{}}));assertFalse(b.complete());b.blocked()
  } finally {b.dispose()}
 }
}

class ListenerCleanupAckTest {
 @Test fun stopBeforeWorkerMayReleaseOnlyKnownEmptyCleanupBoundary() {
  val session=ListenerSession();val cleanup=ListenerCleanup();assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.stopListening()
   assertTrue(cleanup.complete)
   assertTrue(session.releaseAfter({cleanup.complete},{true},{fail("cold stop wake")}))
   assertTrue(session.released);assertTrue(AudioArbiter.idle())
  } finally {AudioArbiter.release(session)}
 }
 @Test fun prematureAckCannotReplayHitAfterEventualCleanup() {
  val session=ListenerSession();val cleanup=ListenerCleanup();val events=mutableListOf<String>()
  assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.gate.hit();cleanup.begin()
   assertFalse(session.releaseAfter({cleanup.complete},{true},{fail("early wake")}))
   // Prior failed ACK invalidates hit; a fresh session is required (no replay).
   assertTrue(cleanup.finish({events.add("stop")},{events.add("release")},{events.add("engine")},
    {events.add("recording-callback")},{events.add("device-callback")},{events.add("focus")}))
   assertTrue(session.releaseAfter({cleanup.complete},{true},{fail("replayed wake")},{events.add("ack")}))
   assertTrue(AudioArbiter.idle());assertEquals(7,events.size)
  } finally {AudioArbiter.release(session)}
 }
 @Test fun normalHitDispatchesOnceAfterSuccessfulCleanup() {
  val session=ListenerSession();val cleanup=ListenerCleanup();var wakes=0;var acks=0
  assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.gate.hit();cleanup.begin()
   assertTrue(cleanup.finish({}, {}, {}, {}, {}, {}))
   repeat(2) {assertTrue(session.releaseAfter({cleanup.complete},{true},{assertTrue(AudioArbiter.idle());assertEquals(1,acks);wakes++},{acks++}))}
   assertEquals(1,wakes);assertEquals(1,acks)
  } finally {AudioArbiter.release(session)}
 }
 @Test fun thrownCleanupRetainsOwnership() {
  val session=ListenerSession();assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.gate.hit()
   assertFalse(session.releaseAfter({error("cleanup-throw")},{true},{fail("wake")}))
   assertFalse(session.released);assertFalse(AudioArbiter.idle())
  } finally {AudioArbiter.release(session)}
 }
 @Test fun simultaneousNativeFailuresStillAttemptEveryCleanupWithoutAck() {
  val cleanup=ListenerCleanup();val events=mutableListOf<String>();cleanup.begin()
  assertFalse(cleanup.finish({events.add("stop");error("stop-failed")},
   {events.add("release");error("release-failed")}, {events.add("engine");error("close-failed")},
   {events.add("recording-callback")}, {events.add("device-callback")}, {events.add("focus")}))
  assertFalse(cleanup.complete)
  assertEquals(listOf("stop","release","engine","recording-callback","device-callback","focus"),events)
 }
 @Test fun notificationLossAtReleasedStageCancelsQueuedWake() {
  val session=ListenerSession();assertTrue(AudioArbiter.acquire(session))
  try {
   session.gate.start(true);session.gate.hit()
   assertTrue(session.releaseAfter({true},{true},{fail("wake after stage cancellation")},
    {session.stopListening()}))
   assertTrue(session.released);assertTrue(AudioArbiter.idle())
  } finally {AudioArbiter.release(session)}
 }
}
