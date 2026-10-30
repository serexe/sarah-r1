package com.serexe.sarah

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** Actual service teardown + command cleanup + playback ownership boundaries; native calls replaced.
 * Android framework callbacks themselves still require exact-byte device proof. */
class CommandTeardownTest {
 private val reasons=listOf("Stop","task-removal","notification-loss","lock","cancel","destroy")
 private fun barrier(latch:CountDownLatch) {check(latch.await(3,TimeUnit.SECONDS))}
 @Test fun captureReleaseBeforeServiceTeardownForEveryExit()=runBlocking {
  for(reason in reasons) {
   val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
   val released=AtomicBoolean(false);val ack=AtomicBoolean(false);val removed=AtomicInteger()
   val scope=CoroutineScope(SupervisorJob()+Dispatchers.Default)
   val recording=scope.launch {
    try {entered.complete(Unit);awaitCancellation()} finally {
     withContext(NonCancellable) {release.await();released.set(true)}
    }
   }
   entered.await()
   val service=ServiceTeardown({scope.cancel()},{ack.get()},{removed.incrementAndGet()})
   if(reason=="destroy") service.destroyed() else service.stop()
   assertTrue(service.stopped);assertFalse(service.finish());assertEquals(0,removed.get())
   val waiting=async(start=CoroutineStart.UNDISPATCHED) {
    CommandCleanup.await(recording,{released.get()},CompletableFuture.completedFuture(true))
   }
   assertFalse("$reason must await recorder finally",waiting.isCompleted)
   assertFalse(recording.isCompleted)
   release.complete(Unit)
   ack.set(waiting.await());assertTrue(ack.get());assertTrue(service.finish())
   assertEquals(if(reason=="destroy") 0 else 1,removed.get())
   assertFalse(service.finish())
  }
 }
 @Test fun prepareAndReleaseBarriersGateServiceForEveryExit()=runBlocking {
  for(reason in reasons) {
   val prepared=CountDownLatch(1);val allowPrepare=CountDownLatch(1)
   val closing=CountDownLatch(1);val allowRelease=CountDownLatch(1)
   val starts=AtomicInteger();val released=AtomicBoolean(false);val ack=AtomicBoolean(false)
   val removed=AtomicInteger();val active=AtomicBoolean(true)
   val pool=Executors.newSingleThreadExecutor()
   val owner=PlaybackOwnership(dispatchCleanup={pool.execute(it)})
   val scope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
   val preparing=scope.launch {
    owner.play({active.get()}) {object:PlaybackOwnership.Resource {
     override fun initialize() {}
     override fun prepare() {prepared.countDown();barrier(allowPrepare)}
     override fun start() {starts.incrementAndGet()}
     override fun close():Boolean {closing.countDown();barrier(allowRelease);released.set(true);return true}
    }}
   }
   try {
    barrier(prepared)
    var closed=CompletableFuture.completedFuture(false)
    val service=ServiceTeardown({active.set(false);scope.cancel();closed=owner.stop()},
     {ack.get()},{removed.incrementAndGet()})
    if(reason=="destroy") service.destroyed() else service.stop()
    assertFalse(service.finish());assertFalse(closed.isDone)
    val waiting=async(start=CoroutineStart.UNDISPATCHED) {
     CommandCleanup.await(null,{true},closed,preparing=preparing)
    }
    assertFalse(waiting.isCompleted)
    allowPrepare.countDown();barrier(closing)
    assertFalse(closed.isDone);assertFalse(service.finish());assertEquals(0,starts.get())
    allowRelease.countDown();ack.set(waiting.await())
    assertTrue(released.get());assertTrue(ack.get());assertTrue(service.finish())
    assertEquals(if(reason=="destroy") 0 else 1,removed.get())
   } finally {allowPrepare.countDown();allowRelease.countDown();scope.cancel();pool.shutdownNow()}
  }
 }
 @Test fun startedPlaybackStopReturnsBeforeNativeRelease()=runBlocking {
  val entered=CountDownLatch(1);val release=CountDownLatch(1)
  val pool=Executors.newSingleThreadExecutor();val owner=PlaybackOwnership(dispatchCleanup={pool.execute(it)})
  owner.play({true}) {object:PlaybackOwnership.Resource {
   override fun initialize() {};override fun prepare() {};override fun start() {}
   override fun close():Boolean {entered.countDown();barrier(release);return true}
  }}
  try {
   val closed=owner.stop();barrier(entered);assertFalse(closed.isDone)
   assertFalse(CommandCleanup.await(null,{true},closed,timeoutMs=30))
   release.countDown();assertTrue(closed.get(3,TimeUnit.SECONDS))
  } finally {release.countDown();pool.shutdownNow()}
 }
 @Test fun cancelledCallerStillAwaitsCleanup()=runBlocking {
  val release=CompletableDeferred<Unit>();val entered=CompletableDeferred<Unit>();val result=CompletableDeferred<Boolean>()
  val job=launch {try {entered.complete(Unit);awaitCancellation()} finally {
   result.complete(CommandCleanup.await(null,{true},CompletableFuture<Boolean>().also {future->
    launch(NonCancellable) {release.await();future.complete(true)}
   }))
  }}
  entered.await();job.cancel();yield();assertFalse(result.isCompleted)
  release.complete(Unit);assertTrue(result.await());job.join()
 }
 @Test fun stalledOrFailedReleaseNeverAcknowledgesOrRemovesService()=runBlocking {
  val unfinished=Job();var ack=false;var removed=false
  val service=ServiceTeardown({}, {ack}, {removed=true})
  service.stop()
  ack=CommandCleanup.await(unfinished,{true},CompletableFuture.completedFuture(true),timeoutMs=30)
  assertFalse(ack);assertFalse(service.finish());assertFalse(removed);unfinished.complete()
  ack=CommandCleanup.await(null,{false},CompletableFuture.completedFuture(true))
  assertFalse(ack);assertFalse(service.finish())
  ack=CommandCleanup.await(null,{true},CompletableFuture.completedFuture(false))
  assertFalse(ack);assertFalse(service.finish());assertFalse(removed)
 }
}
