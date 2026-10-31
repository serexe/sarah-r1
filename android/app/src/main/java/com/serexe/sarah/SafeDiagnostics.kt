package com.serexe.sarah

import java.security.MessageDigest
import org.json.JSONObject

/** Separate strict wire/share allowlist. Never serializes the local diagnostic blob. */
internal object SafeDiagnostics {
 val phases=setOf("disconnected","ready","done","error","cancelled","uncertain","recording","finalizing","uploading","polling","playing","reply_audio_pending","confirming","creating","cancelling","other")
 fun payload(state:JSONObject,phase:String,version:Long):JSONObject {
  val out=JSONObject().put("schema",1).put("appVersion",version.coerceIn(1,999999))
   .put("phase",phase.takeIf {it in phases} ?: "other")
   .put("serverError",RequestDiagnostics.savedServerError(state))
   .put("httpStatus",state.optInt("requestHttp",0).let {if(it==0 || it in 100..599) it else 0})
   .put("audioNext",state.optInt("audioNext",0).coerceIn(0,32)).put("chunkInFlight",state.optBoolean("chunkInFlight"))
  for(key in listOf("request","turn","conversation")) {
   val present=state.has(key) && !state.isNull(key);val value=if(present) state.optString(key) else ""
   val hash=if(present) MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") {"%02x".format(it)}.take(12) else ""
   out.put(key+"Present",present).put(key+"Length",value.length.coerceAtMost(65535)).put(key+"Hash",hash)
  }
  return out
 }
 fun share(payload:JSONObject):String="SARAH sanitized diagnostics (not a recovery action)\n"+payload.toString(2)
 fun receipt(value:String):String {require(Regex("[A-F0-9]{24}").matches(value));return value}
}
