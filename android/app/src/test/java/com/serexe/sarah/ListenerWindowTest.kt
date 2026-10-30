package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.io.File

class ListenerWindowTest {
 @Test fun persistentOptInHasNoTwoMinuteExpiryButRejectsPreStartClock() {
  val window=ListenerWindow(1000,persistent=true)
  assertFalse(window.valid(999));assertTrue(window.valid(1000));assertTrue(window.valid(121000))
  assertTrue(window.valid(86_401_000))
 }
 @Test fun productionTaskRemovalKeepsStartedMicrophoneOwnerAndExplicitStop() {
  val manifest=File("src/main/AndroidManifest.xml").readText()
  assertFalse(manifest.contains("android:stopWithTask=\"true\""))
  val service=File("src/main/java/com/serexe/sarah/HeySarahListenerService.kt").readText()
  assertFalse(service.contains("onTaskRemoved(rootIntent:Intent?) {stop(this)"))
  assertTrue(service.contains("if(intent?.action==STOP) {stop(this)"))
  assertTrue(service.contains("instance?.requestStop()"))
  assertTrue(service.contains("listenerCleanup.complete && session.released"))
  assertTrue(service.contains("ListenerWindow(optedStart,persistent=true)"))
  assertFalse(service.contains("main.postDelayed(cutoff"))
 }
 @Test fun lockedWakeDoesNotRecordCommandOrConsumePersistentOptIn() {
  val service=File("src/main/java/com/serexe/sarah/HeySarahListenerService.kt").readText()
  val locked=service.substringAfter("} else {\n    stage(\"locked\")").substringBefore("}, {worker=null")
  assertTrue(locked.contains("notifyWake()"))
  assertTrue(locked.contains("isDeviceLocked"))
  assertTrue(locked.contains("rearmAfterCommand()"))
  assertFalse(locked.contains("owner.start()"))
 }
 @Test fun initializationConsumesSameTwoMinuteBudget() {
  val window=ListenerWindow(1000)
  assertTrue(window.valid(1000));assertTrue(window.valid(120999))
  assertFalse(window.valid(121000));assertFalse(window.valid(121001));assertFalse(window.valid(999))
 }
 @Test fun offscreenHitNotifiesOnlyAfterReleaseAck() {
  val session=ListenerSession();val window=ListenerWindow(0);val events=mutableListOf<String>()
  session.gate.start(true);session.gate.hit()
  session.releaseAfter({events.add("recorder-native-release");true},{window.valid(119999)},{assertTrue(session.released);events.add("tap-unlock-notification")})
  assertEquals(listOf("recorder-native-release","tap-unlock-notification"),events)
  assertFalse(session.gate.hit());assertFalse(session.gate.listening(true))
 }
 @Test fun expiredWindowDropsQueuedWake() {
  val session=ListenerSession();val window=ListenerWindow(0)
  session.gate.start(true);session.gate.hit()
  session.releaseAfter({true}, {window.valid(120000)},{fail("expired notification")})
  assertTrue(session.released)
 }
 @Test fun notificationStopCancelsQueuedOffscreenHit() {
  val session=ListenerSession();session.gate.start(true);session.gate.hit()
  session.cancelBefore {session.releaseAfter({true}, {true},{fail("stale notification")})}
  assertTrue(session.released)
 }
}
