package com.serexe.sarah

import android.content.Context
import android.os.SystemClock
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Owned by the already-running microphone FGS; never starts a service or Activity. */
internal class OffscreenCommand(
 private val context:Context,
 private val deadline:ListenerWindow,
 private val active:()->Boolean,
 private val stage:(String)->Unit,
 private val finished:()->Unit
) {
 private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
 @Volatile private var capture:Capture?=null
 @Volatile private var playback:Playback?=null
 @Volatile var cleanupComplete=true; private set
 @Volatile private var stopped=false
 var rearmAllowed=false; private set
 private var running=false
 private var recording:Deferred<Unit>?=null
 private var preparing:Deferred<Unit>?=null
 private val monitor=Executors.newSingleThreadScheduledExecutor {r->Thread(r,"sarah-command-safety").apply {isDaemon=true}}
 // One monotonic command window covers capture, network, pending native prepare and playback.
 private fun eligible()=active() && deadline.valid(SystemClock.elapsedRealtime()) && AudioEligibility.allowed(context,true) && NotificationAvailability.allowed(context)
 fun start():Boolean {
  if(running || !eligible()) return false
  if(!OffscreenOwnership.acquire(this)) return false
  // Never create a conversation or restore a pending request on a wake.
  val state=runCatching {Vault(context,this).load()}.getOrNull()
  if(state==null) {OffscreenOwnership.release(this);return false}
  if(!OffscreenWakePolicy.admit(active(),eligible(),AudioArbiter.idle(),
    deadline.valid(SystemClock.elapsedRealtime()),state.optString("phase"),
    Identity.valid(state.optString("conversation")) && state.optString("origin").isNotEmpty() && state.optString("token").isNotEmpty())) {OffscreenOwnership.release(this);return false}
  running=true;cleanupComplete=false
  // No native resource exists yet. A rejected watchdog schedule must not orphan the lease.
  try {monitor.scheduleWithFixedDelay({if(!eligible()) stop()},100,100,TimeUnit.MILLISECONDS)}
  catch (_:Exception) {
   monitor.shutdownNow();running=false;cleanupComplete=true;OffscreenOwnership.release(this);return false
  }
  CommandCleanup.launchOwned(scope) {
   try {run(state)} catch (_:CancellationException) {stage("discarded")}
   catch (_:Exception) {stage("error")}
   finally {
    monitor.shutdownNow();capture?.discard()
    // Cancellation is not cleanup acknowledgment. Keep service/lease until native release returns.
    val clean=CommandCleanup.await(recording,{capture?.releaseComplete ?: true},
     playback?.stopAcknowledgement() ?: java.util.concurrent.CompletableFuture.completedFuture(true),preparing=preparing)
    if(clean) {
     rearmAllowed=!stopped && eligible() && OffscreenWakePolicy.resolved(state.optString("phase"))
     capture=null;recording=null;playback=null;running=false;cleanupComplete=true;OffscreenOwnership.release(this@OffscreenCommand);finished()
    }
    else stage("cleanup-failed")
   }
  }
  return true
 }
 fun stop() { stopped=true;scope.cancel();capture?.discard();playback?.stop() }
 private suspend fun run(state:JSONObject) {
  if(!eligible()) return
  val vault=Vault(context,this)
  val c=Capture(context,{scope.launch {stage("interrupted");stop()} },true)
  c.eligibility={eligible()}
  c.onMicReady={cue->scope.launch {
   if(eligible()) stage(if(cue==MicReadyCueGate.Result.OUTPUT_MUTED) "recording-media-muted" else "recording")
  }}
  capture=c;stage("starting-command-mic")
  val job=scope.async(Dispatchers.IO,start=CoroutineStart.LAZY) {c.record()}
  recording=job;job.start()
  // Capture remains bounded even if Activity vanishes or screen turns off.
  // Native endpoint uses recorded activity and within-command pauses; cap discards.
  // Capture's independent 30-second PCM/clock cap discards an unended command.
  try {withTimeout(31_000L) {job.await()}}
  catch (_:Exception) {c.discard();job.cancel();throw CancellationException("capture endpoint failed")}
  c.stop()
  check(c.releaseComplete) {"capture release failed"}
  if(!eligible() || c.capped || !c.endpointReached || !c.speechDetected) {stage("discarded");return}
  val wav=try {c.finish()} catch (_:Exception) {stage("discarded");return}
  c.discard();capture=null
  if(!eligible()) return
  val conversation=state.getString("conversation")
  val request=Identity.new()
  // Persist request identity and uncertain outcome before network bytes leave process.
  state.put("request",request).put("turn","").put("phase","uncertain")
   .put("fingerprint",MessageDigest.getInstance("SHA-256").digest(wav).joinToString("") {"%02x".format(it)})
  vault.save(state)
  if(!eligible()) return
  val bridge=Bridge(state.getString("origin"),state.getString("token"),state.optString("ca","").takeIf {it.isNotEmpty()}?.let {android.util.Base64.decode(it,android.util.Base64.DEFAULT)})
  stage("uploading")
  if(!eligible()) return
  val turn=bridge.submitCancellable(conversation,request,wav)
  if(!eligible()) return
  state.put("turn",turn);vault.save(state);stage("polling")
  var delayMs=1500L
  repeat(30) {
   if(!eligible()) return
   val row=bridge.pollCancellable(turn)
   if(!eligible()) return
   if(row.optString("id")!=turn || row.optString("conversation")!=conversation) {stage("uncertain");return}
   when(row.optString("state")) {
    "done" -> {
     // Same encrypted local conversation, no notification text or logs.
     val transcript=row.optString("transcript").take(8000)
     val detail=row.optString("detail").take(8000)
     val messages=state.optJSONArray("messages") ?: JSONArray()
     if(transcript.isNotBlank() && state.optString("shownTranscript")!=request) {messages.put(JSONObject().put("who","YOU").put("text",transcript.take(3000)).put("time",System.currentTimeMillis()));state.put("shownTranscript",request)}
     if(state.optString("shownReply")!=request) {messages.put(JSONObject().put("who","S.A.R.A.H").put("text",detail.take(3000)).put("time",System.currentTimeMillis()));state.put("shownReply",request)}
     val kept=JSONArray();val cutoff=System.currentTimeMillis()-30L*24*60*60*1000
     for(i in maxOf(0,messages.length()-100) until messages.length()) {
      val message=messages.optJSONObject(i) ?: continue
      if(message.optLong("time")>=cutoff) kept.put(message)
     }
     state.put("messages",kept).put("phase","done");vault.save(state)
     if(row.optBoolean("audio") && eligible()) {
      val bytes=bridge.audioCancellable(turn)
      if(!eligible()) return
      val done=CompletableDeferred<Boolean>()
      val p=Playback(context) {done.complete(it)}
      p.eligibility={scope.isActive && eligible()}
      playback=p
      currentCoroutineContext().ensureActive()
      // Native prepare may block; never run it on the service/main dispatcher.
      val prepare=scope.async(Dispatchers.IO,start=CoroutineStart.LAZY) {p.play(bytes)}
      preparing=prepare;prepare.start();prepare.await()
      currentCoroutineContext().ensureActive()
      if(!eligible()) return
      stage("speaking")
      // Preserve a per-command playback cap even when listener opt-in has no expiry.
      if(!withTimeout(120_000L) {done.await()}) {stage("interrupted");return}
     }
     stage("done");return
    }
    "confirming" -> {state.put("phase","uncertain");vault.save(state);stage("confirmation-required");return}
    "error","cancelled","uncertain" -> {state.put("phase",row.optString("state"));vault.save(state);stage(row.optString("state"));return}
    "transcribing","thinking","acting","speaking" -> stage("polling")
    else -> {stage("uncertain");return}
   }
   delay(delayMs);delayMs=minOf(delayMs+500,5000)
  }
  stage("uncertain")
 }
}
