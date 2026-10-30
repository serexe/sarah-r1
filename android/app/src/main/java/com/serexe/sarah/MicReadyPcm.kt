package com.serexe.sarah

/** Short bounded PCM cue for the media output route; no assets, files, or stream-volume writes. */
internal object MicReadyPcm {
 const val RATE=16000
 const val DRAIN_MS=500L // 180 ms cue + acoustic tail, all mic PCM discarded.
 fun samples():ShortArray {
  val count=RATE*180/1000
  val attack=RATE*30/1000
  val release=RATE*90/1000
  return ShortArray(count) { i->
   // Raised-cosine edges have zero slope at both ends; no sharp click.
   val edge=minOf(1.0,i.toDouble()/attack,(count-1-i).toDouble()/release).coerceAtLeast(0.0)
   val envelope=(1.0-kotlin.math.cos(Math.PI*edge))/2.0
   val phase=2.0*Math.PI*392.0*i/RATE
   ((kotlin.math.sin(phase)+0.10*kotlin.math.sin(2.0*phase))*5600.0*envelope).toInt().toShort()
  }
 }
}
