package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class ReplyEnvelopeTest {
 @Test fun speakingVisualGainDoublesV34WithoutClippingAndPreservesZero() {
  assertEquals(0f,speakingWaveformHeightDp(0f),0f)
  for(step in 0..1000) {
   val level=step/1000f
   assertEquals(level*76f*2f,speakingWaveformHeightDp(level),.0001f)
   // Taper <= 1 and absolute wave <= .60 + .27 + .13 = 1.
   // Thus this includes every time, both paths and the widest 18dp stroke.
   assertTrue(speakingWaveformHeightDp(level)+9f<=WAVEFORM_CANVAS_HEIGHT_DP/2f)
  }
  assertEquals(0f,speakingWaveformHeightDp(-1f),0f)
  assertEquals(152f,speakingWaveformHeightDp(1f),0f)
  assertEquals(152f,speakingWaveformHeightDp(2f),0f)
 }
 private fun pcm(value:Short)=ByteBuffer.allocate(640).order(ByteOrder.LITTLE_ENDIAN).apply {repeat(320) {putShort(value)};flip()}
 @Test fun silenceRemainsZeroAndRealPcmRaisesEnvelopeAtCorrectPosition() {
  val bins=PcmEnvelopeBins()
  bins.add(pcm(0),0,16000,1)
  bins.add(pcm(8192),20000,16000,1)
  val levels=bins.finish()
  assertEquals(0f,levels[0],0f)
  assertEquals(.75f,levels[1],.001f)
  assertEquals(0f,levels[2],0f)
 }
 @Test fun stoppedOrFailedMeterRemainsZeroWithoutDecoder() {
  val envelope=ReplyEnvelope(byteArrayOf())
  assertEquals(0f,envelope.at(20),0f)
  envelope.close();envelope.request()
  assertEquals(0f,envelope.at(20),0f)
 }
 @Test fun stereoAndFloatPcmUseFrameTimestampsAndClamp() {
  val bins=PcmEnvelopeBins()
  val pcm=ByteBuffer.allocate(160*2*4).order(ByteOrder.LITTLE_ENDIAN)
  repeat(160) {pcm.putFloat(-.5f);pcm.putFloat(.5f)};pcm.flip()
  bins.add(pcm,40000,8000,2,true)
  val levels=bins.finish()
  assertEquals(0f,levels[1],0f)
  assertEquals(1f,levels[2],0f)
  assertEquals(0f,levels[3],0f)
 }
 @Test fun newEnvelopeDoesNotRetainPreviousReplyLevels() {
  val loud=PcmEnvelopeBins();loud.add(pcm(16000),0,16000,1)
  assertTrue(loud.finish()[0]>0f)
  assertEquals(0f,PcmEnvelopeBins().finish()[0],0f)
 }
}
