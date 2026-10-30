package com.serexe.sarah
import org.junit.Assert.*
import org.junit.Test

class ListenerGateTest {
 @Test fun noImplicitStartOrUnsafeOptIn() {
  val g=ListenerGate();assertFalse(g.listening(true));assertFalse(g.hit());assertFalse(g.released())
  assertFalse(g.start(false));assertFalse(g.listening(true))
 }
 @Test fun oneHitRequiresExplicitRearmAfterRelease() {
  val g=ListenerGate();assertTrue(g.start(true));assertFalse(g.start(true));assertTrue(g.listening(true))
  assertTrue(g.hit());assertFalse(g.hit());assertFalse(g.listening(true));assertTrue(g.released())
  assertFalse(g.listening(true));assertFalse(g.released());assertTrue(g.start(true))
 }
 @Test fun stopAndLateCallbackNeverWake() {
  val g=ListenerGate();g.start(true);g.hit();g.stop();assertFalse(g.released());assertFalse(g.hit())
 }
 @Test fun unsafePermissionRoleCallPrivacyTtsBackgroundFailClosed() {
  repeat(6) {val g=ListenerGate();g.start(true);assertFalse(g.listening(false));assertFalse(g.listening(true));assertFalse(g.hit());assertFalse(g.released())}
 }
 @Test fun unsafeAfterHitCancelsBeforeRelease() {
  val g=ListenerGate();g.start(true);g.hit();assertFalse(g.listening(false));assertFalse(g.released())
 }
}
