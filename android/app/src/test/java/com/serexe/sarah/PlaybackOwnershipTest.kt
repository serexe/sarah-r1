package com.serexe.sarah

import android.app.NotificationManager
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/** Exercises the SAME initialize/prepare/start/cleanup orchestrator used by Playback.
 * Only Android resource calls are replaced, allowing deterministic cross-thread barriers.
 * Not a MediaPlayer/OS integration test.
 */
class PlaybackOwnershipTest {
 private class Resource(val duringPrepare:()->Unit={},val duringClose:()->Unit={}):PlaybackOwnership.Resource {
  val initialized=AtomicInteger();val starts=AtomicInteger();val closes=AtomicInteger()
  override fun initialize() {initialized.incrementAndGet()}
  override fun prepare() {duringPrepare()}
  override fun start() {starts.incrementAndGet()}
  override fun close():Boolean {duringClose();closes.incrementAndGet();return true}
 }
 private fun await(latch:CountDownLatch) {check(latch.await(3,TimeUnit.SECONDS)) {"barrier timeout"}}
 private fun race(beforeInit:Boolean,reason:String,stop:Boolean=true) {
  val paused=CountDownLatch(1);val resume=CountDownLatch(1)
  val permission=AtomicBoolean(true);val unlocked=AtomicBoolean(true);val active=AtomicBoolean(true)
  val barrier={paused.countDown();await(resume)}
  val owner=PlaybackOwnership(if(beforeInit) barrier else ({}))
  val resource=Resource(if(!beforeInit) barrier else ({}))
  val eligible={active.get() && unlocked.get() && NotificationAvailability.evaluate(permission.get(),true,NotificationManager.IMPORTANCE_LOW)}
  val pool=Executors.newFixedThreadPool(2)
  try {
   val play=pool.submit<Boolean> {owner.play(eligible) {resource}}
   await(paused)
   when(reason) {"notification"->permission.set(false);"lock"->unlocked.set(false);"cancel"->active.set(false)}
   val ack=if(stop) pool.submit<CompletableFuture<Boolean>> {owner.stop()}.get(1,TimeUnit.SECONDS) else null
   if(ack!=null) assertFalse("Stop must invalidate now, but ACK waits for preparation cleanup",ack.isDone)
   resume.countDown()
   assertFalse(play.get(3,TimeUnit.SECONDS))
   assertTrue((ack ?: owner.stop()).get(3,TimeUnit.SECONDS))
   assertEquals(0,resource.starts.get())
   assertEquals(if(beforeInit) 0 else 1,resource.initialized.get())
   assertEquals(if(beforeInit) 0 else 1,resource.closes.get())
  } finally {resume.countDown();pool.shutdownNow();assertTrue(pool.awaitTermination(3,TimeUnit.SECONDS))}
 }
 @Test fun stopBeforeInitialization()=race(true,"stop")
 @Test fun notificationDenialBeforeInitialization()=race(true,"notification")
 @Test fun lockBeforeInitialization()=race(true,"lock")
 @Test fun stopDuringPrepare()=race(false,"stop")
 @Test fun notificationDenialDuringPrepare()=race(false,"notification")
 @Test fun lockDuringPrepare()=race(false,"lock")
 @Test fun cancellationAloneAfterPrepareRejectsStart()=race(false,"cancel",false)
 @Test fun notificationRecheckWithoutMonitorRejectsStart()=race(false,"notification",false)
 @Test fun lockRecheckWithoutMonitorRejectsStart()=race(false,"lock",false)
 @Test fun cleanupAckWaitsForReleaseNotOnlyStop() {
  val paused=CountDownLatch(1);val resume=CountDownLatch(1)
  val owner=PlaybackOwnership();val resource=Resource(duringClose={paused.countDown();await(resume)})
  assertTrue(owner.play({true}) {resource})
  val pool=Executors.newSingleThreadExecutor()
  try {
   val stop=pool.submit<CompletableFuture<Boolean>> {owner.stop()}
   await(paused)
   val ack=owner.stop()
   assertFalse(ack.isDone)
   resume.countDown()
   assertTrue(stop.get(3,TimeUnit.SECONDS).get(3,TimeUnit.SECONDS))
   assertTrue(ack.get(3,TimeUnit.SECONDS));assertEquals(1,resource.closes.get())
  } finally {resume.countDown();pool.shutdownNow();pool.awaitTermination(3,TimeUnit.SECONDS)}
 }
 @Test fun partialInitializationExceptionReclaimsLocalResource() {
  val closed=AtomicBoolean(false);val owner=PlaybackOwnership()
  assertThrows(IllegalStateException::class.java) {
   owner.play({true}) {object:PlaybackOwnership.Resource {
    override fun initialize() {error("synthetic initialization failure")}
    override fun prepare() {fail("must not prepare")}
    override fun start() {fail("must not start")}
    override fun close():Boolean {closed.set(true);return true}
   }}
  }
  assertTrue(closed.get());assertTrue(owner.stop().get())
 }
 @Test fun failedReleaseNeverAcknowledgesSuccess() {
  val owner=PlaybackOwnership()
  owner.play({true}) {object:PlaybackOwnership.Resource {
   override fun initialize() {}
   override fun prepare() {}
   override fun start() {}
   override fun close()=false
  }}
  assertFalse(owner.stop().get());assertFalse(owner.stop().get())
 }
 @Test fun foregroundReuseAndStaleCallbackKeepNewOwner() {
  val owner=PlaybackOwnership();val first=Resource();val second=Resource();var firstId=0L
  assertTrue(owner.play({true}) {firstId=it;first})
  assertTrue(owner.play({true}) {second})
  assertEquals(1,first.closes.get())
  owner.finish(firstId,true) {fail("stale callback")}
  assertEquals(0,second.closes.get())
  assertTrue(owner.stop().get());assertEquals(1,second.closes.get())
  val third=Resource();assertTrue(owner.play({true}) {third});assertTrue(owner.stop().get())
 }
 @Test fun completionCallbackRunsOnlyAfterCleanup() {
  val owner=PlaybackOwnership();val resource=Resource();var id=0L;var called=false
  owner.play({true}) {id=it;resource}
  owner.finish(id,true) {assertTrue(it);assertEquals(1,resource.closes.get());called=true}
  assertTrue(called)
 }
}
