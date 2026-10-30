package com.serexe.sarah

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.util.concurrent.CompletableFuture

/** Real service completion boundary + production listener/command ownership; no Android lifecycle emulation. */
class ServiceCommandRearmTest {
 @Test fun persistentSameOwnerRearmsAfterOriginalTwoMinuteBoundaryButNeverAfterStop() {
  val now=86_401_000L
  assertTrue(ServiceRearmPolicy.allowed(true,false,false,1000,now,true,true,true,persistent=true))
  assertFalse(ServiceRearmPolicy.allowed(true,false,false,1000,now,true,true,true))
  assertFalse(ServiceRearmPolicy.allowed(true,true,false,1000,now,true,true,true,persistent=true))
  assertFalse(ServiceRearmPolicy.allowed(false,false,false,1000,now,true,true,true,persistent=true))
  assertFalse(ServiceRearmPolicy.allowed(true,false,false,1000,now,true,false,true,persistent=true))
  assertFalse(ServiceRearmPolicy.allowed(true,false,false,1000,now,true,true,false,persistent=true))
 }
 @Test fun sameServiceReturnsToListenerAfterSuccessErrorAndCancelCleanup()=runBlocking {
  var now=10_000L
  val started=now
  var listener=ListenerSession()
  assertTrue(AudioArbiter.acquire(listener));assertTrue(listener.gate.start(true))
  var restarts=0;var stops=0
  try {
   for(outcome in listOf("done","error","cancelled")) {
    assertTrue(listener.gate.hit())
    assertTrue(listener.releaseAfter({true},{true},{}))
    val command=Any();assertTrue(OffscreenOwnership.acquire(command))
    var ack=false
    val completion=ServiceCommandCompletion(
     {ack && listener.released && !OffscreenOwnership.held()},
     {ServiceRearmPolicy.allowed(true,false,false,started,now,true,true,OffscreenWakePolicy.resolved(outcome))},
     {val next=ListenerSession();if(!AudioArbiter.acquire(next)) false else {
      assertTrue(next.gate.start(true));listener=next;restarts++;true}},
     {stops++})
    try {
     assertFalse(completion.complete()) // terminal row/cancellation is not native ACK
     assertEquals(0,stops)
     ack=CommandCleanup.await(null,{true},CompletableFuture.completedFuture(true))
     assertFalse(completion.complete()) // ACK without command lease release also insufficient
     OffscreenOwnership.release(command)
     assertTrue("$outcome must return same service to listening",completion.complete())
     assertFalse("duplicate cleanup callback cannot start another listener",completion.complete())
     assertTrue(listener.gate.listening(true));assertEquals(0,stops)
     now+=1000
    } finally {OffscreenOwnership.release(command)}
   }
   assertEquals(3,restarts)
  } finally {
   listener.stopListening();assertTrue(listener.releaseAfter({true},{false},{}))
  }
  assertTrue(AudioArbiter.idle())
 }
 @Test fun stopLockRoleNotificationDeadlineAndUnknownOutcomeFailClosed() {
  fun allowed(owner:Boolean=true,stop:Boolean=false,destroyed:Boolean=false,start:Long=10_000L,
   now:Long=11_000L,safe:Boolean=true,unlocked:Boolean=true,phase:String="done")=
   ServiceRearmPolicy.allowed(owner,stop,destroyed,start,now,safe,unlocked,OffscreenWakePolicy.resolved(phase))
  assertTrue(allowed()) // no screen-interactivity requirement: unlocked screen-off remains eligible
  val rejected=listOf(allowed(stop=true),allowed(unlocked=false),allowed(safe=false), // role/notification/audio
   allowed(now=130_000L),allowed(start=0),allowed(phase="uncertain"),allowed(phase="confirming"),
   allowed(phase="polling"),allowed(destroyed=true),allowed(owner=false))
  for(admitted in rejected) {
   var starts=0;var stops=0
   val completion=ServiceCommandCompletion({true},{admitted},{starts++;true},{stops++})
   assertFalse(completion.complete());assertEquals(0,starts);assertEquals(1,stops)
   assertFalse(completion.complete());assertEquals(1,stops)
  }
  var stopped=0
  val busy=Any();assertTrue(AudioArbiter.acquire(busy))
  try {
   val completion=ServiceCommandCompletion({true},{true},{AudioArbiter.acquire(Any())},{stopped++})
   assertFalse(completion.complete());assertEquals(1,stopped)
  } finally {AudioArbiter.release(busy)}
 }
 @Test fun failedNativeCleanupCannotRestartOrReportOff()=runBlocking {
  val listener=ListenerSession();assertTrue(AudioArbiter.acquire(listener));listener.gate.start(true);listener.gate.hit()
  var restarted=false;var off=false
  try {
   assertFalse(listener.releaseAfter({false},{true},{error("no wake before native ACK")}))
   val commandAck=CommandCleanup.await(null,{false},CompletableFuture.completedFuture(true))
   val completion=ServiceCommandCompletion({listener.released && commandAck},{true},{restarted=true;true},{off=true})
   assertFalse(completion.complete());assertFalse(restarted);assertFalse(off);assertFalse(AudioArbiter.idle())
  } finally {AudioArbiter.release(listener)}
 }
 @Test fun pendingNativeReleaseBlocksRearmUntilAcknowledged()=runBlocking {
  val command=Any();assertTrue(OffscreenOwnership.acquire(command))
  val nativeReleased=CompletableDeferred<Unit>();var released=false;var ack=false;var starts=0;var off=0
  val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
  val recording=scope.launch {
   try {awaitCancellation()} finally {withContext(NonCancellable) {nativeReleased.await();released=true}}
  }
  val completion=ServiceCommandCompletion({ack && !OffscreenOwnership.held()},{true},{starts++;true},{off++})
  try {
   recording.cancel()
   val cleanup=async(start=CoroutineStart.UNDISPATCHED) {
    CommandCleanup.await(recording,{released},CompletableFuture.completedFuture(true))
   }
   assertFalse(cleanup.isCompleted);assertFalse(completion.complete());assertEquals(0,starts);assertEquals(0,off)
   nativeReleased.complete(Unit);ack=cleanup.await();assertTrue(ack)
   assertFalse(completion.complete());assertEquals(0,starts) // lease release still required
   OffscreenOwnership.release(command)
   assertTrue(completion.complete());assertEquals(1,starts);assertEquals(0,off)
  } finally {nativeReleased.complete(Unit);scope.cancel();OffscreenOwnership.release(command)}
 }
 @Test fun visibleProductionHandoffRetainsOwnerUntilCompletionAndOriginalDeadline() {
  val source=File("src/main/java/com/serexe/sarah/HeySarahListenerService.kt").readText()
  val visible=source.substringAfter("val listenerOwner=session").substringBefore("} else if(AudioEligibility")
  assertTrue(visible.contains("visibleCommand=handoff"));assertTrue(visible.contains("ServiceCommandCompletion("))
  assertTrue(visible.contains("AudioArbiter.idle()"));assertTrue(visible.contains("ServiceRearmPolicy.allowed("))
  assertTrue(visible.contains("current===listenerOwner"));assertTrue(visible.contains("{visibleCommand=null;rearmAfterCommand()}"))
  assertTrue(visible.contains("if(!handed) {visibleCommand=null;stage(\"fallback\");notifyWake();finishService()}"))
  assertFalse(visible.contains("startForegroundService("));assertFalse(visible.contains("optedStart="))
  assertFalse(visible.contains("postDelayed(cutoff"))
 }
 @Test fun eachOffscreenCommandGetsFreshFiniteMonotonicWindowNotPersistentOptIn() {
  val service=File("src/main/java/com/serexe/sarah/HeySarahListenerService.kt").readText()
  val command=File("src/main/java/com/serexe/sarah/OffscreenCommand.kt").readText()
  assertTrue(service.contains("OffscreenCommand(this,ListenerWindow(SystemClock.elapsedRealtime(),persistent=false),"))
  assertFalse(service.contains("OffscreenCommand(this,Long.MAX_VALUE"))
  assertTrue(command.contains("private val deadline:ListenerWindow"))
  assertEquals(2,Regex("deadline\\.valid\\(SystemClock\\.elapsedRealtime\\(\\)\\)").findAll(command).count())
  assertTrue(command.contains("if(!eligible()) stop()"))
  assertTrue(command.contains("p.eligibility={scope.isActive && eligible()}"))
  val admitted=86_401_000L // persistent listener may already be days old
  val window=ListenerWindow(admitted,persistent=false)
  assertTrue(window.valid(admitted));assertTrue(window.valid(admitted+119_999))
  assertFalse(window.valid(admitted+120_000));assertFalse(window.valid(admitted-1))
 }
 @Test fun commandDeadlineDuringPendingPreparationRejectsLateStartAndWaitsForRealRelease()=runBlocking {
  // Both scheduled invalidation and the final eligibility recheck must reject late native start.
  for(watchdog in listOf(true,false)) {
   val now=java.util.concurrent.atomic.AtomicLong(86_401_000L)
   val window=ListenerWindow(now.get(),persistent=false)
   val entered=java.util.concurrent.CountDownLatch(1);val resume=java.util.concurrent.CountDownLatch(1)
   val closing=java.util.concurrent.CountDownLatch(1);val release=java.util.concurrent.CountDownLatch(1)
   val starts=java.util.concurrent.atomic.AtomicInteger();val closes=java.util.concurrent.atomic.AtomicInteger()
   val played=java.util.concurrent.atomic.AtomicBoolean(true)
   val owner=PlaybackOwnership();val lease=Any()
   assertTrue(OffscreenOwnership.acquire(lease))
   val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
   fun barrier(latch:java.util.concurrent.CountDownLatch) {check(latch.await(3,java.util.concurrent.TimeUnit.SECONDS))}
   val preparing=scope.launch {
    played.set(owner.play({window.valid(now.get())}) {object:PlaybackOwnership.Resource {
     override fun initialize() {}
     override fun prepare() {entered.countDown();barrier(resume)}
     override fun start() {starts.incrementAndGet()}
     override fun close():Boolean {closing.countDown();barrier(release);closes.incrementAndGet();return true}
    }})
   }
   var ack=false;var rearms=0;var off=0
   val completion=ServiceCommandCompletion({ack && !OffscreenOwnership.held()},
    {window.valid(now.get())},{rearms++;true},{off++})
   try {
    barrier(entered);now.addAndGet(ListenerWindow.LIMIT_MS)
    assertFalse(window.valid(now.get()))
    val nativeAck=if(watchdog) owner.stop() else {
     // Let prepare return before watchdog invalidation: eligibility alone must veto start.
     resume.countDown();barrier(closing);owner.stop()
    }
    assertFalse("expiry invalidation is not cleanup ACK",nativeAck.isDone)
    if(watchdog) preparing.cancel() // coroutine cancellation also cannot acknowledge blocked native work
    assertFalse(completion.complete());assertEquals(0,rearms);assertEquals(0,off)
    assertFalse(CommandCleanup.await(null,{true},nativeAck,timeoutMs=25,preparing=preparing))
    assertFalse(nativeAck.isDone);assertTrue(OffscreenOwnership.held())
    assertFalse(completion.complete());assertEquals(0,off)
    val cleanup=async(start=CoroutineStart.UNDISPATCHED) {
     CommandCleanup.await(null,{true},nativeAck,preparing=preparing)
    }
    assertFalse(cleanup.isCompleted)
    resume.countDown();barrier(closing)
    assertEquals(0,starts.get());assertEquals(0,closes.get())
    assertFalse(cleanup.isCompleted);assertFalse(completion.complete());assertEquals(0,off)
    release.countDown();ack=cleanup.await()
    assertTrue(ack);assertFalse(played.get());assertEquals(1,closes.get())
    assertFalse(completion.complete()) // real native ACK alone cannot release command lease
    OffscreenOwnership.release(lease)
    assertFalse(completion.complete());assertEquals(0,rearms);assertEquals(1,off)
   } finally {
    resume.countDown();release.countDown();preparing.join();scope.cancel();OffscreenOwnership.release(lease)
   }
  }
 }
 @Test fun productionWiringKeepsExistingForegroundOwnerAndNeverRepostsOnReturn() {
  val service=File("src/main/java/com/serexe/sarah/HeySarahListenerService.kt").readText()
  val boundary=service.substringAfter("lateinit var completion:ServiceCommandCompletion").substringBefore("private fun stage(")
  assertTrue(boundary.contains("{completion.complete()}"));assertTrue(boundary.contains("owner.cleanupComplete"))
  assertTrue(boundary.contains("!OffscreenOwnership.held()"));assertTrue(boundary.contains("ServiceRearmPolicy.allowed("))
  assertTrue(boundary.contains("{rearmAfterCommand()}"));assertTrue(boundary.contains("AudioArbiter.acquire(next)"))
  assertFalse(boundary.contains("startForegroundService("));assertFalse(boundary.contains("isInteractive"))
  assertFalse(boundary.contains("optedStart="));assertFalse(boundary.contains("postDelayed(cutoff"))
  val command=File("src/main/java/com/serexe/sarah/OffscreenCommand.kt").readText()
  assertEquals(1,Regex("bridge\\.submitCancellable\\(").findAll(command).count())
  assertFalse(command.contains("bridge.confirm"));assertTrue(command.contains("rearmAllowed=!stopped && eligible() && OffscreenWakePolicy.resolved"))
  assertTrue(command.indexOf("CommandCleanup.await(")<command.indexOf("rearmAllowed=!stopped"))
  assertTrue(command.indexOf("OffscreenOwnership.release(this@OffscreenCommand);finished()")>command.indexOf("rearmAllowed=!stopped"))
 }
}
