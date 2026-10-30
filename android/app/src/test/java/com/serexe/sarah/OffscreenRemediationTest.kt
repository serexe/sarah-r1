package com.serexe.sarah

import android.app.NotificationManager
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import kotlinx.coroutines.*
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.util.concurrent.TimeUnit
import java.util.concurrent.CompletableFuture
import kotlin.coroutines.CoroutineContext

/** Production safety helpers, production Bridge, and production ViewModel paths. */
class OffscreenRemediationTest {
 @Test fun offscreenEmittedStagesPassProductionValidationButUnknownIsRejected() {
  val source=File("src/main/java/com/serexe/sarah/OffscreenCommand.kt").readText()
  // Read the production emitter, not a separately maintained test-only allowlist.
  val literal=Regex("stage\\(\\\"([^\\\"]+)\\\"\\)").findAll(source).map {it.groupValues[1]}.toSet()
  val cue=Regex("stage\\(if\\(cue==MicReadyCueGate.Result.OUTPUT_MUTED\\) \\\"([^\\\"]+)\\\" else \\\"([^\\\"]+)\\\"\\)")
   .find(source) ?: error("offscreen mic-ready branch missing")
  val emitted=literal+cue.groupValues.drop(1)+setOf("error","cancelled","uncertain") // row state branch
  assertTrue("starting stage missing from production emitter", "starting-command-mic" in emitted)
  assertTrue("muted stage missing from production emitter", "recording-media-muted" in emitted)
  val rejected=emitted.filter {runCatching {StageTrail.validate(it)}.isFailure}
  assertEquals("offscreen labels rejected by production stage validation", emptyList<String>(), rejected)
  assertThrows(IllegalArgumentException::class.java) {StageTrail.validate("unknown-stage")}
 }
 @Test fun cancelBeforeCommandDispatchStillRunsProductionFinallyAndRequiresNativeAck()=runBlocking {
  // Guard the production call site too: launchOwned's receiver is a CoroutineScope,
  // not the OffscreenCommand that acquired the identity-based lease.
  val commandSource=File("src/main/java/com/serexe/sarah/OffscreenCommand.kt").readText()
  assertTrue("cleanup must release acquired command, not coroutine scope",
   commandSource.contains("cleanupComplete=true;OffscreenOwnership.release(this@OffscreenCommand);finished()"))
  val queued=ArrayDeque<Runnable>()
  val dispatcher=object:CoroutineDispatcher() {
   override fun dispatch(context:CoroutineContext,block:Runnable) {queued.addLast(block)}
  }
  for(cancelBeforeLaunch in listOf(false,true)) for(ack in listOf(false,true)) {
   val owner=Any()
   val prior=OffscreenOwnership.releases.value
   assertTrue(OffscreenOwnership.acquire(owner))
   try {
    val scope=CoroutineScope(SupervisorJob()+dispatcher)
    if(cancelBeforeLaunch) scope.cancel() // Watchdog may stop between acquisition and launch.
    var entered=false
    var cleaned=false
    CommandCleanup.launchOwned(scope) {
     try {entered=true;delay(1000)} finally {
      cleaned=true
      val native=CommandCleanup.await(null,{ack},CompletableFuture.completedFuture(true))
      if(native) OffscreenOwnership.release(owner)
     }
    }
    scope.cancel() // Service Stop arrives before Main dispatcher runs coroutine.
    while(queued.isNotEmpty()) queued.removeFirst().run()
    assertTrue("production command entered try before Stop",entered)
    assertTrue("production command finally ran",cleaned)
    assertEquals(!ack,OffscreenOwnership.held())
    assertEquals(prior+if(ack) 1 else 0,OffscreenOwnership.releases.value)
   } finally {OffscreenOwnership.release(owner)}
  }
 }
 @Test fun recorderClockAndPcmBudgetRejectDispatcherDelay() {
  var now=1_000_000_000L
  val limit=CommandCaptureLimit(now,{now})
  assertEquals(2048,limit.bytesAllowed(0,2048))
  assertEquals(2,limit.bytesAllowed(Wav.MAX_SAMPLES*2-2,2048))
  now+=30_000_000_000L
  assertTrue(limit.expired)
  assertEquals(0,limit.bytesAllowed(0,2048))
  assertEquals(0,limit.bytesAllowed(Wav.MAX_SAMPLES*2,2048))
 }
 @Test fun silenceEndpointResetsAfterNewSpeechAndNeverCutsOngoingCommand() {
  var now=0L
  val endpoint=CommandEndpoint({now})
  val voice=ByteArray(2048) {if(it%2==0) 0 else 16}
  val quiet=ByteArray(2048)
  repeat(50) {now+=64_000_000L;endpoint.accept(quiet,quiet.size)}
  assertFalse(endpoint.speechDetected);assertFalse(endpoint.reached)
  repeat(5) {now+=64_000_000L;endpoint.accept(voice,voice.size)}
  assertTrue(endpoint.speechDetected)
  repeat(120) {now+=64_000_000L;endpoint.accept(voice,voice.size);assertFalse(endpoint.reached)}
  repeat(20) {now+=64_000_000L;endpoint.accept(quiet,quiet.size);assertFalse(endpoint.reached)}
  now+=64_000_000L;endpoint.accept(voice,voice.size);assertFalse(endpoint.reached)
  repeat(30) {now+=64_000_000L;endpoint.accept(quiet,quiet.size);assertFalse(endpoint.reached)}
  repeat(5) {now+=64_000_000L;endpoint.accept(quiet,quiet.size)}
  assertTrue(endpoint.reached)
 }
 @Test fun micReadyCueRequiresRecordingAndDrainsBeforePcmAdmission()=runBlocking {
  val events=mutableListOf<String>()
  assertEquals(MicReadyCueGate.Result.FAILED,MicReadyCueGate.play(false,false,{events.add("cue");true},{events.add("drain")}))
  assertTrue(events.isEmpty())
  assertEquals(MicReadyCueGate.Result.PLAYED,MicReadyCueGate.play(true,false,{events.add("cue");true},{events.add("drain")}))
  events.add("admit-pcm")
  assertEquals(listOf("cue","drain","admit-pcm"),events)
  assertEquals(MicReadyCueGate.Result.FAILED,MicReadyCueGate.play(true,false,{false},{error("must not drain absent cue")}))
  assertEquals(MicReadyCueGate.Result.OUTPUT_MUTED,MicReadyCueGate.play(true,true,
   {error("muted route must not queue cue")},{error("muted route must not drain")}) )
  assertEquals(listOf("cue","drain","admit-pcm"),events)
  assertThrows(IllegalStateException::class.java) {runBlocking {
   MicReadyCueGate.play(true,false,{throw IllegalStateException("audio output failed")},{error("no admission")})
  }}
  assertTrue(MicReadyCueGate.outputMuted(0,false))
  assertTrue(MicReadyCueGate.outputMuted(7,true))
  assertFalse(MicReadyCueGate.outputMuted(7,false))
  val pcm=MicReadyPcm.samples()
  assertEquals(MicReadyPcm.RATE*180/1000,pcm.size)
  assertTrue("cue shorter than 500 ms drain",pcm.size*1000/MicReadyPcm.RATE<MicReadyPcm.DRAIN_MS)
  assertEquals(0,pcm.first().toInt());assertEquals(0,pcm.last().toInt())
  val peak=pcm.maxOf {kotlin.math.abs(it.toInt())}
  assertTrue("audible but not aggressive peak: $peak",peak in 2500..6500)
  assertTrue("no clipping",pcm.all {it.toInt() in -6500..6500})
  assertTrue("positive and negative excursions",pcm.any {it>2000} && pcm.any {it< -2000})
  val mean=pcm.map {it.toInt()}.average()
  assertTrue("DC offset: $mean",kotlin.math.abs(mean)<35)
  val middle=pcm.slice(MicReadyPcm.RATE*55/1000 until MicReadyPcm.RATE*100/1000)
   .maxOf {kotlin.math.abs(it.toInt())}
  val head=pcm.take(MicReadyPcm.RATE*5/1000).maxOf {kotlin.math.abs(it.toInt())}
  val tail=pcm.takeLast(MicReadyPcm.RATE*5/1000).maxOf {kotlin.math.abs(it.toInt())}
  assertTrue("gentle rounded attack: $head vs $middle",head<middle/5)
  assertTrue("gentle rounded release: $tail vs $middle",tail<middle/10)
  val maxStep=(1 until pcm.size).maxOf { i->kotlin.math.abs(pcm[i].toInt()-pcm[i-1].toInt()) }
  assertTrue("no discontinuous edge or piercing transient: $maxStep",maxStep<1100)
  fun crossingFrequency(startMs:Int,endMs:Int):Double {
   val section=pcm.slice(MicReadyPcm.RATE*startMs/1000 until MicReadyPcm.RATE*endMs/1000)
   val crossings=section.zipWithNext().count {(a,b)->a<=0 && b>0}
   return crossings.toDouble()*1000/(endMs-startMs)
  }
  for ((start,end) in listOf(40 to 100,100 to 160)) {
   val frequency=crossingFrequency(start,end)
   assertTrue("stable low-pitch dominant frequency: $frequency Hz",frequency in 350.0..440.0)
  }
  // Production route and order are not a parallel mock cue path.
  val capture=File("src/main/java/com/serexe/sarah/Capture.kt").readText()
  assertTrue(capture.contains("AudioAttributes.USAGE_MEDIA"))
  assertTrue(capture.contains("AudioManager.STREAM_MUSIC"))
  assertFalse(capture.contains("STREAM_NOTIFICATION"))
  assertTrue(capture.indexOf("r.startRecording()")<capture.indexOf("MicReadyCueGate.play("))
  assertTrue(capture.indexOf("MicReadyCueGate.play(")<capture.indexOf("endpoint.accept(chunk,n)"))
  assertFalse(capture.contains("setStreamVolume("))
 }
 @Test fun notificationTransitionsFailClosedAtEveryCheck() {
  val allowed={permission:Boolean,enabled:Boolean,importance:Int?->NotificationAvailability.evaluate(permission,enabled,importance)}
  assertTrue(allowed(true,true,NotificationManager.IMPORTANCE_LOW))
  assertFalse(allowed(false,true,NotificationManager.IMPORTANCE_LOW)) // revoked at handoff
  assertFalse(allowed(true,false,NotificationManager.IMPORTANCE_LOW)) // disabled during capture
  assertFalse(allowed(true,true,NotificationManager.IMPORTANCE_NONE)) // muted before upload
  assertFalse(allowed(true,true,null)) // missing during playback
 }
 @Test fun sharedLeaseProtectsPersistentWritesAndOwnerAcrossInterleavings() {
  val first=Any();val second=Any();var request="older"
  assertTrue(OffscreenOwnership.acquire(first))
  try {
   assertFalse(OffscreenOwnership.acquire(second))
   OffscreenOwnership.guarded(first) {request="admitted"}
   assertThrows(IllegalStateException::class.java) {OffscreenOwnership.guarded(null) {request="erased"}}
   assertEquals("admitted",request)
   assertTrue(OffscreenOwnership.owns(first))
  } finally {OffscreenOwnership.release(first)}
  OffscreenOwnership.guarded(null) {assertEquals("admitted",request)}
 }
 @Test fun processStartupPurgesOnlyLegacyPlaintextReplies() {
  val directory=Files.createTempDirectory("sarah-reply-fixture").toFile()
  try {
   val old=File(directory,"reply-abcd.mp3").apply {writeText("synthetic private reply")}
   val unrelated=File(directory,"other.mp3").apply {writeText("keep")}
   purgeLegacyReplies(directory)
   assertFalse(old.exists());assertTrue(unrelated.exists())
   purgeLegacyReplies(directory)
  } finally {directory.listFiles()?.forEach {it.delete()};directory.delete()}
 }
 private fun server():Pair<MockWebServer,ByteArray> {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Synthetic CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer()
  server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false)
  server.start()
  return server to ca.certificate.encoded
 }
 @Test fun droppedTlsResponseDoesNotReplayPostAndLookupIsReadOnly() {
  val (server,ca)=server()
  try {
   val bridge=Bridge("https://localhost:${server.port}","x".repeat(48),ca)
   server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
   assertThrows(Exception::class.java) {runBlocking {bridge.submitCancellable("c1","request-1",Wav.encode(ByteArray(8000)))}}
   val post=server.takeRequest(3,TimeUnit.SECONDS)!!
   assertEquals("POST",post.method)
   assertEquals("request-1",post.getHeader("Idempotency-Key"))
   assertEquals("c1",post.getHeader("X-Conversation"))
   assertEquals(1,server.requestCount)
   server.enqueue(MockResponse().setBody("{\"id\":\"t1\",\"conversation\":\"c1\",\"state\":\"uncertain\"}"))
   assertEquals("uncertain",bridge.lookup("request-1").getString("state"))
   assertEquals("GET",server.takeRequest(3,TimeUnit.SECONDS)!!.method)
   assertEquals(2,server.requestCount)
  } finally {server.shutdown()}
 }
 @Test fun cancellationClosesProductionTlsCallAfterPostAdmission()=runBlocking {
  val (server,ca)=server()
  try {
   val bridge=Bridge("https://localhost:${server.port}","x".repeat(48),ca)
   server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
   val job=launch(Dispatchers.Default) {bridge.submitCancellable("c1","request-stop",Wav.encode(ByteArray(8000)))}
   val admitted=withContext(Dispatchers.IO) {server.takeRequest(3,TimeUnit.SECONDS)}!!
   assertEquals("request-stop",admitted.getHeader("Idempotency-Key"))
   withTimeout(2000) {job.cancelAndJoin()}
   assertEquals(1,server.requestCount)
  } finally {server.shutdown()}
 }
 @Test fun partialTlsResponseNeverReplaysAdmittedPost() {
  val (server,ca)=server()
  try {
   val bridge=Bridge("https://localhost:${server.port}","x".repeat(48),ca)
   server.enqueue(MockResponse().setBody("{\"turn\":\"synthetic-admitted\"}").setSocketPolicy(SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
   assertThrows(Exception::class.java) {runBlocking {bridge.submitCancellable("c1","response-cut",Wav.encode(ByteArray(8000)))}}
   val admission=server.takeRequest(3,TimeUnit.SECONDS)!!
   assertEquals("POST",admission.method)
   assertEquals("response-cut",admission.getHeader("Idempotency-Key"))
   assertEquals(1,server.requestCount)
  } finally {server.shutdown()}
 }
 @Test fun retryableTlsServiceResponseStillDoesNotReplayPost() {
  val (server,ca)=server()
  try {
   val bridge=Bridge("https://localhost:${server.port}","x".repeat(48),ca)
   server.enqueue(MockResponse().setResponseCode(503).addHeader("Retry-After","0").setBody("{\"error\":\"synthetic\"}"))
   server.enqueue(MockResponse().setBody("{\"turn\":\"must-not-reach\"}"))
   assertThrows(Bridge.Failure::class.java) {runBlocking {bridge.submitCancellable("c1","retry-guard",Wav.encode(ByteArray(8000)))}}
   assertEquals("retry-guard",server.takeRequest(3,TimeUnit.SECONDS)!!.getHeader("Idempotency-Key"))
   assertEquals(1,server.requestCount)
  } finally {server.shutdown()}
 }
}
