package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class OffscreenWakePolicyTest {
 @Test fun unlockedExistingWindowMayAdmitOnlyIdlePairedReadyState() {
  assertTrue(OffscreenWakePolicy.admit(true,true,true,true,"ready",true))
  for(index in listOf(0,1,2,3,5)) {
   val flags=booleanArrayOf(true,true,true,true,true,true);flags[index]=false
   assertFalse(OffscreenWakePolicy.admit(flags[0],flags[1],flags[2],flags[3],"ready",flags[5]))
  }
  for(phase in listOf("uncertain","uploading","polling","confirming","recording","disconnected"))
   assertFalse(OffscreenWakePolicy.admit(true,true,true,true,phase,true))
 }
 @Test fun oneWakeCannotReplayAfterStopOrRelease() {
  val gate=ListenerGate()
  assertTrue(gate.start(true));assertTrue(gate.hit());assertTrue(gate.released())
  assertFalse(gate.released());assertFalse(gate.hit())
  assertTrue(gate.start(true));assertTrue(gate.hit());gate.stop();assertFalse(gate.released())
 }
}
