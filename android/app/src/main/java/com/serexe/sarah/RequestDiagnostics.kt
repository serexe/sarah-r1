package com.serexe.sarah

import java.security.MessageDigest
import org.json.JSONObject

/** Explicit local capture only: fixed server codes and one-way saved identity metadata. */
internal object RequestDiagnostics {
 private val serverCodes=setOf("unauthorized","not_found","invalid_identifier")
 fun serverError(reason:String):String=reason.takeIf {it in serverCodes} ?: "other"
 fun savedServerError(state:JSONObject):String = if(!state.has("requestServerError") || state.optString("requestServerError")=="none") "none" else serverError(state.optString("requestServerError"))
 fun masked(state:JSONObject,key:String,label:String):String {
  val present=state.has(key) && !state.isNull(key)
  val value=if(present) state.optString(key) else ""
  val hash=if(present) MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") {"%02x".format(it)}.take(12) else "absent"
  return "$label present=$present length=${value.length} sha256=$hash"
 }
}
