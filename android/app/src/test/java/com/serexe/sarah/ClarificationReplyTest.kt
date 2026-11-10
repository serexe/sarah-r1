package com.serexe.sarah

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ClarificationReplyTest {
 private val conversation="abc123"
 private val turn="def456"
 private val request="ghi789"
 private fun row():JSONObject=JSONObject().put("id",turn).put("conversation",conversation)
  .put("state","done").put("reply_expected",true)
  .put("timings",JSONObject().put("route","model"))
 private fun valid(row:JSONObject)=ClarificationReply.valid(row,conversation,turn,request,request)
 @Test fun exactExplicitTerminalMarkerOnly() {
  assertTrue(valid(row()))
  assertFalse(valid(row().put("reply_expected",false)))
  assertFalse(valid(row().apply {remove("reply_expected")}))
  assertFalse(valid(row().put("reply_expected","true")))
  assertFalse(valid(row().put("state","speaking")))
  assertFalse(valid(row().put("state","confirming")))
  assertFalse(valid(row().put("state","uncertain")))
  assertFalse(valid(row().put("id","wrong")))
  assertFalse(valid(row().put("conversation","foreign")))
  assertFalse(ClarificationReply.valid(row(),conversation,turn,request,"other"))
  assertFalse(valid(row().put("confirmation",JSONObject().put("nonce","x"))))
  assertFalse(valid(row().put("phone_action",JSONObject().put("action","create"))))
  assertTrue(valid(row().apply {remove("timings")})) // metrics may publish after terminal done
 }
}
