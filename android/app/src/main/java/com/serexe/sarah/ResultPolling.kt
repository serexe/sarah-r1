package com.serexe.sarah

import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** One shared device poll gate across foreground/offscreen owners and turns.
 * At most 60 starts in any inclusive 60s window (1001ms spacing), leaving 30
 * requests for submit/audio/health/cancel under the unchanged 90/min guard.
 * No retries on HTTP failures. Cancellation releases the gate, sends nothing.
 */
internal object ResultPolling {
 private val gate=Mutex()
 private var lastStart=0L
 fun delayMs(attempt:Int):Long=if(attempt<=10) 1001L else minOf(1001L+(attempt-10)*250L,5000L)
 suspend fun awaitSlot()=gate.withLock {
  val now=System.nanoTime()
  val remaining=1001L-(now-lastStart)/1_000_000L
  if(lastStart!=0L && remaining>0) delay(remaining)
  lastStart=System.nanoTime()
 }
}

/** Monotonic, local numeric metadata only; endpoint != actual end of speech. */
internal class ResponseTiming {
 private val start=System.nanoTime()
 private val values=org.json.JSONObject()
 fun mark(name:String) {values.put(name,(System.nanoTime()-start)/1_000_000L)}
 fun snapshot(server:org.json.JSONObject?=null):org.json.JSONObject {
  val copy=org.json.JSONObject(values.toString())
  // Explicit numeric allowlist; never retain server text, IDs, URLs or errors.
  if(server!=null) for(k in listOf("upload_read_ms","queue_ms","stt_ms","reply_ms","model_ms","tts_ms","server_ms")) {
   val v=server.optDouble(k,Double.NaN)
   if(v.isFinite() && v>=0) copy.put("server_$k",v)
  }
  return copy
 }
}
