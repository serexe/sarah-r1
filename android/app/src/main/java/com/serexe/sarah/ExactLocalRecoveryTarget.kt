package com.serexe.sarah

import org.json.JSONObject
import java.security.MessageDigest

/** One explicitly approved candidate, not a general "forget uncertain request" escape hatch. */
internal class ExactLocalRecoveryTarget(private val requestHash:String,private val conversationHash:String) {
 private fun identity(state:JSONObject,key:String,length:Int,expected:String):Boolean {
  val value=state.opt(key) as? String ?: return false
  if(!expected.matches(Regex("[0-9a-f]{12}")) || value.length!=length || !Identity.valid(value)) return false
  val actual=MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") {"%02x".format(it)}.take(12)
  return actual==expected
 }
 fun matches(state:JSONObject):Boolean = state.opt("phase")=="uncertain" &&
  identity(state,"request",36,requestHash) && identity(state,"conversation",32,conversationHash) &&
  state.opt("turn")=="" && state.opt("audioNext")==0 && state.opt("chunkInFlight")==false &&
  state.opt("requestHttp")==403 && state.opt("requestServerError")=="not_found"
 companion object {
  fun installed()=ExactLocalRecoveryTarget(BuildConfig.RECOVERY_REQUEST_HASH,BuildConfig.RECOVERY_CONVERSATION_HASH)
 }
}
