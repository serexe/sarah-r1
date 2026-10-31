package com.serexe.sarah

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class RequestDiagnosticsTest {
 @Test fun exactAllowlistOnly() {
  for(code in listOf("unauthorized","not_found","invalid_identifier")) assertEquals(code,RequestDiagnostics.serverError(code))
  for(raw in listOf("", "other", "Unauthorized", "not_found\nsecret", "https://private.invalid/token", "none")) assertEquals("other",RequestDiagnostics.serverError(raw))
  assertEquals("none",RequestDiagnostics.savedServerError(JSONObject()))
  assertEquals("other",RequestDiagnostics.savedServerError(JSONObject().put("requestServerError","private-body")))
 }
 @Test fun maskedHashUsesExactSavedUtf8AndDistinguishesAbsentEmpty() {
  val state=JSONObject().put("request","abc").put("turn","")
  assertEquals("savedRequest present=true length=3 sha256=ba7816bf8f01",RequestDiagnostics.masked(state,"request","savedRequest"))
  assertEquals("savedTurn present=true length=0 sha256=e3b0c44298fc",RequestDiagnostics.masked(state,"turn","savedTurn"))
  assertEquals("savedConversation present=false length=0 sha256=absent",RequestDiagnostics.masked(state,"conversation","savedConversation"))
  state.put("request"," abc ")
  assertFalse(RequestDiagnostics.masked(state,"request","savedRequest").contains("ba7816bf8f01"))
  assertFalse(RequestDiagnostics.masked(state,"request","savedRequest").contains(" abc "))
 }
}
