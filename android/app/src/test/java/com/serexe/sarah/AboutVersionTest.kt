package com.serexe.sarah

import org.junit.Assert.assertEquals
import org.junit.Test

class AboutVersionTest {
 @Test fun includesInstalledNameAndLongBuildCode() {
  assertEquals("0.1.16-about-review (build 17)",formatInstalledVersion("0.1.16-about-review",17L))
  assertEquals("2.0 (build 2147483648)",formatInstalledVersion("2.0",2147483648L))
 }

 @Test fun absentNameIsExplicitNotStale() {
  assertEquals("Unknown (build 9)",formatInstalledVersion(null,9L))
  assertEquals("Unknown (build 9)",formatInstalledVersion("  ",9L))
 }
}
