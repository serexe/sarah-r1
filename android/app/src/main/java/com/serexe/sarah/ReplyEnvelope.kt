package com.serexe.sarah

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaDataSource
import android.media.MediaExtractor
import android.media.MediaFormat
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.sqrt

/** Local reply bytes only. No microphone, loopback, Visualizer or audio-output changes. */
internal class ReplyEnvelope(private val bytes:ByteArray) {
 private val cancelled=AtomicBoolean(false)
 @Volatile private var levels:FloatArray?=null
 @Volatile private var started=false
 @Synchronized fun request() {
  if(started || cancelled.get()) return
  started=true
  executor.execute {
   if(!cancelled.get()) runCatching { decode() }.getOrNull()?.let { if(!cancelled.get()) levels=it }
  }
 }
 fun at(positionMs:Int):Float=if(cancelled.get()) 0f else levels?.getOrNull(positionMs.coerceAtLeast(0)/20) ?: 0f
 fun close() {cancelled.set(true);levels=null}
 private fun decode():FloatArray {
  val extractor=MediaExtractor()
  var codec:MediaCodec?=null
  val source=object:MediaDataSource() {
   override fun getSize()=bytes.size.toLong()
   override fun readAt(position:Long,buffer:ByteArray,offset:Int,size:Int):Int {
    if(position<0 || position>=bytes.size) return -1
    val n=minOf(size,bytes.size-position.toInt());System.arraycopy(bytes,position.toInt(),buffer,offset,n);return n
   }
   override fun close() {}
  }
  try {
   extractor.setDataSource(source)
   val track=(0 until extractor.trackCount).first {extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/")==true}
   extractor.selectTrack(track)
   val format=extractor.getTrackFormat(track)
   var rate=format.getInteger(MediaFormat.KEY_SAMPLE_RATE)
   var channels=format.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
   var encoding=AudioFormat.ENCODING_PCM_16BIT
   val decoder=MediaCodec.createDecoderByType(format.getString(MediaFormat.KEY_MIME)!!);codec=decoder
   decoder.configure(format,null,null,0);decoder.start()
   val bins=PcmEnvelopeBins()
   val info=MediaCodec.BufferInfo()
   var inputDone=false
   val deadline=System.nanoTime()+10_000_000_000L
   while(!cancelled.get() && System.nanoTime()<deadline) {
    if(!inputDone) {
     val index=decoder.dequeueInputBuffer(1000)
     if(index>=0) {
      val n=extractor.readSampleData(decoder.getInputBuffer(index)!!,0)
      if(n<0) {decoder.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);inputDone=true}
      else {decoder.queueInputBuffer(index,0,n,extractor.sampleTime,0);extractor.advance()}
     }
    }
    val out=decoder.dequeueOutputBuffer(info,1000)
    if(out==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
     val f=decoder.outputFormat;rate=f.getInteger(MediaFormat.KEY_SAMPLE_RATE);channels=f.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
     encoding=if(f.containsKey(MediaFormat.KEY_PCM_ENCODING)) f.getInteger(MediaFormat.KEY_PCM_ENCODING) else AudioFormat.ENCODING_PCM_16BIT
     check(encoding==AudioFormat.ENCODING_PCM_16BIT || encoding==AudioFormat.ENCODING_PCM_FLOAT)
    } else if(out>=0) {
     try {
      decoder.getOutputBuffer(out)?.let {buffer->
       buffer.position(info.offset);buffer.limit(info.offset+info.size)
       bins.add(buffer.slice().order(ByteOrder.LITTLE_ENDIAN),info.presentationTimeUs,rate,channels,encoding==AudioFormat.ENCODING_PCM_FLOAT)
      }
     } finally {decoder.releaseOutputBuffer(out,false)}
     // Publish bounded partial results so long replies need not finish decoding first.
     if(out>=0 && info.presentationTimeUs%200_000L<40_000L && !cancelled.get()) levels=bins.finish()
     if(info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM!=0 || info.presentationTimeUs>=120_000_000L) return bins.finish()
    }
   }
   return bins.finish()
  } finally {
   runCatching {codec?.stop()};runCatching {codec?.release()};extractor.release();source.close()
  }
 }
 private companion object {
  val executor=java.util.concurrent.Executors.newSingleThreadExecutor {r->Thread(r,"sarah-reply-envelope").apply {isDaemon=true}}
 }
}

/** 20 ms RMS bins, fixed memory, normalized display gain. Silence remains zero. */
internal class PcmEnvelopeBins {
 private val squares=DoubleArray(6000)
 private val counts=IntArray(6000)
 fun add(pcm:ByteBuffer,ptsUs:Long,rate:Int,channels:Int,floatPcm:Boolean=false) {
  if(rate<=0 || channels<=0) return
  var sample=0L
  val width=if(floatPcm) 4 else 2
  while(pcm.remaining()>=width) {
   val value=if(floatPcm) pcm.float.toDouble() else pcm.short.toDouble()/32768.0
   val bin=((ptsUs+(sample/channels)*1_000_000L/rate)/20_000L).toInt()
   if(bin in squares.indices && value.isFinite()) {squares[bin]+=value*value;counts[bin]++}
   sample++
  }
 }
 fun finish()=FloatArray(squares.size) {i->if(counts[i]==0) 0f else (sqrt(squares[i]/counts[i])*3.0).coerceIn(0.0,1.0).toFloat()}
}
