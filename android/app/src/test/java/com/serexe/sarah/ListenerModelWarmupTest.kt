package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class ListenerModelWarmupTest {
 private class Model(private val closes:AtomicInteger):AutoCloseable {
  override fun close() {closes.incrementAndGet()}
 }
 private fun await(latch:CountDownLatch) {assertTrue(latch.await(3,TimeUnit.SECONDS))}

 @Test fun preconstructedModelTransfersExactlyOnceWithoutPrematureClose() {
  val closes=AtomicInteger();val done=CountDownLatch(1)
  val warm=ListenerModelWarmup({Model(closes)}) {done.countDown()}
  assertTrue(warm.start());await(done)
  assertTrue(warm.complete)
  val owner=warm.take();assertNotNull(owner);assertNull(warm.take())
  warm.cancel();assertEquals(0,closes.get()) // listener finally now owns model
  owner!!.close();assertEquals(1,closes.get())
 }
 @Test fun stopDuringNativeConstructionWaitsForRealCloseAndBlocksTake() {
  val entered=CountDownLatch(1);val release=CountDownLatch(1);val done=CountDownLatch(1)
  val closes=AtomicInteger()
  val warm=ListenerModelWarmup({entered.countDown();await(release);Model(closes)}) {done.countDown()}
  assertTrue(warm.start());await(entered)
  warm.cancel();assertFalse(warm.complete)
  release.countDown();await(done)
  assertTrue(warm.complete);assertNull(warm.take());assertEquals(1,closes.get())
 }
 @Test fun stopAfterConstructionClosesUnusedModelAndFailureNeverAcknowledgesUnknownNative() {
  val closes=AtomicInteger();val done=CountDownLatch(1)
  val warm=ListenerModelWarmup({Model(closes)}) {done.countDown()}
  assertTrue(warm.start());await(done);warm.cancel();warm.cancel()
  assertTrue(warm.complete);assertNull(warm.take());assertEquals(1,closes.get())
  val failed=CountDownLatch(1)
  val unknown=ListenerModelWarmup<Model>({throw IllegalStateException("native constructor failed")}) {failed.countDown()}
  assertTrue(unknown.start());await(failed);unknown.cancel()
  assertFalse(unknown.complete);assertNull(unknown.take())
 }
 @Test fun stopCannotReportCleanupAckWhileUnusedNativeCloseIsPendingOrFailed() {
  val entered=CountDownLatch(1);val release=CountDownLatch(1);val constructed=CountDownLatch(1)
  val warm=ListenerModelWarmup<AutoCloseable>({AutoCloseable {
   entered.countDown();await(release);throw IllegalStateException("native close failed")
  }}) {constructed.countDown()}
  assertTrue(warm.start());await(constructed)
  val stopper=Thread {warm.cancel()};stopper.start();await(entered)
  assertFalse(warm.complete)
  release.countDown();stopper.join(3000)
  assertFalse(stopper.isAlive);assertFalse(warm.complete);assertNull(warm.take())
 }
}
