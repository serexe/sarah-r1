package com.serexe.sarah

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LegacyWakeEligibilityTest {
 @Test fun explicitForegroundConsentCanUseLegacyMicWithoutAssistantRole() {
  assertTrue(AssistantWakePolicy.roleSatisfied(27,false))
  assertTrue(AssistantWakePolicy.roleSatisfied(28,false))
  assertFalse(AssistantWakePolicy.roleSatisfied(29,false))
  assertTrue(AssistantWakePolicy.roleSatisfied(29,true))
  assertFalse(AssistantWakePolicy.roleSatisfied(35,false))
 }
}
