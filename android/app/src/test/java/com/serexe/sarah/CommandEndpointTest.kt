package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.io.File

/** Synthetic PCM through the actual production endpoint, not mocked speech flags. */
class CommandEndpointTest {
 private class Input {
  var now=0L
  val endpoint=CommandEndpoint({now})
  fun pcm(ms:Int,voice:Boolean,chunkMs:Int=20) {
   var left=ms
   while(left>0) {
    val duration=minOf(left,chunkMs)
    val bytes=ByteArray(duration*32)
    if(voice) for(i in bytes.indices step 2) {
     val value=if((i/2)%32<16) 4096 else -4096
     bytes[i]=value.toByte();bytes[i+1]=(value shr 8).toByte()
    }
    now+=duration*1_000_000L
    endpoint.accept(bytes,bytes.size)
    left-=duration
   }
  }
 }
 @Test fun establishedSpeechFinishesSoonerThanOldFourSecondEndpoint() {
  val i=Input();i.pcm(1200,true);assertTrue(i.endpoint.speechDetected)
  i.pcm(1580,false);assertFalse(i.endpoint.reached)
  i.pcm(20,false);assertTrue(i.endpoint.reached)
 }
 @Test fun shortPhraseGetsLongerNaturalPauseAndRenewedSpeechResets() {
  val i=Input();i.pcm(400,true);i.pcm(1800,false)
  assertFalse(i.endpoint.reached)
  i.pcm(400,true);assertFalse(i.endpoint.reached)
  // Observed 1800 ms intra-command pause earns 800 ms margin: 2600 ms.
  i.pcm(2580,false);assertFalse(i.endpoint.reached)
  i.pcm(20,false);assertTrue(i.endpoint.reached)
 }
 @Test fun freshCommandDoesNotInheritPriorPauseEvidence() {
  val first=Input();first.pcm(400,true);first.pcm(1800,false);first.pcm(800,true)
  first.pcm(1600,false);assertFalse(first.endpoint.reached)
  val next=Input();next.pcm(1200,true);next.pcm(1600,false)
  assertTrue(next.endpoint.reached)
 }
 @Test fun shortCompletedSpeechEndsAtConservative2400ms() {
  val i=Input();i.pcm(400,true);i.pcm(2380,false);assertFalse(i.endpoint.reached)
  i.pcm(20,false);assertTrue(i.endpoint.reached)
 }
 @Test fun silenceAndScatteredClicksNeverBecomeSpeechOrSendAtCap() {
  val i=Input()
  repeat(20) {i.pcm(40,true);i.pcm(200,false)}
  i.pcm(30000,false)
  assertFalse(i.endpoint.speechDetected);assertFalse(i.endpoint.reached)
  val cap=CommandCaptureLimit(0,{i.now})
  assertTrue(cap.expired);assertEquals(0,cap.bytesAllowed(0,2048))
 }
 @Test fun continuousSpeechNeverEndpointsAndHardCapStillDiscards() {
  val i=Input();i.pcm(30000,true)
  assertTrue(i.endpoint.speechDetected);assertFalse(i.endpoint.reached)
  assertTrue(CommandCaptureLimit(0,{i.now}).expired)
 }
 @Test fun clockJumpWithoutRecordedQuietCannotPretendSpeechEnded() {
  val i=Input();i.pcm(1200,true);i.now+=10_000_000_000L
  assertFalse(i.endpoint.reached)
  i.pcm(100,false);assertFalse(i.endpoint.reached)
 }
 @Test fun realPcmDurationNotReadChunkCountControlsSpeechQualification() {
  for(chunk in listOf(5,20,64,100)) {
   val i=Input();i.pcm(200,true,chunk);assertFalse(i.endpoint.speechDetected)
   i.pcm(200,true,chunk);assertTrue(i.endpoint.speechDetected)
   i.pcm(2400,false,chunk);assertTrue(i.endpoint.reached)
  }
 }
 @Test fun observedNaturalPausesExtendButNeverExceed3200ms() {
  val i=Input();i.pcm(400,true);i.pcm(1800,false);i.pcm(800,true)
  i.pcm(2500,false);assertFalse(i.endpoint.reached)
  i.pcm(400,true);assertFalse(i.endpoint.reached)
  i.pcm(3180,false);assertFalse(i.endpoint.reached)
  i.pcm(20,false);assertTrue(i.endpoint.reached)
 }
 @Test fun subThresholdRoomNoiseDoesNotQualifyAsSpeech() {
  var now=0L;val endpoint=CommandEndpoint({now})
  val noise=ByteArray(640) {if(it%2==0) 100 else 0}
  repeat(1600) {now+=20_000_000L;endpoint.accept(noise,noise.size)}
  assertFalse(endpoint.speechDetected);assertFalse(endpoint.reached)
 }
 @Test fun cueExclusionFreshEndpointAndCapRemainInProductionCapture() {
  val source=File("src/main/java/com/serexe/sarah/Capture.kt").readText()
  assertTrue(source.indexOf("MicReadyCueGate.play(")<source.indexOf("endpoint.accept(chunk,n)"))
  assertTrue(source.contains("endpoint=CommandEndpoint(SystemClock::elapsedRealtimeNanos)"))
  assertTrue(source.contains("if(limit?.expired==true) {capped=true;break}"))
  assertTrue(source.contains("if(commandLimit && endpoint.reached) {endpointReached=true;break}"))
  assertTrue(source.indexOf("endpoint.accept(chunk,n)")<source.lastIndexOf("if(commandLimit && endpoint.reached)"))
 }
}
