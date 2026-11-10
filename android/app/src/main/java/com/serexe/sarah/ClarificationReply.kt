package com.serexe.sarah

import org.json.JSONObject

/** Exact terminal owner-bound server intent, never answer punctuation or recovery lookup. */
internal object ClarificationReply {
 fun valid(row:JSONObject,conversation:String,turn:String,request:String,savedRequest:String):Boolean =
  Identity.valid(conversation) && Identity.valid(turn) && Identity.valid(request) &&
   request==savedRequest && row.optString("id")==turn && row.optString("conversation")==conversation &&
   row.optString("state")=="done" && row.has("reply_expected") &&
   row.opt("reply_expected") is Boolean && row.getBoolean("reply_expected") && row.optJSONObject("confirmation")==null &&
   row.optJSONObject("phone_action")==null
}
