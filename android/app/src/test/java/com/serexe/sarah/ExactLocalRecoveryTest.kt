package com.serexe.sarah

import android.app.Application
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.net.SocketTimeoutException
import java.security.MessageDigest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import java.util.concurrent.TimeUnit

/** Production controller + synthetic local state/HTTPS only; never a real phone or server. */
class ExactLocalRecoveryTest {
 private val request="12345678-1234-1234-1234-123456789abc"
 private val conversation="0123456789abcdef0123456789abcdef"
 private fun hash(value:String)=MessageDigest.getInstance("SHA-256").digest(value.toByteArray()).joinToString("") {"%02x".format(it)}.take(12)
 private fun target()=ExactLocalRecoveryTarget(hash(request),hash(conversation))
 private fun saved()=JSONObject().put("origin","https://fixture.invalid").put("token","x".repeat(48))
  .put("phase","uncertain").put("request",request).put("conversation",conversation).put("turn","")
  .put("audioNext",0).put("chunkInFlight",false).put("requestHttp",403).put("requestServerError","not_found")
  .put("requestPhase","status").put("requestFailure","access").put("fingerprint","preserved-audio-digest")
  .put("shownTranscript","previous-request").put("shownReply","previous-request").put("shownRecovery","previous-request")
  .put("audioAcks",JSONArray().put(JSONObject().put("turn","old-turn").put("next",3)))
  .put("actionReceipts",JSONObject().put("completed-action","keep"))
  .put("permissions",JSONObject().put("tools",true)).put("caNote","keep")
  .put("messages",JSONArray().put(JSONObject().put("who","YOU").put("text","existing history")))
 private class Memory(initial:JSONObject):StateStore {
  var value=JSONObject(initial.toString());var writes=0;var failSave=false
  override fun load()=JSONObject(value.toString())
  override fun save(value:JSONObject) {if(failSave) throw IOException("synthetic storage failure");writes++;this.value=JSONObject(value.toString())}
  override fun reset() {fail("Recovery must never reset storage")}
 }
 private class Wire:BridgePort {
  var lookups=0;var other=0;var onLookup:()->Unit={};var failure:Exception?=Bridge.Failure(403,"not_found")
  override fun health()=JSONObject().put("protocol",1).put("ready",true)
  override fun lookup(request:String):JSONObject {lookups++;onLookup();failure?.let {throw it};return JSONObject().put("id","admitted").put("state","done")}
  override fun create():String {other++;return "never"}
  override fun submit(conversation:String,request:String,wav:ByteArray):String {other++;return "never"}
  override fun poll(turn:String):JSONObject {other++;return JSONObject()}
  override fun pollChunks(turn:String,after:Int):JSONObject {other++;return JSONObject()}
  override fun audio(turn:String):ByteArray {other++;return byteArrayOf()}
  override fun audioChunk(turn:String,seq:Int):ByteArray {other++;return byteArrayOf()}
  override fun cancel(turn:String):JSONObject {other++;return JSONObject()}
  override fun confirm(turn:String,conversation:String,nonce:String,hash:String,accept:Boolean):JSONObject {other++;return JSONObject()}
 }
 private data class Fixture(val vm:SarahViewModel,val store:Memory,val wire:Wire,val scope:CoroutineScope)
 private fun fixture(initial:JSONObject=saved(),approval:ExactLocalRecoveryTarget=target(),port:BridgePort?=null):Fixture {
  val memory=Memory(initial);val wire=Wire();val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
  val vm=SarahViewModel(Application(),memory,{_,_,_->port ?: wire},{_->error("Recovery must not start capture")},
   {_->object:AudioPlayback {override fun play(bytes:ByteArray) {fail("No replay")};override fun stop() {}}},scope,Dispatchers.Unconfined,
   rearmListener={fail("Recovery must not rearm listener")},awaitPollSlot={fail("Recovery must not poll/ACK")},localRecoveryTarget=approval)
  vm.onForeground()
  return Fixture(vm,memory,wire,scope)
 }
 private fun unchanged(f:Fixture,before:String,writes:Int) {
  assertEquals(before,f.store.value.toString());assertEquals(writes,f.store.writes)
  assertEquals("uncertain",f.vm.ui.value.phase);assertFalse(f.vm.ui.value.canCapture);assertEquals(0,f.wire.other)
 }
 private fun close(f:Fixture) {f.vm.onBackground();f.scope.cancel();assertTrue(AudioArbiter.idle())}
 @Test fun exactExplicitRecoveryOnlyRemovesPointersAndPreservesEveryOtherRecordAcrossRecreate() {
  val f=fixture();assertEquals(0,f.wire.lookups) // Recreate/health never clears anything automatically.
  f.vm.diagnosticSnapshot(43);f.vm.shareDiagnostics(43);assertEquals(0,f.wire.lookups)
  val before=JSONObject(f.store.value.toString());val writes=f.store.writes
  f.vm.recoverApprovedLocalRequest()
  assertEquals(1,f.wire.lookups);assertEquals(writes+1,f.store.writes);assertEquals(0,f.wire.other)
  assertFalse(f.store.value.has("request"));assertFalse(f.store.value.has("turn"))
  assertEquals("ready",f.vm.ui.value.phase);assertTrue(f.vm.ui.value.canCapture)
  val removed=setOf("request","turn","phase","status")
  for(key in before.keys()) if(key !in removed) assertEquals("Must preserve $key",before.get(key).toString(),f.store.value.get(key).toString())
  assertEquals(before.length()-2+(if(before.has("status")) 0 else 1),f.store.value.length())
  assertTrue(f.vm.ui.value.status.contains("Nothing resent"));f.vm.recoverApprovedLocalRequest();assertEquals(1,f.wire.lookups)
  val recovered=JSONObject(f.store.value.toString());close(f)
  val recreated=fixture(recovered);assertEquals(0,recreated.wire.lookups);assertFalse(recreated.store.value.has("request"));assertEquals("ready",recreated.vm.ui.value.phase)
  assertEquals("existing history",recreated.vm.ui.value.transcript.single().second);assertEquals(0,recreated.wire.other);close(recreated)
 }
 @Test fun approvalMismatchAndMissingOrCoercedFieldsNeverQueryOrWrite() {
  val cases=listOf<Pair<String,Any?>>("request" to request.replace("a","b"),"conversation" to conversation.replace("a","b"),
   "request" to request.dropLast(1),"conversation" to conversation.dropLast(1),"turn" to "admitted", "turn" to null,
   "turn" to JSONObject.NULL,"audioNext" to 1,"audioNext" to "0","audioNext" to null,
   "chunkInFlight" to true,"chunkInFlight" to "false","chunkInFlight" to null,"requestHttp" to 401,"requestHttp" to "403",
   "requestServerError" to "unauthorized","requestServerError" to "other")
  for((key,value) in cases) {
   val state=saved();if(value==null) state.remove(key) else state.put(key,value)
   val f=fixture(state);val before=f.store.value.toString();val writes=f.store.writes
   f.vm.recoverApprovedLocalRequest();assertEquals("Rejected $key=$value",0,f.wire.lookups);unchanged(f,before,writes);close(f)
  }
  for(approval in listOf(ExactLocalRecoveryTarget("",""),ExactLocalRecoveryTarget(hash(request),""),ExactLocalRecoveryTarget("not-a-hash",hash(conversation)))) {
   val f=fixture(approval=approval);val before=f.store.value.toString();val writes=f.store.writes
   f.vm.recoverApprovedLocalRequest();assertEquals(0,f.wire.lookups);unchanged(f,before,writes);close(f)
  }
 }
 @Test fun freshDenialsNetworkAndMalformedFailuresDoNotUseCachedNotFound() {
  val failures=listOf(Bridge.Failure(403,"unauthorized"),Bridge.Failure(403,"invalid_identifier"),Bridge.Failure(403,"other"),
   Bridge.Failure(403,"not_found "),Bridge.Failure(404,"not_found"),Bridge.Failure(500,"not_found"),
   IOException("network"),SocketTimeoutException(),javax.net.ssl.SSLException("tls"),IllegalArgumentException("malformed"))
  for(failure in failures) {
   val f=fixture();f.wire.failure=failure;val before=f.store.value.toString();val writes=f.store.writes
   f.vm.recoverApprovedLocalRequest();assertEquals(1,f.wire.lookups);unchanged(f,before,writes);assertTrue(AudioArbiter.idle());close(f)
  }
 }
 @Test fun admittedRowNeverClearsOrManufacturesTurn() {
  val f=fixture();f.wire.failure=null;val before=f.store.value.toString();val writes=f.store.writes
  f.vm.recoverApprovedLocalRequest();assertEquals(1,f.wire.lookups);unchanged(f,before,writes);assertEquals("",f.store.value.getString("turn"));close(f)
 }
 @Test fun activeAudioListenerAndOffscreenLeaseBlockBeforeLookup() {
  for(listener in listOf("Wake listening","uploading","speaking","cleanup-failed")) {
   val f=fixture();val before=f.store.value.toString();val writes=f.store.writes
   try {HeySarahListenerService.status.value=listener;f.vm.recoverApprovedLocalRequest();assertEquals(0,f.wire.lookups);unchanged(f,before,writes)}
   finally {HeySarahListenerService.status.value="off";close(f)}
  }
  val f=fixture();val before=f.store.value.toString();val writes=f.store.writes;val audio=Any()
  assertTrue(AudioArbiter.acquire(audio))
  try {f.vm.recoverApprovedLocalRequest();assertEquals(0,f.wire.lookups);unchanged(f,before,writes)} finally {AudioArbiter.release(audio)}
  val lease=Any();assertTrue(OffscreenOwnership.acquire(lease))
  try {f.vm.recoverApprovedLocalRequest();assertEquals(0,f.wire.lookups);unchanged(f,before,writes)} finally {OffscreenOwnership.release(lease);close(f)}
 }
 @Test fun singleFlightReservesAudioAndNeverSendsAnyOtherOperation() {
  val f=fixture()
  f.wire.onLookup={assertFalse(AudioArbiter.acquire(Any()));f.vm.recoverApprovedLocalRequest();f.vm.checkExisting()}
  f.vm.recoverApprovedLocalRequest();assertEquals(1,f.wire.lookups);assertEquals(0,f.wire.other);assertEquals("ready",f.vm.ui.value.phase);close(f)
 }
 @Test fun changedDurableRequestPairingHistoryOrAcksCannotBeOverwritten() {
  for(key in listOf("request","conversation","token","origin","messages","audioAcks","actionReceipts")) {
   val f=fixture();val writes=f.store.writes
   f.wire.onLookup={f.store.value.put(key,"changed while GET outstanding")}
   f.vm.recoverApprovedLocalRequest();assertEquals(1,f.wire.lookups);assertEquals(writes,f.store.writes)
   assertEquals("changed while GET outstanding",f.store.value.getString(key));assertTrue(f.store.value.has("request"));assertEquals("uncertain",f.vm.ui.value.phase);assertFalse(f.vm.ui.value.canCapture);close(f)
  }
 }
 @Test fun ownershipEpochAndLocalHistoryChangesDuringLookupFailClosed() {
  val f=fixture();val before=f.store.value.toString();val writes=f.store.writes
  f.wire.onLookup={val lease=Any();assertTrue(OffscreenOwnership.acquire(lease));OffscreenOwnership.release(lease)}
  f.vm.recoverApprovedLocalRequest();unchanged(f,before,writes);close(f)
  val history=fixture();history.wire.onLookup={history.vm.clearLocal()};history.vm.recoverApprovedLocalRequest()
  assertTrue(history.store.value.has("request"));assertEquals("uncertain",history.vm.ui.value.phase);assertEquals(0,history.store.value.getJSONArray("messages").length());close(history)
 }
 @Test fun backgroundOrListenerChangeDuringLookupCannotClear() {
  val f=fixture();val before=f.store.value.toString();val writes=f.store.writes
  f.wire.onLookup={f.vm.onBackground()};f.vm.recoverApprovedLocalRequest();unchanged(f,before,writes);close(f)
  val listener=fixture();val old=listener.store.value.toString();val count=listener.store.writes
  try {listener.wire.onLookup={HeySarahListenerService.status.value="starting"};listener.vm.recoverApprovedLocalRequest();unchanged(listener,old,count)}
  finally {HeySarahListenerService.status.value="off";close(listener)}
 }
 @Test fun failedAtomicSaveKeepsMemoryAndDurableTrackingBlocked() {
  val f=fixture();val before=f.store.value.toString();val writes=f.store.writes;f.store.failSave=true
  f.vm.recoverApprovedLocalRequest();unchanged(f,before,writes);assertTrue(AudioArbiter.idle())
  f.store.failSave=false;f.vm.recoverApprovedLocalRequest();assertEquals(2,f.wire.lookups);assertEquals("ready",f.vm.ui.value.phase);assertFalse(f.store.value.has("request"));close(f)
 }
 @Test fun cancelledScopeCannotLeakAudioReservationOrClearTracking() {
  val f=fixture();val before=f.store.value.toString();val writes=f.store.writes
  f.scope.cancel();f.vm.recoverApprovedLocalRequest();unchanged(f,before,writes)
  assertEquals(0,f.wire.lookups);assertTrue(AudioArbiter.idle());close(f)
 }
 @Test fun realTlsTransportUsesOneBearerBoundReadOnlyGetAndFailsClosedOnUnauthorized() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Synthetic CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer();server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false);server.start()
  try {
   val api=Bridge("https://localhost:${server.port}","x".repeat(48),ca.certificate.encoded)
   for(error in listOf("unauthorized","not_found")) {
    server.enqueue(MockResponse().setBody("{\"protocol\":1,\"ready\":true}")) // Foreground health only, never recovery proof.
    val f=fixture(port=api);assertEquals("/v1/health",server.takeRequest(2,TimeUnit.SECONDS)!!.path)
    val before=f.store.value.toString();val writes=f.store.writes
    server.enqueue(MockResponse().setResponseCode(403).setBody("{\"error\":\"$error\"}"))
    f.vm.recoverApprovedLocalRequest()
    val get=server.takeRequest(2,TimeUnit.SECONDS)!!
    assertEquals("GET",get.method);assertEquals("/v1/requests/$request",get.path);assertEquals("Bearer ${"x".repeat(48)}",get.getHeader("Authorization"))
    assertEquals("no-store",get.getHeader("Cache-Control"));assertEquals(0L,get.bodySize)
    assertNull(get.getHeader("X-Audio-After"));assertNull(get.getHeader("Idempotency-Key"))
    if(error=="unauthorized") unchanged(f,before,writes) else {assertEquals("ready",f.vm.ui.value.phase);assertFalse(f.store.value.has("request"))}
    close(f)
   }
   assertEquals(4,server.requestCount)
  } finally {server.shutdown()}
 }
}
