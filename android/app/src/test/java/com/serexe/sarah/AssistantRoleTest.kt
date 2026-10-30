package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class AssistantRoleTest {
 @Test fun roleStatusMakesManualFallbackExplicit() {
  assertTrue(assistantRoleStatus(false,false).contains("Tap to talk"))
  assertTrue(assistantRoleStatus(true,false).contains("Not the default"))
  assertTrue(assistantRoleStatus(true,false).contains("Tap to talk"))
  assertTrue(assistantRoleStatus(true,true).contains("default assistant"))
 }
}
