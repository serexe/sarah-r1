package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/** Fake native operation exercises the exact ownership boundary called by both production recorders. */
class NativeStartOwnershipTest {
 private fun pendingStop(cancel:(NativeStartOwnership)->Unit) {
  val poised=CountDownLatch(1);val release=CountDownLatch(1)
  val starts=AtomicInteger();val sends=AtomicInteger();val rearms=AtomicInteger()
  val failure=AtomicReference<Throwable?>()
  val owner=NativeStartOwnership(beforeNativeStart={
   poised.countDown()
   check(release.await(3,TimeUnit.SECONDS)) {"test pause timed out"}
  })
  val worker=Thread {
   try { if(owner.start({true}) {starts.incrementAndGet()}) { sends.incrementAndGet();rearms.incrementAndGet() } }
   catch(e:Throwable) {failure.set(e)}
  }
  worker.start()
  try {
   assertTrue("worker did not reach pre-native boundary",poised.await(3,TimeUnit.SECONDS))
   cancel(owner) // must finish before native start becomes possible
  } finally {release.countDown();worker.join(3000)}
  assertFalse("worker stuck",worker.isAlive)
  failure.get()?.let {throw AssertionError("worker failed",it)}
  assertEquals("late native start",0,starts.get())
  assertEquals("no command send",0,sends.get())
  assertEquals("no listener rearm",0,rearms.get())
 }
 @Test fun discardStopsPendingCommandNativeStart() = pendingStop {it.cancel()}
 @Test fun backgroundStopsPendingCommandNativeStart() = pendingStop {it.cancel()}
 @Test fun listenerStopInvalidatesGateBeforePendingWakeNativeStart() {
  val poised=CountDownLatch(1);val release=CountDownLatch(1);val starts=AtomicInteger();val dispatched=AtomicInteger()
  val session=ListenerSession(beforeNativeStart={poised.countDown();check(release.await(3,TimeUnit.SECONDS))})
  assertTrue(session.gate.start(true))
  // The service's session owns the same production native-start boundary.
  val worker=Thread {
   if(session.nativeStart.start({session.gate.listening(true)}) {starts.incrementAndGet()}) session.gate.hit()
   session.releaseAfter({true}, {true}, {dispatched.incrementAndGet()})
  }
  worker.start()
  try {assertTrue(poised.await(3,TimeUnit.SECONDS));session.cancelBefore {} }
  finally {release.countDown();worker.join(3000)}
  assertFalse(worker.isAlive);assertTrue(session.released);assertEquals(0,starts.get());assertEquals(0,dispatched.get());assertFalse(session.gate.listening(true))
 }
 @Test fun focusLossCallbackReturnsBeforePendingWakeNativeStart() {
  val poised=CountDownLatch(1);val release=CountDownLatch(1);val callbackReturned=CountDownLatch(1)
  val starts=AtomicInteger();val failure=AtomicReference<Throwable?>()
  // Pause after production eligibility check, immediately before native operation.
  val session=ListenerSession(beforeNativeOperation={poised.countDown();check(release.await(3,TimeUnit.SECONDS))})
  assertTrue(session.gate.start(true))
  val worker=Thread {
   try {session.nativeStart.start({session.gate.listening(true)}) {starts.incrementAndGet()}}
   catch(e:Throwable) {failure.set(e)}
  }
  worker.start()
  val releaser=Thread {callbackReturned.await(300,TimeUnit.MILLISECONDS);release.countDown()}
  try {
   assertTrue("worker did not reach pending native start",poised.await(3,TimeUnit.SECONDS))
   releaser.start()
   session.onAudioFocusChange(-1) // exact production callback path
   val startsAtCallbackReturn=starts.get()
   callbackReturned.countDown()
   worker.join(3000)
   assertFalse("native start happened after focus callback returned",starts.get()!=startsAtCallbackReturn)
   assertFalse(session.gate.listening(true))
  } finally {release.countDown();callbackReturned.countDown();releaser.join(3000);worker.join(3000)}
  assertFalse("worker stuck",worker.isAlive)
  failure.get()?.let {throw AssertionError("worker failed",it)}
 }
}
