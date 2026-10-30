package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class ReplyEnvelopeTest {
 @Test fun speakingVisualGainDoublesHeightPreservesZeroAndClampsBounds() {
  assertEquals(0f,speakingWaveformHeightDp(0f),0f)
  for(level in listOf(.05f,.1f,.25f,.5f)) {
   assertEquals(level*38f*2f,speakingWaveformHeightDp(level),.0001f)
   assertTrue(speakingWaveformHeightDp(level)>level*38f)
   assertTrue(speakingWaveformHeightDp(level)<76f)
  }
  assertEquals(0f,speakingWaveformHeightDp(-1f),0f)
  assertEquals(76f,speakingWaveformHeightDp(1f),0f)
  assertEquals(76f,speakingWaveformHeightDp(2f),0f)
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
