package com.serexe.sarah
import org.junit.Assert.*
import org.junit.Test
class ResultPollingTest {
 @Test fun boundedBudgetAndFasterFirstIntervals() {
  assertEquals(1001L,ResultPolling.delayMs(1))
  assertEquals(1001L,ResultPolling.delayMs(10))
  assertEquals(1251L,ResultPolling.delayMs(11))
  assertEquals(5000L,ResultPolling.delayMs(100))
  assertTrue(60_000L/1001L+1<=60L)
  for(i in 1..200) assertTrue(ResultPolling.delayMs(i) in 1001L..5000L)
 }
 @Test fun numericTimingAllowlist() {
  val t=ResponseTiming();t.mark("done_observed_ms")
  val input=org.json.JSONObject().put("stt_ms",12.5).put("detail","private").put("tts_ms","NaN")
  val out=t.snapshot(input)
  assertEquals(12.5,out.getDouble("server_stt_ms"),0.0)
  assertFalse(out.has("detail"));assertFalse(out.has("server_tts_ms"))
  assertTrue(out.getLong("done_observed_ms")>=0)
 }
}
