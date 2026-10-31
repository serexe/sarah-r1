package com.serexe.sarah

import android.app.Application
import androidx.lifecycle.AndroidViewModel

import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collect
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicLong

/** One owner; no WorkManager, background submit, polling, or capture resurrection. */
class SarahViewModel internal constructor(app:Application,private val vault:StateStore,
 private val bridgeFactory:(String,String,ByteArray?)->BridgePort,
 private val captureFactory:(()->Unit)->AudioCapture,
 playbackFactory:((Boolean)->Unit)->AudioPlayback,
 private val scope:CoroutineScope,
 private val io:kotlin.coroutines.CoroutineContext,
 private val commandEligible:(Boolean)->Boolean={true},
 private val beforePlayback:suspend ()->Unit={},
 private val rearmListener:()->Unit={},
 private val abortWindow:()->Unit={},
 private val awaitPollSlot:suspend ()->Unit={ResultPolling.awaitSlot()},
 private val localRecoveryTarget:ExactLocalRecoveryTarget=ExactLocalRecoveryTarget.installed()):AndroidViewModel(app) {
 constructor(app:Application):this(app,Vault(app),{url,token,ca->Bridge(url,token,ca)},{interrupted->Capture(app,interrupted,true)},{done->Playback(app,done)},CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate),Dispatchers.IO,{wake->AudioEligibility.allowed(app,wake)},{HeySarahListenerService.awaitIdle()},{HeySarahListenerService.start(app,true,true)},{HeySarahListenerService.stop(app)})
 data class Ui(val phase:String="disconnected",val status:String="Set up HTTPS bridge",val conversation:String?=null,val transcript:List<Pair<String,String>> = emptyList(),val hasConfig:Boolean=false,val confirmation:JSONObject?=null,val canCapture:Boolean=false)
 private val generation=AtomicLong()
 private val _ui=MutableStateFlow(Ui());val ui=_ui.asStateFlow()
 private var state=JSONObject()
 private val _diagnosticDelivery=MutableStateFlow("Not sent");val diagnosticDelivery=_diagnosticDelivery.asStateFlow()
 private var diagnosticSending=false
 internal fun safeDiagnosticPayload(version:Long)=SafeDiagnostics.payload(state,_ui.value.phase,version)
 internal fun shareDiagnostics(version:Long)=SafeDiagnostics.share(safeDiagnosticPayload(version))
 internal fun sendDiagnostics(version:Long) {
  if(diagnosticSending) return
  val wire=bridge ?: run {_diagnosticDelivery.value="No bridge configured; use Share diagnostics";return}
  val payload=safeDiagnosticPayload(version)
  diagnosticSending=true;_diagnosticDelivery.value="Sending sanitized diagnostics…"
  scope.launch {
   try {val code=withContext(io) {SafeDiagnostics.receipt(wire.sendDiagnostics(payload))};_diagnosticDelivery.value="Sent · report code $code"}
   catch(e:Exception) {_diagnosticDelivery.value=when {
    e is Bridge.Failure && e.status==403 -> "Not sent: authentication denied; use Share diagnostics"
    e is Bridge.Failure && e.status in setOf(404,405) || e is UnsupportedOperationException -> "Not available on this bridge; use Share diagnostics"
    e is Bridge.Failure && e.status==429 -> "Not sent: diagnostic quota reached; use Share diagnostics"
    else -> "Delivery unconfirmed; use Share diagnostics. No automatic retry."
   }} finally {diagnosticSending=false}
  }
 }
 private var bridge:BridgePort?=null
 private var capture:AudioCapture?=null
 private var captureJob:Job?=null

 private var job:Job?=null
 private var statusChecking=false
 private var responseTiming:ResponseTiming?=null
 private var chunkCompletion:CompletableDeferred<Boolean>?=null
 private var foreground=false
 private var authenticated=false
 private var wakeCapture=false
 private var visibleHandoff:VisibleCommandHandoff?=null
 private var leaseEpoch=OffscreenOwnership.epoch()
 private var healthState="idle"
 private var healthGeneration:Long?=null
 private var lastHealthFailure="none"
 internal fun playbackAmplitude():Float=(playback as? Playback)?.amplitude() ?: 0f
 internal fun clearPlaybackMeter() {(playback as? Playback)?.clearMeter()}
 /** Local one-shot metadata: allowlisted codes and masked IDs only; never raw state/body. */
 internal fun diagnosticSnapshot(versionCode:Long):String {
  val u=_ui.value
  val (listenerAck,commandAck)=HeySarahListenerService.cleanupSnapshot()
  val listener=HeySarahListenerService.status.value.takeIf {it in setOf("off","starting","Wake listening","hit","released","starting-command-mic","recording","recording-media-muted","uploading","polling","speaking","done","stopping","stopped","discarded","error","interrupted","uncertain","fallback","locked","cleanup-failed","confirmation-required","destroyed-cleanup-pending","cancelled") } ?: "other"
  val phase=u.phase.takeIf {it in setOf("disconnected","ready","done","error","cancelled","uncertain","recording","finalizing","uploading","polling","playing","reply_audio_pending","confirming","creating","cancelling") } ?: "other"
  return listOf("build=$versionCode",
   "requestServerError=${RequestDiagnostics.savedServerError(state)}",
   RequestDiagnostics.masked(state,"request","savedRequest"),
   RequestDiagnostics.masked(state,"turn","savedTurn"),
   RequestDiagnostics.masked(state,"conversation","savedConversation"),
   "foreground=$foreground", "listener=$listener",
   "phase=$phase", "finishWaiting=${u.status=="Finishing background command"}","canCapture=${u.canCapture}",
   "leaseHeld=${OffscreenOwnership.held()}","leaseEpoch=${OffscreenOwnership.epoch()}",
   "vmEpoch=$leaseEpoch","releaseCount=${OffscreenOwnership.releases.value}",
   "listenerCleanupAck=${listenerAck ?: "absent"}","commandCleanupAck=${commandAck ?: "absent"}",
   "health=$healthState","healthGeneration=${healthGeneration ?: "none"}",
   "currentGeneration=${generation.get()}","healthCurrent=${healthState !in setOf("skippedBackground","skippedBusy","skippedNoBridge") && healthGeneration!=null && healthGeneration==generation.get()}",
   "statusChecking=$statusChecking","audioNext=${state.optInt("audioNext",0).coerceIn(0,32)}","chunkInFlight=${state.optBoolean("chunkInFlight")}","requestPhase=${state.optString("requestPhase").takeIf {it in setOf("submit","poll","download","playback","status","terminal")} ?: "none"}","requestFailure=${state.optString("requestFailure").takeIf {it in setOf("tls","access","rateLimit","notReady","http","timeout","dns","connect","noRoute","eof","protocol","network","formatOrConnection","interrupted")} ?: "none"}","requestHttp=${state.optInt("requestHttp",0).coerceIn(0,599)}","lastHealthFailure=$lastHealthFailure","responseTimings=${state.optJSONObject("responseTimings") ?: "absent"}").joinToString("\n")
 }
 private fun healthFailure(e:Exception)=when(e) {
  is javax.net.ssl.SSLException -> "tls"
  is Bridge.Failure -> when(e.status) {403->"access";429->"rateLimit";503->"notReady";else->"http"}
  is java.net.SocketTimeoutException -> "timeout"
  is java.net.UnknownHostException -> "dns"
  is java.net.ConnectException -> "connect"
  is java.net.NoRouteToHostException -> "noRoute"
  is java.io.EOFException -> "eof"
  is java.net.ProtocolException -> "protocol"
  is IOException -> "network"
  else -> "formatOrConnection"
 }
 private fun serviceBusy()=(visibleHandoff?.let {!it.owned()} ?: (HeySarahListenerService.status.value!="off")) || OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch()
 private val playback=playbackFactory { clean->val completion=chunkCompletion;if(completion!=null) completion.complete(clean) else {val g=generation.get();val c=state.optString("conversation");val r=state.optString("request");scope.launch { if (owner(g,c,r) && _ui.value.phase=="playing") {show("done",if(clean) "Reply ready" else "Playback interrupted");if(clean) rearmIfEligible() else {wakeCapture=false;runCatching {abortWindow()}}} } } }
 init {
  try {
   state=vault.load()
   if (state.has("origin") && state.has("token")) {
    bridge=makeBridge()
    val phase=state.optString("phase","ready")
    if (serviceBusy()) {restore()} else if (phase in listOf("uploading","recording","creating","cancelling","confirming","polling")) {
     state.put("phase","uncertain");save()
    } else if (state.optBoolean("chunkInFlight") || phase in setOf("playing","reply_audio_pending") && state.has("request")) {
     state.put("phase","uncertain").put("status",interruptedPlaybackStatus());save()
    } else if (phase in setOf("playing","reply_audio_pending")) {
     state.put("phase","done");save()
    }
    restore()
   }
  } catch (_:OffscreenOwnership.LeaseHeld) { _ui.value=Ui(status="Finishing background command") }
    catch (_:Exception) { state=JSONObject();_ui.value=Ui(status="Secure storage unavailable. Re-pair required; no plaintext recovery.",phase="error") }
  // Lease release precedes service-off or same-owner listening. Observe both;
  // listening permits persisted presentation only, not manual capture or reconnect.
  scope.launch { OffscreenOwnership.releases.collect {
   if(foreground && HeySarahListenerService.status.value in setOf("off","Wake listening") &&
    _ui.value.status=="Finishing background command") syncAfterService()
  } }
  scope.launch { HeySarahListenerService.status.collect { status ->
   if(status in setOf("off","Wake listening") && foreground && !_ui.value.canCapture &&
    (_ui.value.status=="Finishing background command" || leaseEpoch!=OffscreenOwnership.epoch() || status=="off" && !authenticated)) syncAfterService()
  } }
 }
 private fun makeBridge()=bridgeFactory(state.getString("origin"),state.getString("token"),state.optString("ca","").takeIf {it.isNotEmpty()}?.let { android.util.Base64.decode(it,android.util.Base64.DEFAULT) })
 private fun save() {if(!OffscreenOwnership.held() && leaseEpoch==OffscreenOwnership.epoch()) vault.save(state)}
 private fun messages():List<Pair<String,String>> {
  val a=state.optJSONArray("messages") ?: return emptyList()
  return (0 until a.length()).mapNotNull { i->a.optJSONObject(i)?.let { it.optString("who") to it.optString("text") } }
 }
 private fun restore() {
  val p=state.optString("phase","ready")
  _ui.value=Ui(p,state.optString("status").takeIf {it.isNotBlank()} ?: if(p=="uncertain") "Outcome uncertain. Check existing request; never resend." else p.replaceFirstChar {it.uppercase()},state.optString("conversation").takeIf {it.isNotEmpty()},messages(),true,canCapture=authenticated && p in setOf("ready","done","error","cancelled"))
 }
 private fun show(phase:String,status:String,confirmation:JSONObject?=null) {
  if(phase=="uncertain" && visibleHandoff!=null) {wakeCapture=false;runCatching {abortWindow()}}
  state.put("phase",phase).put("status",status);save()
  _ui.value=Ui(phase,status,state.optString("conversation").takeIf {it.isNotEmpty()},messages(),bridge!=null,confirmation,authenticated && phase in setOf("ready","done","error","cancelled"))
 }
 private fun append(who:String,text:String) {
  val rows=state.optJSONArray("messages") ?: JSONArray()
  rows.put(JSONObject().put("who",who).put("text",if(text.length>3000) text.take(3000)+" … [locally truncated]" else text).put("time",System.currentTimeMillis()))
  val kept=JSONArray();val cutoff=System.currentTimeMillis()-30L*24*60*60*1000
  for (i in maxOf(0,rows.length()-100) until rows.length()) {
   val r=rows.getJSONObject(i);if(r.optLong("time",0)>=cutoff) kept.put(r)
  }
  state.put("messages",kept);save();_ui.value=_ui.value.copy(transcript=messages())
 }
 private fun owner(g:Long,c:String,r:String):Boolean=foreground && !serviceBusy() && generation.get()==g && state.optString("conversation")==c && state.optString("request")==r
 private fun stopOperations() {
  val handoff=visibleHandoff;visibleHandoff=null
  val recording=captureJob;val mic=capture
  if(healthState=="inflight") healthState="canceled"
  generation.incrementAndGet();statusChecking=false;val wake=wakeCapture;wakeCapture=false
  job?.cancel();job=null;chunkCompletion?.cancel();chunkCompletion=null;mic?.stop();recording?.cancel();captureJob=null;mic?.discard();capture=null
  val playbackClosed=(playback as? Playback)?.stopAcknowledgement()
  if(playbackClosed==null) playback.stop()
  if(wake) runCatching {abortWindow()}
  if(handoff!=null) scope.launch {
   if(CommandCleanup.await(recording,{(mic as? Capture)?.releaseComplete ?: true},
     playbackClosed ?: java.util.concurrent.CompletableFuture.completedFuture(true))) handoff.complete(false)
  }
 }
 private fun stopVisibleCommand() {
  val phase=_ui.value.phase
  val remote=bridge;val turn=state.optString("turn")
  stopOperations()
  if(phase in setOf("polling","playing","reply_audio_pending","cancelling") && Identity.valid(turn)) {
   show("cancelling","Stopping speech and server turn; no action rollback")
   job=scope.launch {try {val row=withContext(io) {remote!!.cancel(turn)};show(if(row.optString("state")=="done") "done" else row.optString("state"),"Speech stopped; dispatched actions not undone")}
    catch(_:Exception) {show("uncertain","Cancel outcome uncertain; no retry")}}
   return
  }
  when(phase) {
   "recording","finalizing" -> show("ready","Recording discarded; nothing sent")
   "uploading","polling","cancelling" -> show("uncertain","Command stopped. Check existing request; never resend.")
   "playing","reply_audio_pending" -> show("done","Playback stopped. Server work not cancelled.")
  }
 }
 private fun rearmIfEligible() {
  val should=wakeCapture && foreground && authenticated && _ui.value.phase in setOf("done","error","cancelled") && commandEligible(true)
  val handoff=visibleHandoff;visibleHandoff=null;wakeCapture=false
  if(handoff!=null) handoff.complete(should) else if(should) runCatching {rearmListener()} // production rechecks visible, keyguard, opt-in deadline and audio lease
 }
 /** Called only by the service on the main thread, after native engine and AudioRecord release. */
 internal fun acceptWake(handoff:VisibleCommandHandoff?=HeySarahListenerService.visibleHandoff()):Boolean {
  if(!foreground || !authenticated || !_ui.value.canCapture || _ui.value.phase !in setOf("ready","done","error","cancelled") || !commandEligible(true) || !AudioArbiter.idle()) return false
  startCapture(true,handoff)
  return _ui.value.phase=="recording" && wakeCapture
 }
 fun onForeground() { foreground=true;if(HeySarahListenerService.status.value!="off") {
   _ui.value=_ui.value.copy(canCapture=false)
   if(HeySarahListenerService.status.value=="Wake listening" &&
    (_ui.value.status=="Finishing background command" || leaseEpoch!=OffscreenOwnership.epoch())) syncAfterService()
  } else if(leaseEpoch!=OffscreenOwnership.epoch()) {_ui.value=_ui.value.copy(canCapture=false);syncAfterService()}
  else if(!authenticated) syncAfterService() }
 fun syncAfterService() {
  val listenerOff=HeySarahListenerService.status.value=="off"
  if(!foreground || !listenerOff && HeySarahListenerService.status.value!="Wake listening" || _ui.value.canCapture) return
  if(OffscreenOwnership.held()) {_ui.value=_ui.value.copy(status="Finishing background command",canCapture=false);return}
  try {state=vault.load();leaseEpoch=OffscreenOwnership.epoch();bridge=if(state.has("origin") && state.has("token")) makeBridge() else null
   if(bridge==null) {authenticated=false;_ui.value=if(state.length()==0) Ui() else Ui(phase="error",status="Secure storage unavailable");return}
   if(state.optString("phase") in setOf("uploading","recording","creating","cancelling","confirming","polling")) {state.put("phase","uncertain");save()}
   if(state.optBoolean("chunkInFlight") || state.optString("phase") in setOf("playing","reply_audio_pending") && state.has("request")) {state.put("phase","uncertain").put("status",interruptedPlaybackStatus());save()}
   authenticated=false;restore();if(listenerOff) reconnect()}
  catch (_:OffscreenOwnership.LeaseHeld) {_ui.value=_ui.value.copy(status="Finishing background command",canCapture=false)}
  catch (_:Exception) {_ui.value=_ui.value.copy(phase="error",status="Secure storage unavailable",canCapture=false)}
 }
 fun onBackground() {
  if(wakeCapture) abortWindow()
  foreground=false;authenticated=false;stopOperations();_ui.value=_ui.value.copy(canCapture=false)
  if(OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch()) return
  if (_ui.value.phase in setOf("recording","finalizing")) show("ready","Recording discarded when app left foreground")
  else if (_ui.value.phase in setOf("playing","reply_audio_pending")) show(if(state.has("request")) "uncertain" else "done","Playback stopped; completion unknown. Check existing request; never resend.")
  else if (_ui.value.phase in listOf("uploading","polling","creating","cancelling","confirming")) show("uncertain","Connection interrupted. Check existing request; no retry.")
 }
 fun configure(url:String,token:String,ca:ByteArray?=null) {
  if (!foreground || serviceBusy()) return
  val origin=try { Origin.parse(url) } catch (_:Exception) { _ui.value=_ui.value.copy(status="Enter an HTTPS origin (no path or credentials)",phase="error");return }
  if (token.length !in 40..256 || token.any { it.code == 10 || it.code == 13 }) { _ui.value=_ui.value.copy(status="Enter separate revocable device token",phase="error");return }
  stopOperations();authenticated=false;_ui.value=_ui.value.copy(canCapture=false);val g=generation.get()
  job=scope.launch {
   try {
    val candidate=withContext(io) { bridgeFactory(origin,token,ca).also { val h=it.health();require(h.getInt("protocol")==1 && h.getBoolean("ready")) {"Bridge not ready"} } }
    if (!foreground || serviceBusy() || generation.get()!=g) return@launch
    val conversation=withContext(io) { candidate.create() }
    if (!foreground || serviceBusy() || generation.get()!=g) return@launch
    val next=JSONObject().put("origin",origin).put("token",token).put("conversation",conversation).put("phase","ready").put("messages",JSONArray())
    if(ca!=null) next.put("ca",android.util.Base64.encodeToString(ca,android.util.Base64.NO_WRAP))
    vault.save(next);state=next;bridge=candidate;authenticated=true;restore()
   } catch (e:Exception) { if (foreground && generation.get()==g) _ui.value=_ui.value.copy(phase="error",status=safeError(e)) }
  }
 }
 fun reconnect() {
  if (!foreground || serviceBusy() || bridge==null) {
   healthState=when { !foreground->"skippedBackground";serviceBusy()->"skippedBusy";else->"skippedNoBridge" }
   return
  }
  if(_ui.value.phase in setOf("recording","finalizing")) {stopOperations();show("disconnected","Recording discarded for connection check")}
  else if(_ui.value.phase in setOf("uploading","polling","playing","reply_audio_pending","cancelling","confirming","creating")) {stopOperations();show("uncertain","Connection check interrupted active work. Check existing request; never resend.")}
  authenticated=false;_ui.value=_ui.value.copy(canCapture=false)
  if(healthState=="inflight") healthState="canceled"
  statusChecking=false;val g=generation.incrementAndGet();job?.cancel();healthGeneration=g;healthState="inflight";lastHealthFailure="none"
  job=scope.launch {try {
   val h=withContext(io) {bridge!!.health()}
   if (foreground && !serviceBusy() && generation.get()==g) {
    if(h.optInt("protocol")!=1 || !h.optBoolean("ready")) {healthState="notReady";_ui.value=_ui.value.copy(phase="disconnected",status="Bridge not ready",canCapture=false)}
    else {healthState="succeeded";authenticated=true;val unresolved=state.optString("phase")=="uncertain";show(if(unresolved) "uncertain" else "ready",if(unresolved) state.optString("status","Outcome uncertain. Check existing request; never resend.") else state.optString("status").takeIf {state.optString("requestPhase")=="terminal"} ?: "Connected")}
   } else if(healthGeneration==g) healthState="ignored"
  } catch (e:CancellationException) {if(healthGeneration==g) healthState="canceled";throw e}
    catch (e:Exception) {if(healthGeneration==g) {healthState="failed";lastHealthFailure=healthFailure(e)};if(foreground && generation.get()==g) _ui.value=_ui.value.copy(phase=if(state.optString("phase")=="uncertain") "uncertain" else "disconnected",status="Connection check failed: ${safeError(e)}. ${if(state.optString("phase")=="uncertain") "Check existing request; never resend." else ""}",canCapture=false)} }
 }
 fun startCapture(fromWake:Boolean=false) = startCapture(fromWake,null)
 private fun startCapture(fromWake:Boolean,handoff:VisibleCommandHandoff?) {
  if(!foreground || serviceBusy() && !fromWake || OffscreenOwnership.held() || !authenticated || !_ui.value.canCapture || bridge==null || _ui.value.phase !in listOf("ready","done","error","cancelled") || state.optString("conversation").isEmpty()) return
  if(!commandEligible(fromWake)) return
  stopOperations();wakeCapture=fromWake;visibleHandoff=handoff;handoff?.onStop={stopVisibleCommand()};val g=generation.get();val c=captureFactory {scope.launch {routeInterrupted()}};capture=c
  if(c is Capture) {
   c.eligibility={commandEligible(fromWake) && (handoff?.owned() ?: true)}
   c.onMicReady={cue->scope.launch {
    if(foreground && generation.get()==g && capture===c && _ui.value.phase=="recording")
     _ui.value=_ui.value.copy(status=if(cue==MicReadyCueGate.Result.OUTPUT_MUTED)
      "Microphone recording · media output muted; no audible cue. Stop or discard anytime"
      else "Microphone recording · speak now; sends after an adaptive speech pause")
   }}
  }
  show("recording","Starting microphone · wait for cue; stop or discard anytime")
  captureJob=scope.launch {try {
   c.record()
   if(foreground && generation.get()==g && capture===c && _ui.value.phase=="recording") {
    if(c.capped) {if(wakeCapture) abortWindow();c.discard();capture=null;show("ready","30-second limit reached. Recording discarded; tap again.")}
    else if(c.endpointReached && c.speechDetected) send()
    else {if(wakeCapture) abortWindow();c.discard();capture=null;show("ready","Recording ended without speech; nothing sent")}
   }
  } catch (_:Exception) {if(foreground && generation.get()==g && _ui.value.phase=="recording") {if(wakeCapture) abortWindow();c.discard();capture=null;show("error","Microphone interrupted or 16 kHz input unavailable")}} }
 }
 fun discard() {if(_ui.value.phase=="recording") {if(wakeCapture) abortWindow();stopOperations();show("ready","Recording discarded")}}
 fun send() {
  if (!foreground || OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch() || _ui.value.phase!="recording") return
  if(!commandEligible(wakeCapture)) {discard();return}
  val c=capture ?:return;val recordingJob=captureJob;val g=generation.get()

  show("finalizing","Finishing recording")
  responseTiming=ResponseTiming()
  c.stop()
  job=scope.launch {
   try {recordingJob?.join()} catch (_:CancellationException) {c.discard();return@launch}
   if(!foreground || serviceBusy() && (!wakeCapture || visibleHandoff!=null) || OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch() || generation.get()!=g || capture!==c) {c.discard();return@launch}
   captureJob=null;capture=null
   val wav=try { c.finish() } catch (_:Exception) {c.discard();show("error","Recording interrupted or too short; nothing sent");return@launch}
   if(OffscreenOwnership.held() || !commandEligible(wakeCapture)) {c.discard();if(!OffscreenOwnership.held()) show("ready","Recording eligibility lost; nothing sent");return@launch}
   val conversation=state.getString("conversation");val request=Identity.new()
   // durable identity and ambiguous status before any upload bytes leave process
   state.put("request",request).put("turn","").put("requestPhase","submit").put("requestHttp",0).put("requestFailure","none").put("requestServerError","none").put("phase","uncertain").put("audioNext",0).put("chunkInFlight",false).put("fingerprint",MessageDigest.getInstance("SHA-256").digest(wav).joinToString("") {"%02x".format(it)})
   try {save();show("uploading","Sending recording (outcome may be uncertain)")}
   catch (_:Exception) { _ui.value=_ui.value.copy(phase="error",status="Cannot securely save request; nothing sent");return@launch }
   try {
   responseTiming?.mark("upload_start_ms")
   val turn=withContext(io) {bridge!!.submit(conversation,request,wav)}
   responseTiming?.mark("upload_ack_ms")
   if(!owner(g,conversation,request)) return@launch
   state.put("turn",turn);show("polling","Processing · turn admitted; waiting for server")
   poll(g,conversation,request,turn)
   } catch (e:Exception) {if(owner(g,conversation,request)) {recordFailure(if(state.optString("turn").isEmpty()) "submit" else "poll",e);wakeCapture=false;abortWindow();show("uncertain","Submission may have reached server. ${safeError(e)} Check existing request; never resend.")}}
  }
 }
 private suspend fun poll(g:Long,c:String,r:String,turn:String) {
  var attempts=0;val deadline=System.nanoTime()+236_000_000_000L
  while(owner(g,c,r) && System.nanoTime()<deadline && attempts++<240) {
   awaitPollSlot()
   if(!owner(g,c,r)) return
   state.put("requestPhase","poll")
   val row=try {withContext(io) {bridge!!.pollChunks(turn,state.optInt("audioNext",0))}} catch (e:Exception) {if(owner(g,c,r)) {recordFailure("poll",e);wakeCapture=false;abortWindow();show("uncertain","Polling interrupted: ${safeError(e)}. Check existing request.")};return}
   if (!owner(g,c,r)) return
   if(row.optString("id")!=turn || row.optString("conversation")!=c) {show("uncertain","Server identity mismatch; no further action");return}
   val chunks=row.optJSONObject("audio_chunks")
   if(chunks!=null && row.optString("state")=="speaking") {
    val next=state.optInt("audioNext",0);val count=chunks.optInt("count",-1)
    if(count !in next..32 || state.optBoolean("chunkInFlight")) {show("uncertain","Audio sequence interrupted; no replay");return}
    if(next<count) {
     try {
      awaitPollSlot();if(!owner(g,c,r)) return
      state.put("requestPhase","download");save()
      val bytes=withContext(io) {bridge!!.audioChunk(turn,next)}
      if(!owner(g,c,r)) return
      beforePlayback();if(!owner(g,c,r)) return
      val completion=CompletableDeferred<Boolean>();chunkCompletion=completion
      state.put("requestPhase","playback").put("chunkInFlight",true);show("playing","Speaking · Stop cancels remaining speech")
      playback.play(bytes)
      if(next==0) responseTiming?.mark("first_chunk_prepared_ms")
      check(withTimeout(120_000L) {completion.await()})
      if(!owner(g,c,r)) return
      state.put("audioNext",next+1).put("chunkInFlight",false);save()
      chunkCompletion=null;show("polling","Waiting for next spoken sentence")
      continue
     } catch(e:CancellationException) {throw e}
       catch(e:Exception) {recordFailure("playback",e);chunkCompletion=null;playback.stop();wakeCapture=false;show("uncertain","Playback interrupted: ${safeError(e)}. Completion unknown; no replay. Check existing request.");return}
    }
   }
   applyRow(row,g,c,r);if(row.optString("state") in listOf("done","error","cancelled","uncertain","confirming")) return
   delay(ResultPolling.delayMs(attempts))
  }
  if(owner(g,c,r)) {wakeCapture=false;abortWindow();show("uncertain","Polling limit reached. Check existing request later.")}
 }
 private suspend fun applyRow(row:JSONObject,g:Long,c:String,r:String) {
  val stage=row.optString("state");val detail=row.optString("detail").take(8000);val transcript=row.optString("transcript").take(8000)
  if(stage in setOf("done","error","cancelled")) {state.put("audioNext",0).put("chunkInFlight",false);save()}
  if(transcript.isNotBlank() && state.optString("shownTranscript")!=r) {append("YOU",transcript);state.put("shownTranscript",r);save()}
  when(stage) {
   "done" -> {
    responseTiming?.mark("done_observed_ms")
    responseTiming?.let {state.put("responseTimings",it.snapshot(row.optJSONObject("timings")));save()}
    if(state.optString("shownReply")!=r) { append("S.A.R.A.H",detail);state.put("shownReply",r);save() }
    show(if(row.optBoolean("audio")) "reply_audio_pending" else "done","Reply ready${if (row.optBoolean("audio")) " · audio pending" else " · text only"}")
    if(!row.optBoolean("audio")) rearmIfEligible()
    if(row.optBoolean("audio") && owner(g,c,r)) try {
     val bytes=withContext(io) {bridge!!.audio(row.getString("id"))}
     responseTiming?.mark("audio_downloaded_ms")
     if(owner(g,c,r)) {beforePlayback();if(owner(g,c,r)) {playback.play(bytes);responseTiming?.mark("playback_prepared_ms");responseTiming?.let {state.put("responseTimings",it.snapshot(row.optJSONObject("timings")));save()};show("playing","Speaking · stop audio does not cancel work")}}
    } catch (_:Exception) {wakeCapture=false;if(owner(g,c,r)) show("done","Reply text ready. Audio unavailable")}
   }
   "confirming" -> {
    wakeCapture=false;abortWindow()
    val envelope=row.optJSONObject("confirmation")
    if(envelope==null || envelope.optString("conversation")!=c) show("uncertain","Confirmation unavailable or invalid. No action sent by app")
    else show("confirming","Server requests confirmation; acceptance does not prove action success",envelope)
   }
   "error","cancelled" -> {show(stage,detail.ifBlank {stage});rearmIfEligible()}
   "uncertain" -> {wakeCapture=false;abortWindow();show(stage,detail.ifBlank {stage})}
   "transcribing","thinking","acting","speaking" -> show("polling","Server: $stage${if(detail.isBlank()) "" else " · $detail"}")
   else -> show("uncertain","Unknown server state; no retry")
  }
 }
 private fun interruptedPlaybackStatus():String = if(state.optString("requestPhase")=="status" && state.optInt("requestHttp")==403)
  "Status check failed: HTTP 403 · ${RequestDiagnostics.savedServerError(state)}. Server outcome unknown; never resend."
  else "Playback interrupted; completion unknown. Check existing request; never resend."
 private fun recordFailure(phase:String,e:Exception) {
  state.put("requestPhase",phase).put("requestFailure",healthFailure(e)).put("requestHttp",(e as? Bridge.Failure)?.status ?: 0)
   .put("requestServerError",(e as? Bridge.Failure)?.let {RequestDiagnostics.serverError(it.reason)} ?: "none");save()
 }
 private fun statusOwner(g:Long,c:String,r:String)=foreground && !OffscreenOwnership.held() && leaseEpoch==OffscreenOwnership.epoch() && generation.get()==g && state.optString("conversation")==c && state.optString("request")==r && HeySarahListenerService.status.value in setOf("off","Wake listening")
 fun checkExisting() {
  if(statusChecking) return
  if(!foreground || bridge==null || _ui.value.phase!="uncertain") { _ui.value=_ui.value.copy(status="Status check unavailable in current phase");return }
  if(OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch() || HeySarahListenerService.status.value !in setOf("off","Wake listening")) { _ui.value=_ui.value.copy(status="Status check waiting for microphone command cleanup; no request sent");return }
  responseTiming=null
  val c=state.optString("conversation");val r=state.optString("request")
  if(!Identity.valid(c) || !Identity.valid(r)) {show("uncertain","Saved request identity unavailable. Cannot prove server finished; recording remains blocked.");return}
  val g=generation.incrementAndGet();job?.cancel();statusChecking=true
  state.put("requestPhase","status");show("uncertain","Checking existing request status… No resend or audio replay.")
  job=scope.launch {try {
   val row=withTimeout(60_000L) {withContext(io) {bridge!!.lookup(r)}}
   if(!statusOwner(g,c,r)) return@launch
   val turn=row.optString("id");val saved=state.optString("turn")
   if(!Identity.valid(turn) || row.optString("conversation")!=c || saved.isNotEmpty() && saved!=turn) {show("uncertain","Request identity mismatch; recording remains blocked");return@launch}
   state.put("turn",turn).put("requestServerError","none");authenticated=true
   val phase=row.optString("state")
   if(phase in setOf("done","error","cancelled")) {
    // Terminal receipt proves this exact owner finished. Never fetch audio or ACK on recovery.
    val errorKind=if(row.optString("detail").contains("(TimeoutError)")) " (TimeoutError)" else ""
    val outcome=if(phase=="error") "Request failed$errorKind; actions may already have happened. No automatic retry." else if(phase=="cancelled") "Request cancelled; dispatched actions not undone." else "Request finished. Audio not replayed."
    if(state.optString("shownRecovery")!=r) {append("S.A.R.A.H",outcome);state.put("shownRecovery",r)}
    state.put("audioNext",0).put("chunkInFlight",false).put("requestPhase","terminal").put("requestFailure","none").put("requestHttp",0)
    wakeCapture=false;show("ready","$outcome Ready for a new question.");if(HeySarahListenerService.status.value=="Wake listening") runCatching {abortWindow()}
   } else {
    val safePhase=phase.takeIf {it in setOf("transcribing","thinking","acting","speaking","confirming","uncertain")} ?: "unknown"
    show("uncertain","Status checked: $safePhase. Server not proven finished; no audio replay or ACK. Check later or stop server turn.")
   }
  } catch(e:Exception) {if(statusOwner(g,c,r)) {recordFailure("status",e);show("uncertain","Status check failed: ${safeError(e)}. Server outcome unknown; never resend.")}}
   finally {if(generation.get()==g) statusChecking=false}
  }
 }
 /** Explicit, one-off approval. Only GETs; never submit, ACK, cancel, create or replay. */
 fun recoverApprovedLocalRequest() {
  if(statusChecking) return
  fun blocked(reason:String) {_ui.value=_ui.value.copy(status="Local recovery blocked: $reason. Tracking kept; nothing resent.")}
  val wire=bridge
  if(!foreground || wire==null || _ui.value.phase!="uncertain" || !localRecoveryTarget.matches(state)) {blocked("saved request does not match exact approval");return}
  if(OffscreenOwnership.held() || leaseEpoch!=OffscreenOwnership.epoch() || HeySarahListenerService.status.value!="off" ||
   capture!=null || captureJob!=null || chunkCompletion!=null || wakeCapture || job?.isActive==true) {blocked("stop Hey Sarah and wait for command/audio cleanup");return}
  val audioReservation=Any()
  if(!AudioArbiter.acquire(audioReservation)) {blocked("audio still active");return}
  val before=state.toString();val c=state.getString("conversation");val r=state.getString("request")
  val g=generation.incrementAndGet();statusChecking=true
  _ui.value=_ui.value.copy(status="Checking exact approved missing request… No resend or audio ACK.",canCapture=false)
  job=scope.launch(start=CoroutineStart.UNDISPATCHED) {
   try {
    val absent=try {
     withTimeout(60_000L) {withContext(io) {wire.lookup(r)}}
     false // Any admitted row, even terminal, is outside this local-only approval.
    } catch(e:Bridge.Failure) {
     // Server authenticates bearer before owner-bound request lookup. Numeric 403 alone is NOT evidence.
     if(e.status==403 && e.reason=="not_found") true else throw e
    }
    if(!absent) {blocked("server returned an admitted request");return@launch}
    OffscreenOwnership.guarded(null) {
     if(!statusOwner(g,c,r) || HeySarahListenerService.status.value!="off" || _ui.value.phase!="uncertain" ||
      !localRecoveryTarget.matches(state) || state.toString()!=before) {blocked("request or command ownership changed");return@guarded}
     val saved=vault.load()
     if(saved.toString()!=before || !localRecoveryTarget.matches(saved)) {blocked("saved state changed during lookup");return@guarded}
     val next=JSONObject(saved.toString())
     // Keep ALL other keys, including audio progress/ACKs, action receipts, history, pairing and permissions.
     next.remove("request");next.remove("turn")
     next.put("phase","ready").put("status","Approved local request tracking cleared. Nothing resent. Same conversation kept; ready for a new question.")
     vault.save(next) // Atomic durable write must succeed before memory/UI can become ready.
     state=next;authenticated=true;restore()
    }
   } catch(e:CancellationException) {throw e}
     catch(e:Exception) {if(generation.get()==g && foreground) blocked(if(e is Bridge.Failure) safeError(e) else "fresh lookup or secure storage unavailable")}
   finally {AudioArbiter.release(audioReservation);if(generation.get()==g) statusChecking=false}
  }
 }
 fun cancelTurn() {
  val turn=state.optString("turn");val c=state.optString("conversation");val r=state.optString("request")
  if(!foreground || serviceBusy() || !Identity.valid(turn) || _ui.value.phase !in setOf("polling","confirming","playing","reply_audio_pending","uncertain")) return
  val g=generation.incrementAndGet();job?.cancel();chunkCompletion?.cancel();chunkCompletion=null;playback.stop();show("cancelling","Cancelling server turn; this cannot undo dispatched actions")
  job=scope.launch {try {
   val row=withContext(io) {bridge!!.cancel(turn)}
   if(owner(g,c,r)) {
    if(row.optString("state")=="done") show("done","Speech stopped; completed actions not undone") else applyRow(row,g,c,r)
   }
  } catch(e:Exception) {if(owner(g,c,r)) show("uncertain","Cancel outcome uncertain. Check request; actions may have occurred.")}}
 }
 fun confirm(accept:Boolean) {
  val envelope=_ui.value.confirmation ?:return;val turn=state.optString("turn");val c=state.optString("conversation");val r=state.optString("request")
  if(!foreground || serviceBusy() || _ui.value.phase!="confirming" || !Identity.valid(turn)) return
  val g=generation.incrementAndGet();job?.cancel();show("confirming","Sending confirmation; acceptance is not action success")
  job=scope.launch {try {
   withContext(io) {bridge!!.confirm(turn,c,envelope.getString("nonce"),envelope.getString("action_hash"),accept)}
   if(owner(g,c,r)) poll(g,c,r,turn)
  } catch (_:Exception) {if(owner(g,c,r)) show("uncertain","Confirmation outcome uncertain. Check existing request.")}}
 }
 fun stopAudio() {if(serviceBusy()) return;cancelTurn()}
 fun newConversation() {
  if(!foreground || serviceBusy() || bridge==null) return
  stopOperations();val g=generation.get();show("creating","Creating separate server conversation; pending work is not undone")
  job=scope.launch {try {
   val c=withContext(io) {bridge!!.create()}
   if(!foreground || serviceBusy() || generation.get()!=g) return@launch
   state.remove("request");state.remove("turn");state.remove("fingerprint");state.remove("shownTranscript");state.remove("shownReply")
   state.put("conversation",c).put("messages",JSONArray());authenticated=false;show("disconnected","New conversation created. Check connection before recording");reconnect()
  } catch (_:Exception) {if(foreground && generation.get()==g) show("uncertain","New conversation outcome unknown. No automatic retry; old conversation retained.")}}
 }
 fun clearLocal() {if(serviceBusy()) return;state.put("messages",JSONArray());save();_ui.value=_ui.value.copy(transcript=emptyList(),status=if(_ui.value.phase=="uncertain") _ui.value.status else "Local transcript cleared. Server history remains.")}
 fun resetPairing() {
  if(!foreground || serviceBusy()) return
  stopOperations();authenticated=false;try {vault.reset();state=JSONObject();bridge=null;_ui.value=Ui(status="Local pairing cleared. Server conversations remain; request new device token from bridge administrator.")}
  catch (_:Exception) {_ui.value=_ui.value.copy(phase="error",status="Secure storage reset failed; no plaintext recovery")}
 }
 fun routeInterrupted() {
  if(serviceBusy()) return
  if (_ui.value.phase in setOf("recording","finalizing")) {stopOperations();show("ready","Recording interrupted; nothing sent")}
  else if (_ui.value.phase=="playing") stopAudio()
 }
 private fun safeError(e:Exception)=when(e) {
  is javax.net.ssl.SSLException -> "TLS verification failed"
  is Bridge.Failure -> when(e.status) {403->"HTTP 403 · ${RequestDiagnostics.serverError(e.reason)} · "+when(RequestDiagnostics.serverError(e.reason)) {
   "not_found"->"Saved identity not found for this device; recovery requires operator review"
   "unauthorized"->"Device authentication rejected"
   "invalid_identifier"->"Saved identity rejected; recovery requires operator review"
   else->"Access denied; cause not retained"
  };429->"HTTP 429 · Rate limited";503->"HTTP 503 · Bridge not ready";else->"HTTP ${e.status}"}
  is java.net.SocketTimeoutException -> "Network timeout"
  is IOException -> "Network unavailable"
  else -> "Connection or format error"
 }
 override fun onCleared() {onBackground();scope.cancel();super.onCleared()}
}
