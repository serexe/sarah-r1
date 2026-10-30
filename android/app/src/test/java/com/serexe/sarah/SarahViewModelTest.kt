package com.serexe.sarah

import android.app.Application
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.io.EOFException
import java.net.ConnectException
import java.net.ProtocolException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

/** Exercises production SarahViewModel, not unused TurnState. No Android device/network. */
class SarahViewModelTest {
 private class Memory(initial:JSONObject,private val guarded:Boolean=false,private val loadFailure:Exception?=null):StateStore {
  var value=JSONObject(initial.toString())
  var writes=0
  override fun load():JSONObject = if(guarded) OffscreenOwnership.guarded(null) {loadFailure?.let {throw it};JSONObject(value.toString())}
   else {loadFailure?.let {throw it};JSONObject(value.toString())}
  override fun save(value:JSONObject) {if(guarded) OffscreenOwnership.guarded(null) {write(value)} else write(value)}
  private fun write(value:JSONObject) {writes++;this.value=JSONObject(value.toString())}
  override fun reset() {value=JSONObject()}
 }
 private class Wire:BridgePort {
  var healthy=true;var failure:Exception?=null;var posts=0;var lookups=0
  var creates=0;var cancels=0;var confirms=0
  var onSubmit:(()->Unit)?=null
  var onConfirm:(()->Unit)?=null
  var onAudio:(()->Unit)?=null
  var row=JSONObject().put("id","t1").put("conversation","c1").put("state","done").put("detail","reply").put("audio",false)
  override fun health():JSONObject {failure?.let {throw it};return JSONObject().put("protocol",1).put("ready",healthy)}
  override fun create():String {creates++;return "c1"}
  override fun submit(conversation:String,request:String,wav:ByteArray):String {posts++;onSubmit?.invoke();return "t1"}
  override fun lookup(request:String):JSONObject {lookups++;return row}
  override fun poll(turn:String)=row
  override fun cancel(turn:String):JSONObject {cancels++;return row}
  override fun confirm(turn:String,conversation:String,nonce:String,hash:String,accept:Boolean):JSONObject {confirms++;onConfirm?.invoke();return row}
  override fun audio(turn:String):ByteArray {onAudio?.invoke();return byteArrayOf(1)}
 }
 private class Mic:AudioCapture {
  val end=CompletableDeferred<Unit>();var stopped=false;var joined=false;var discarded=false;var finished=0;var permissionRevoked=false
  var stopCompletes=false;var releaseGate:CompletableDeferred<Unit>?=null;override var speechDetected=true;override var endpointReached=false
  override val capped=false
  override suspend fun record() {try {end.await()} finally {withContext(NonCancellable) {releaseGate?.await();joined=true}}}
  override fun stop() {stopped=true;if(stopCompletes) end.complete(Unit)}
  override fun finish():ByteArray {check(joined);if(permissionRevoked) throw SecurityException("permission revoked");finished++;return Wav.encode(ByteArray(8000))}
  override fun discard() {discarded=true;stop();end.complete(Unit)}
 }
 private class Sound(private val done:(Boolean)->Unit):AudioPlayback {var played=0;override fun play(bytes:ByteArray) {played++};override fun stop() {};fun finish(clean:Boolean=true)=done(clean)}
 private fun persisted(phase:String="ready")=JSONObject().put("origin","https://fixture.invalid").put("token","x".repeat(48)).put("conversation","c1").put("phase",phase)
 private data class Fixture(val vm:SarahViewModel,val memory:Memory,val wire:Wire,val mic:Mic,val sound:Sound,val captureStarts:()->Int,val rearms:()->Int)
 private fun fixture(initial:JSONObject=persisted(),eligible:(Boolean)->Boolean={true},beforePlayback:suspend ()->Unit={},
  guardedStore:Boolean=false,loadFailure:Exception?=null,abort:()->Unit={}):Fixture {
  val memory=Memory(initial,guardedStore,loadFailure);val wire=Wire();val mic=Mic();lateinit var sound:Sound;var starts=0;var rearms=0
  val vm=SarahViewModel(Application(),memory,{_,_,_->wire},{_->starts++;mic},{done->Sound(done).also {sound=it}},CoroutineScope(SupervisorJob()+Dispatchers.Unconfined),Dispatchers.Unconfined,eligible,beforePlayback,{rearms++},abort)
  return Fixture(vm,memory,wire,mic,sound,{starts},{rearms})
 }
 @Test fun localSnapshotUsesRealLeaseReleaseAndHealthStateWithoutSensitiveFields() {
  val secret="dangerous-private-text"
  val f=fixture(persisted().put("token",secret).put("messages",org.json.JSONArray().put(JSONObject().put("who","YOU").put("text",secret))))
  f.vm.onForeground()
  val healthy=f.vm.diagnosticSnapshot(19)
  assertTrue(healthy.contains("build=19"));assertTrue(healthy.contains("health=succeeded"))
  assertTrue(healthy.contains("healthCurrent=true"));assertTrue(healthy.contains("foreground=true"))
  assertTrue(healthy.contains("listenerCleanupAck=absent"));assertTrue(healthy.contains("commandCleanupAck=absent"))
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  try {
   f.vm.reconnect()
   val held=f.vm.diagnosticSnapshot(19)
   assertTrue(held.contains("leaseHeld=true"));assertTrue(held.contains("health=skippedBusy"))
   assertTrue(held.contains("healthCurrent=false"))
   assertFalse(held.contains(secret));assertFalse(held.contains("fixture.invalid"));assertFalse(held.contains("c1"))
  } finally {OffscreenOwnership.release(owner)}
  val released=f.vm.diagnosticSnapshot(19)
  assertTrue(released.contains("leaseHeld=false"))
  assertTrue(released.contains("releaseCount=${OffscreenOwnership.releases.value}"))
  f.vm.onBackground();f.vm.onForeground();f.wire.failure=IOException(secret);f.vm.reconnect()
  val failed=f.vm.diagnosticSnapshot(19)
  assertTrue(failed,failed.contains("health=failed"));assertTrue(failed,failed.contains("lastHealthFailure=network"))
  assertFalse(failed.contains(secret));assertFalse(failed.contains("fixture.invalid"))
  try {
   HeySarahListenerService.status.value=secret
   val redacted=f.vm.diagnosticSnapshot(19)
   assertTrue(redacted.contains("listener=other"))
   assertFalse(redacted.contains(secret))
  } finally {HeySarahListenerService.status.value="off"}
 }
 @Test fun healthFailureCauseIsFixedCategoryAndNeverLeaksThrowableText() {
  val f=fixture();f.vm.onForeground()
  val secret="private-host-token-response"
  for ((failure,category) in listOf(
   UnknownHostException(secret) to "dns",
   ConnectException(secret) to "connect",
   SocketTimeoutException(secret) to "timeout",
   EOFException(secret) to "eof",
   ProtocolException(secret) to "protocol",
   SSLHandshakeException(secret) to "tls",
   IOException(secret) to "network")) {
   f.wire.failure=failure;f.vm.reconnect()
   val snapshot=f.vm.diagnosticSnapshot(29)
   assertTrue(snapshot,snapshot.contains("health=failed"))
   assertTrue(snapshot,snapshot.contains("lastHealthFailure=$category"))
   assertFalse(snapshot,snapshot.contains(secret))
   assertFalse(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  }
 }
 @Test fun newActivityWhileOffscreenOwnsVaultDefersLoadAndRestoresReplyAfterRelease() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  lateinit var f:Fixture
  try {
   f=fixture(guardedStore=true)
   assertEquals("Finishing background command",f.vm.ui.value.status)
   assertFalse(f.vm.ui.value.status.startsWith("Secure storage unavailable"))
   f.vm.onForeground();assertFalse(f.vm.ui.value.canCapture)
   OffscreenOwnership.guarded(owner) {
    f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))
   }
   assertEquals(0,f.memory.writes)
  } finally {OffscreenOwnership.release(owner)}
  f.vm.syncAfterService()
  assertEquals("c1",f.vm.ui.value.conversation)
  assertEquals(listOf("S.A.R.A.H" to "reply"),f.vm.ui.value.transcript)
  assertEquals("ready",f.vm.ui.value.phase)
  assertTrue(f.vm.ui.value.canCapture)
  assertEquals(0,f.wire.posts)
 }
 @Test fun serviceStatusOffAfterLeaseReleaseReloadsNewActivityWithoutResend() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  try {
   val f=fixture(guardedStore=true)
   f.vm.onForeground()
   assertFalse(f.vm.ui.value.canCapture)
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   OffscreenOwnership.release(owner)
   HeySarahListenerService.status.value="off"
   // Production VM must observe service completion even if Compose missed lifecycle collection.
   assertEquals("c1",f.vm.ui.value.conversation)
   assertEquals("reply",f.vm.ui.value.transcript.single().second)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseWhileListenerStillSpeakingThenOffRecoversWithoutComposeEvent() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  try {
   val f=fixture(guardedStore=true);f.vm.onForeground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   OffscreenOwnership.release(owner) // Real OffscreenCommand order: release, then finishService/off.
   assertFalse(f.vm.ui.value.canCapture)
   HeySarahListenerService.status.value="off" // No manual syncAfterService or Compose callback.
   assertEquals("c1",f.vm.ui.value.conversation)
   assertEquals(listOf("S.A.R.A.H" to "reply"),f.vm.ui.value.transcript)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseThenWakeListeningRestoresResolvedResultButBlocksManualCapture() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  val f=fixture(guardedStore=true)
  try {
   f.vm.onForeground()
   assertEquals("Finishing background command",f.vm.ui.value.status)
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   OffscreenOwnership.release(owner)
   assertEquals("Finishing background command",f.vm.ui.value.status)
   HeySarahListenerService.status.value="Wake listening" // Real completion order, never off.
   assertEquals("done",f.vm.ui.value.phase)
   assertEquals("c1",f.vm.ui.value.conversation)
   assertEquals(listOf("S.A.R.A.H" to "reply"),f.vm.ui.value.transcript)
   assertFalse(f.vm.ui.value.canCapture)
   f.vm.startCapture();f.vm.send();f.vm.confirm(true)
   assertEquals(0,f.captureStarts());assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms)
   assertEquals(0,f.memory.writes);assertEquals(0,f.rearms())
   HeySarahListenerService.status.value="off"
   assertTrue(f.vm.ui.value.canCapture) // Off still performs authenticated recovery.
   assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms)
  } finally {f.vm.onBackground();OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseThenWakeListeningPreservesUncertainRequestWithoutReplay() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="uploading"
  val f=fixture(guardedStore=true);val request=Identity.new()
  try {
   f.vm.onForeground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("uncertain").put("request",request).put("turn","")}
   OffscreenOwnership.release(owner);HeySarahListenerService.status.value="Wake listening"
   assertEquals("uncertain",f.vm.ui.value.phase)
   assertTrue(f.vm.ui.value.status.contains("never resend"))
   assertEquals("c1",f.vm.ui.value.conversation)
   assertFalse(f.vm.ui.value.canCapture);assertNull(f.vm.ui.value.confirmation)
   f.vm.startCapture();f.vm.send();f.vm.confirm(true);f.vm.checkExisting();f.vm.reconnect()
   assertEquals(request,f.memory.value.getString("request"))
   assertEquals("uncertain",f.memory.value.getString("phase"))
   assertEquals(0,f.captureStarts());assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms);assertEquals(0,f.wire.lookups)
   assertEquals(0,f.memory.writes);assertEquals(0,f.rearms())
   HeySarahListenerService.status.value="off"
   assertEquals("uncertain",f.vm.ui.value.phase);assertFalse(f.vm.ui.value.canCapture)
   assertEquals(request,f.memory.value.getString("request"))
   assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms);assertEquals(0,f.wire.lookups)
  } finally {f.vm.onBackground();OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseThenWakeListeningWhileBackgroundedRestoresOnResume() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  val f=fixture(guardedStore=true)
  try {
   f.vm.onForeground();f.vm.onBackground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done")}
   OffscreenOwnership.release(owner);HeySarahListenerService.status.value="Wake listening"
   assertNull(f.vm.ui.value.conversation)
   f.vm.onForeground()
   assertEquals("done",f.vm.ui.value.phase);assertEquals("c1",f.vm.ui.value.conversation)
   assertFalse(f.vm.ui.value.canCapture);f.vm.startCapture()
   assertEquals(0,f.captureStarts());assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms)
  } finally {f.vm.onBackground();OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun wakeListeningBeforeLeaseReleaseStillWaitsForRealOwnershipRelease() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  val f=fixture(guardedStore=true)
  try {
   f.vm.onForeground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done")}
   HeySarahListenerService.status.value="Wake listening"
   assertEquals("Finishing background command",f.vm.ui.value.status)
   assertNull(f.vm.ui.value.conversation);assertFalse(f.vm.ui.value.canCapture)
   OffscreenOwnership.release(owner)
   assertEquals("done",f.vm.ui.value.phase);assertEquals("c1",f.vm.ui.value.conversation)
   assertFalse(f.vm.ui.value.canCapture);f.vm.startCapture()
   assertEquals(0,f.captureStarts());assertEquals(0,f.wire.posts);assertEquals(0,f.wire.confirms)
  } finally {f.vm.onBackground();OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseThenListenerOffWhileBackgroundedRecoversOnResume() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  try {
   val f=fixture(guardedStore=true);f.vm.onForeground();f.vm.onBackground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"
   assertNull(f.vm.ui.value.conversation)
   f.vm.onForeground()
   assertEquals("c1",f.vm.ui.value.conversation)
   assertEquals("reply",f.vm.ui.value.transcript.single().second)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun resumeAfterReleaseWhileListenerSpeakingWaitsForOffThenReloads() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  try {
   val f=fixture(guardedStore=true);f.vm.onForeground();f.vm.onBackground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   OffscreenOwnership.release(owner)
   f.vm.onForeground() // Foreground resumes between release and service-off.
   assertNull(f.vm.ui.value.conversation)
   assertFalse(f.vm.ui.value.canCapture)
   HeySarahListenerService.status.value="off"
   assertEquals("reply",f.vm.ui.value.transcript.single().second)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun resumeDuringBackgroundCommandRecoversOnLeaseReleaseWithoutSecondLifecycleEvent() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="speaking"
  try {
   val f=fixture(guardedStore=true)
   f.vm.onForeground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done").put("messages",org.json.JSONArray().put(JSONObject().put("who","S.A.R.A.H").put("text","reply")))}
   HeySarahListenerService.status.value="off"
   f.vm.syncAfterService() // single existing listener-off event races before lease release
   assertEquals("Finishing background command",f.vm.ui.value.status)
   assertFalse(f.vm.ui.value.canCapture)
   assertEquals(0,f.memory.writes)
   OffscreenOwnership.release(owner) // no second onForeground or listener-off event
   assertEquals("c1",f.vm.ui.value.conversation)
   assertEquals(listOf("S.A.R.A.H" to "reply"),f.vm.ui.value.transcript)
   assertEquals("ready",f.vm.ui.value.phase)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun leaseReleaseWhileBackgroundedWaitsForForegroundBeforeReload() {
  val owner=Any();assertTrue(OffscreenOwnership.acquire(owner))
  HeySarahListenerService.status.value="off"
  try {
   val f=fixture(guardedStore=true);f.vm.onForeground()
   assertEquals("Finishing background command",f.vm.ui.value.status)
   f.vm.onBackground()
   OffscreenOwnership.guarded(owner) {f.memory.value=persisted("done")}
   OffscreenOwnership.release(owner)
   assertFalse(f.vm.ui.value.canCapture)
   assertNull(f.vm.ui.value.conversation)
   f.vm.onForeground()
   assertEquals("c1",f.vm.ui.value.conversation)
   assertTrue(f.vm.ui.value.canCapture)
   assertEquals(0,f.wire.posts)
  } finally {OffscreenOwnership.release(owner);HeySarahListenerService.status.value="off"}
 }
 @Test fun unpairedForegroundRetryDoesNotInventConfiguration() {
  val f=fixture(JSONObject(),guardedStore=true)
  f.vm.onForeground()
  assertFalse(f.vm.ui.value.hasConfig)
  assertEquals("disconnected",f.vm.ui.value.phase)
  assertEquals(0,f.memory.writes)
  assertEquals(0,f.wire.posts)
 }
 @Test fun genuineDecryptFailureStaysFailClosedAndIsNotClassifiedAsLeaseWait() {
  val f=fixture(guardedStore=true,loadFailure=javax.crypto.AEADBadTagException("fixture"))
  assertTrue(f.vm.ui.value.status.startsWith("Secure storage unavailable"))
  f.vm.onForeground()
  assertEquals("error",f.vm.ui.value.phase)
  assertEquals("Secure storage unavailable",f.vm.ui.value.status)
  assertFalse(f.vm.ui.value.canCapture)
  assertEquals(0,f.memory.writes)
  assertEquals(0,f.wire.posts)
 }
 @Test fun visibleLiveServiceHandoffCompletesRepeatedResolvedCommandsWithoutColdRestart()=runBlocking {
  val started=10_000L;var now=started;var restarts=0;var stops=0
  for(phase in listOf("done","error","cancelled","done")) {
   val f=fixture();f.mic.endpointReached=true;f.wire.row.put("state",phase)
   f.vm.onForeground();HeySarahListenerService.status.value="released"
   var resolved=false;var current=true
   val completion=ServiceCommandCompletion({AudioArbiter.idle() && f.mic.joined},
    {ServiceRearmPolicy.allowed(current,false,false,started,now,true,true,resolved)},
    {restarts++;true},{stops++})
   val handoff=VisibleCommandHandoff({current},{resolved=it;completion.complete()})
   try {
    assertTrue(f.vm.acceptWake(handoff));assertFalse(f.vm.acceptWake(handoff))
    f.mic.end.complete(Unit);delay(30)
    assertEquals(phase,f.vm.ui.value.phase);assertEquals(1,f.wire.posts)
    assertFalse(handoff.owned());assertEquals(0,f.rearms()) // not legacy startForegroundService port
    handoff.complete(true);assertEquals(0,stops)
    now+=1000
   } finally {current=false;f.vm.onBackground();HeySarahListenerService.status.value="off"}
  }
  assertEquals(4,restarts);assertEquals(0,stops)
 }
 @Test fun visibleHandoffWaitsForPlaybackAndStopCleanupAndNeverReplaysUnknown()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.row.put("audio",true);f.vm.onForeground()
  var completed=0;var resolved=false
  val handoff=VisibleCommandHandoff({true},{completed++;resolved=it})
  HeySarahListenerService.status.value="released"
  try {
   assertTrue(f.vm.acceptWake(handoff));f.mic.end.complete(Unit);delay(30)
   assertEquals("playing",f.vm.ui.value.phase);assertEquals(0,completed)
   f.sound.finish();assertEquals(1,completed);assertTrue(resolved)
   f.sound.finish();assertEquals(1,completed)
  } finally {f.vm.onBackground();HeySarahListenerService.status.value="off"}
  var stopWindow:()->Unit={}
  val unknown=fixture(abort={stopWindow()});unknown.mic.endpointReached=true;unknown.vm.onForeground()
  var valid=true;var recovery: Boolean?=null
  val uncertain=VisibleCommandHandoff({valid},{recovery=it})
  stopWindow={valid=false;uncertain.stop()}
  unknown.wire.onSubmit={throw java.net.SocketTimeoutException("private")}
  HeySarahListenerService.status.value="released"
  try {
   assertTrue(unknown.vm.acceptWake(uncertain));unknown.mic.end.complete(Unit);delay(30)
   assertEquals("uncertain",unknown.vm.ui.value.phase);assertEquals(false,recovery)
   val request=unknown.memory.value.getString("request")
   HeySarahListenerService.status.value="off";unknown.vm.checkExisting()
   assertEquals(1,unknown.wire.lookups);assertEquals(1,unknown.wire.posts)
   assertEquals(request,unknown.memory.value.getString("request"));assertEquals(0,unknown.rearms())
  } finally {valid=false;unknown.vm.onBackground();HeySarahListenerService.status.value="off"}
 }
 @Test fun visibleStopInvalidatesOwnerAndWaitsForCaptureFinally()=runBlocking {
  val f=fixture();f.vm.onForeground();var valid=true;var completed=0
  val released=CompletableDeferred<Unit>();f.mic.releaseGate=released
  val handoff=VisibleCommandHandoff({valid},{assertFalse(it);assertTrue(f.mic.joined);completed++})
  HeySarahListenerService.status.value="released"
  try {
   assertTrue(f.vm.acceptWake(handoff));valid=false;handoff.stop();delay(30)
   assertTrue(f.mic.discarded);assertEquals(0,completed);assertEquals(0,f.wire.posts)
   assertEquals("ready",f.vm.ui.value.phase)
   released.complete(Unit);delay(30);assertEquals(1,completed)
   f.mic.end.complete(Unit);assertEquals(0,f.rearms());handoff.complete(true);assertEquals(1,completed)
  } finally {released.complete(Unit);f.vm.onBackground();HeySarahListenerService.status.value="off"}
 }
 @Test fun visibleServerCancelUsesSingleCancelAndCompletesResolvedHandoff()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.row.put("state","thinking");f.vm.onForeground()
  var completed=0;var resolved=false
  val handoff=VisibleCommandHandoff({true},{completed++;resolved=it})
  HeySarahListenerService.status.value="released"
  try {
   assertTrue(f.vm.acceptWake(handoff));f.mic.end.complete(Unit);delay(30)
   assertEquals("polling",f.vm.ui.value.phase);assertEquals(0,completed)
   f.wire.row.put("state","cancelled");f.vm.cancelTurn();delay(30)
   assertEquals("cancelled",f.vm.ui.value.phase);assertEquals(1,f.wire.cancels)
   assertEquals(1,f.wire.posts);assertEquals(1,completed);assertTrue(resolved)
  } finally {f.vm.onBackground();HeySarahListenerService.status.value="off"}
 }
 @Test fun visibleKnownErrorAndCancellationReturnToListener()=runBlocking {
  for(phase in listOf("error","cancelled")) {
   val f=fixture();f.mic.endpointReached=true;f.wire.row.put("state",phase)
   f.vm.onForeground();assertTrue(f.vm.acceptWake());f.mic.end.complete(Unit);delay(30)
   assertEquals(phase,f.vm.ui.value.phase);assertEquals(1,f.wire.posts)
   assertEquals("resolved $phase must rearm",1,f.rearms())
  }
 }
 @Test fun wakeEndpointSubmitsOnceAndRearmsOnlyAfterTextReply()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.vm.onForeground()
  assertTrue(f.vm.acceptWake());assertFalse(f.vm.acceptWake());assertEquals("recording",f.vm.ui.value.phase)
  f.mic.end.complete(Unit)
  delay(150)
  assertEquals(1,f.captureStarts());assertEquals(1,f.wire.posts);assertEquals(1,f.mic.finished)
  assertEquals("done",f.vm.ui.value.phase);assertEquals(1,f.rearms())
 }
 @Test fun foregroundTapUsesSameEndpointAndNoSpeechNeverSends()=runBlocking {
  val spoken=fixture();spoken.mic.endpointReached=true;spoken.vm.onForeground();spoken.vm.startCapture()
  spoken.mic.end.complete(Unit);delay(50)
  assertEquals(1,spoken.wire.posts);assertEquals("done",spoken.vm.ui.value.phase)
  val silent=fixture();silent.mic.endpointReached=true;silent.mic.speechDetected=false
  silent.vm.onForeground();silent.vm.startCapture();silent.mic.end.complete(Unit);delay(50)
  assertEquals(0,silent.wire.posts);assertTrue(silent.mic.discarded)
 }
 @Test fun silenceAndBackgroundBeforeEndpointNeverSubmitOrRearm()=runBlocking {
  val silent=fixture();silent.mic.speechDetected=false;silent.vm.onForeground();assertTrue(silent.vm.acceptWake());silent.mic.end.complete(Unit);delay(100)
  assertTrue(silent.mic.discarded);assertEquals(0,silent.wire.posts);assertEquals(0,silent.rearms())
  val background=fixture();background.vm.onForeground();assertTrue(background.vm.acceptWake());background.vm.onBackground();delay(100)
  assertEquals(0,background.wire.posts);assertEquals(0,background.rearms())
 }
 @Test fun noTtsSelfWakeAndStopAudioPreventsRearm()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.row.put("audio",true);f.vm.onForeground();assertTrue(f.vm.acceptWake());f.mic.end.complete(Unit);delay(150)
  assertEquals("playing",f.vm.ui.value.phase);assertEquals(1,f.sound.played);assertEquals(0,f.rearms());assertFalse(f.vm.acceptWake())
  f.vm.stopAudio();f.sound.finish();assertEquals(0,f.rearms());assertEquals(1,f.wire.posts)
 }
 @Test fun successfulSpokenReplyRearmsOnlyAfterPlaybackRelease()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.row.put("audio",true)
  f.vm.onForeground();assertTrue(f.vm.acceptWake());f.mic.end.complete(Unit);delay(150)
  assertEquals("playing",f.vm.ui.value.phase);assertEquals(0,f.rearms())
  f.sound.finish();assertEquals("done",f.vm.ui.value.phase);assertEquals(1,f.rearms())
  f.sound.finish();assertEquals(1,f.rearms());assertEquals(1,f.wire.posts)
 }
 @Test fun interruptedTtsNeverRearms()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.row.put("audio",true)
  f.vm.onForeground();assertTrue(f.vm.acceptWake());f.mic.end.complete(Unit);delay(150)
  assertEquals("playing",f.vm.ui.value.phase)
  f.sound.finish(false);assertEquals("done",f.vm.ui.value.phase);assertEquals(0,f.rearms())
 }
 @Test fun ambiguousWakePostMustNotRearmAfterReadOnlyLookup()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.onSubmit={throw IOException("response lost")}
  f.vm.onForeground();assertTrue(f.vm.acceptWake());f.mic.end.complete(Unit);delay(150)
  assertEquals("uncertain",f.vm.ui.value.phase);assertEquals(0,f.rearms());assertEquals(1,f.wire.posts)
  f.vm.checkExisting();assertEquals(1,f.wire.lookups);assertEquals(0,f.rearms());assertEquals(1,f.wire.posts)
 }
 @Test fun repeatedConfirmationDuringProductionPostDoesNotSubmitSecondAction()=runBlocking {
  val f=fixture();f.mic.endpointReached=true
  f.wire.row=JSONObject().put("id","t1").put("conversation","c1").put("state","confirming")
   .put("confirmation",JSONObject().put("conversation","c1").put("nonce","n1").put("action_hash","h1"))
  f.vm.onForeground();f.vm.startCapture();f.mic.end.complete(Unit);delay(50)
  assertEquals("confirming",f.vm.ui.value.phase)
  f.wire.onConfirm={f.vm.confirm(true)}
  f.vm.confirm(true)
  assertEquals(1,f.wire.confirms)
  assertEquals(1,f.wire.posts)
 }
 @Test fun timedOutProductionPostPreservesRequestAndNoReplay()=runBlocking {
  val f=fixture();f.mic.endpointReached=true;f.wire.onSubmit={throw java.net.SocketTimeoutException("private backend secret")}
  f.vm.onForeground();f.vm.startCapture();f.mic.end.complete(Unit);delay(50)
  assertEquals("uncertain",f.vm.ui.value.phase)
  assertTrue(f.vm.ui.value.status.contains("Network timeout"))
  assertFalse(f.vm.ui.value.status.contains("private backend secret"))
  val request=f.memory.value.getString("request")
  f.vm.reconnect();assertEquals("uncertain",f.vm.ui.value.phase)
  assertTrue(f.vm.ui.value.status.contains("Check existing request"))
  assertTrue(f.vm.ui.value.status.contains("never resend"))
  assertEquals(request,f.memory.value.getString("request"))
  f.vm.startCapture();assertEquals(1,f.wire.posts)
  f.vm.checkExisting();assertEquals(1,f.wire.lookups);assertEquals(1,f.wire.posts)
 }
 @Test fun microphoneLeaseBlocksWakeHandoffUntilReleased() {
  val held=Any();assertTrue(AudioArbiter.acquire(held))
  try {val f=fixture();f.vm.onForeground();assertFalse(f.vm.acceptWake());assertEquals(0,f.captureStarts())}
  finally {AudioArbiter.release(held)}
 }
 @Test fun wakeRoleLossBlocksAcquisitionAndFinalization() {
  var held=false
  val f=fixture(eligible={wake->!wake || held});f.vm.onForeground();f.vm.startCapture(true)
  assertEquals(0,f.captureStarts())
  held=true;f.vm.startCapture(true);f.vm.send();held=false;f.mic.end.complete(Unit)
  assertEquals(0,f.wire.posts);assertTrue(f.mic.discarded)
 }
 @Test fun pendingAudioBlocksCaptureAndWaitsForReleaseAck() {
  val ack=CompletableDeferred<Unit>();val f=fixture(beforePlayback={ack.await()})
  f.vm.onForeground();f.wire.row.put("audio",true)
  f.wire.onAudio={assertEquals("reply_audio_pending",f.vm.ui.value.phase);assertFalse(f.vm.ui.value.canCapture);f.vm.startCapture();assertEquals(1,f.captureStarts())}
  f.vm.startCapture();f.vm.send();f.mic.end.complete(Unit)
  assertEquals("reply_audio_pending",f.vm.ui.value.phase);assertEquals(0,f.sound.played)
  ack.complete(Unit);assertEquals(1,f.sound.played);assertEquals("playing",f.vm.ui.value.phase)
 }
 @Test fun backgroundWhileAwaitingAudioReleaseNeverPlays() {
  val ack=CompletableDeferred<Unit>();val f=fixture(beforePlayback={ack.await()})
  f.vm.onForeground();f.wire.row.put("audio",true);f.vm.startCapture();f.vm.send();f.mic.end.complete(Unit)
  f.vm.onBackground();ack.complete(Unit)
  assertEquals(0,f.sound.played);assertFalse(f.vm.ui.value.canCapture)
 }
 @Test fun restoredPlayingStopsWithoutAudioReplay() {
  val f=fixture(persisted("playing"));assertEquals("done",f.vm.ui.value.phase)
  assertEquals("done",f.memory.value.getString("phase"));assertFalse(f.vm.ui.value.canCapture)
  assertEquals(0,f.sound.played)
  f.vm.onForeground();assertTrue(f.vm.ui.value.canCapture);assertEquals(0,f.sound.played)
 }
 @Test fun reconnectRevocationTlsOfflineNotReadyPreventsCapture() {
  val f=fixture();f.vm.onForeground();assertTrue(f.vm.ui.value.canCapture)
  for (failure in listOf(Bridge.Failure(403,"denied"),SSLHandshakeException("bad cert"),IOException("offline"),Bridge.Failure(503,"not ready"))) {
   f.wire.failure=failure;f.vm.reconnect();assertEquals("disconnected",f.vm.ui.value.phase)
   assertFalse(f.vm.ui.value.canCapture);f.vm.startCapture();assertEquals(0,f.mic.finished)
   f.wire.failure=null;f.vm.reconnect();assertTrue(f.vm.ui.value.canCapture)
  }
  f.wire.healthy=false;f.vm.reconnect();assertFalse(f.vm.ui.value.canCapture)
  f.vm.startCapture();assertEquals("disconnected",f.vm.ui.value.phase)
 }
 @Test fun duplicateTapWaitsForRecorderAndLostAdmissionReconcilesReadOnly() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture();f.vm.startCapture()
  assertEquals(1,f.captureStarts())
  assertEquals("recording",f.vm.ui.value.phase)
  f.vm.send();f.vm.send();assertEquals("finalizing",f.vm.ui.value.phase)
  assertEquals(0,f.wire.posts);assertEquals(0,f.mic.finished)
  f.wire.onSubmit={throw IOException("response lost")};f.mic.end.complete(Unit)
  assertEquals(1,f.wire.posts);assertEquals(1,f.mic.finished)
  assertEquals("uncertain",f.vm.ui.value.phase);assertTrue(f.memory.value.has("request"))
  f.vm.checkExisting();assertEquals(1,f.wire.lookups);assertEquals(1,f.wire.posts)
  assertEquals("done",f.vm.ui.value.phase)
 }
 @Test fun staleReplyAndBackgroundCaptureNeverSubmit() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture();f.vm.onBackground()
  assertTrue(f.mic.discarded);assertEquals(0,f.wire.posts)
  assertFalse(f.vm.ui.value.canCapture);f.vm.startCapture();assertEquals(0,f.wire.posts)
  val another=fixture();another.vm.onForeground();another.vm.startCapture();another.vm.send()
  another.vm.onBackground();another.mic.end.complete(Unit)
  assertEquals(0,another.wire.posts)
 }
 @Test fun staleSubmitCallbackCannotPublishAfterBackground() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture()
  f.wire.onSubmit={f.vm.onBackground()}
  f.vm.send();f.mic.end.complete(Unit)
  assertEquals(1,f.wire.posts);assertNotEquals("polling",f.vm.ui.value.phase)
  assertFalse(f.vm.ui.value.canCapture)
 }
 @Test fun reconnectDuringUploadPreservesUncertainAdmission() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture()
  f.wire.onSubmit={f.vm.reconnect()}
  f.vm.send();f.mic.end.complete(Unit)
  assertEquals("uncertain",f.vm.ui.value.phase);assertFalse(f.vm.ui.value.canCapture)
  f.vm.startCapture();f.vm.send();assertEquals(1,f.wire.posts)
  f.vm.checkExisting();assertEquals(1,f.wire.lookups);assertEquals(1,f.wire.posts)
 }
 @Test fun routeInterruptionDiscardsAndPermissionRevokeBlocksSend() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture();f.vm.routeInterrupted()
  assertTrue(f.mic.discarded);assertEquals(0,f.wire.posts)
  val revoked=fixture();revoked.vm.onForeground();revoked.vm.startCapture()
  revoked.mic.permissionRevoked=true;revoked.vm.send();revoked.mic.end.complete(Unit)
  assertEquals("error",revoked.vm.ui.value.phase);assertEquals(0,revoked.wire.posts)
 }
 @Test fun uncertainRestoreKeepsRequestForReadOnlyLookupAfterReconnect() {
  val initial=persisted("uncertain").put("request","r1");val f=fixture(initial)
  f.vm.onForeground();f.wire.failure=Bridge.Failure(403,"denied");f.vm.reconnect()
  assertFalse(f.vm.ui.value.canCapture);assertEquals("uncertain",f.memory.value.getString("phase"))
  f.wire.failure=null;f.vm.reconnect();assertEquals("uncertain",f.vm.ui.value.phase)
  f.vm.checkExisting();assertEquals(1,f.wire.lookups);assertEquals(0,f.wire.posts)
 }
 @Test fun activityMutationsBlockedThroughoutServiceOwnershipAndReconcileAfterRelease() {
  val initial=persisted("uncertain").put("request","admitted-request").put("turn","t1")
  val f=fixture(initial);f.vm.onForeground();val owner=Any()
  assertTrue(OffscreenOwnership.acquire(owner))
  try {
   val writes=f.memory.writes
   f.vm.newConversation();f.vm.checkExisting();f.vm.cancelTurn();f.vm.confirm(true)
   f.vm.clearLocal();f.vm.resetPairing();f.vm.stopAudio();f.vm.reconnect()
   assertEquals(writes,f.memory.writes)
   assertEquals("admitted-request",f.memory.value.getString("request"))
   assertEquals("c1",f.memory.value.getString("conversation"))
   assertEquals(0,f.wire.creates);assertEquals(0,f.wire.lookups)
   assertEquals(0,f.wire.cancels);assertEquals(0,f.wire.confirms)
  } finally {OffscreenOwnership.release(owner)}
  f.vm.syncAfterService();f.vm.checkExisting()
  assertEquals(1,f.wire.lookups)
  assertEquals("admitted-request",f.memory.value.getString("request"))
 }
 @Test fun ownershipArrivingInsideProductionSubmitBlocksStaleViewModelTurnSave() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture();f.vm.send()
  val owner=Any()
  f.wire.onSubmit={
   assertTrue(OffscreenOwnership.acquire(owner))
   f.vm.newConversation()
  }
  try {
   f.mic.end.complete(Unit)
   assertEquals(1,f.wire.posts)
   assertEquals(0,f.wire.creates)
   assertEquals("uploading",f.memory.value.getString("phase"))
   assertTrue(Identity.valid(f.memory.value.getString("request")))
   assertEquals("",f.memory.value.getString("turn"))
  } finally {OffscreenOwnership.release(owner)}
  f.vm.syncAfterService()
  assertEquals("uncertain",f.memory.value.getString("phase"))
 }
 @Test fun completedLeaseStillInvalidatesLateActivitySubmitCallback() {
  val f=fixture();f.vm.onForeground();f.vm.startCapture();f.vm.send()
  f.wire.onSubmit={val owner=Any();assertTrue(OffscreenOwnership.acquire(owner));OffscreenOwnership.release(owner)}
  f.mic.end.complete(Unit)
  assertEquals(1,f.wire.posts)
  assertEquals("uploading",f.memory.value.getString("phase"))
  f.vm.newConversation();assertEquals(0,f.wire.creates)
  f.vm.syncAfterService()
  assertEquals("uncertain",f.memory.value.getString("phase"))
  assertTrue(Identity.valid(f.memory.value.getString("request")))
 }
}
