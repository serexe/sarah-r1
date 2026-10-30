package com.serexe.sarah

/** Local PCM activity/pause heuristic, NOT semantic completion or speech recognition.
 * State belongs to one capture only. No user profile, persistence, model or network.
 * 20 ms PCM16/16 kHz frames make thresholds independent of AudioRecord read size.
 * Require delivered quiet PCM AND monotonic quiet time: stalled reads cannot send.
 * Capture's independent 30 s discard-only watchdog remains authoritative.
 */
internal class CommandEndpoint(private val clock:()->Long) {
 private val frameSamples=Wav.RATE/50
 private var frameEnergy=0L
 private var frameCount=0
 private var voicedSamples=0L
 private var burstSamples=0L
 private var quietSamples=0L
 private var observedPauseMs=0L
 private var lastVoice:Long?=null
 var speechDetected=false;private set
 private val quietMs:Long get()=quietSamples*1000/Wav.RATE
 private val requiredQuietMs:Long get() {
  // A short/hesitant opening gets extra room; established speech can finish sooner.
  val base=if(voicedSamples*1000/Wav.RATE<800) 2400L else 1600L
  // Only a pause followed by renewed activity is evidence of an internal pause.
  return maxOf(base,observedPauseMs+800).coerceAtMost(3200)
 }
 val reached:Boolean get()=speechDetected && quietMs>=requiredQuietMs &&
  lastVoice?.let {clock()-it>=requiredQuietMs*1_000_000L}==true
 fun accept(pcm:ByteArray,count:Int) {
  require(count in 0..pcm.size && count%2==0)
  var i=0
  while(i<count) {
   val v=((pcm[i].toInt() and 255) or (pcm[i+1].toInt() shl 8)).toShort().toInt()
   frameEnergy+=kotlin.math.abs(v);frameCount++;i+=2
   if(frameCount==frameSamples) {
    if(frameEnergy/frameSamples>600) {
     if(speechDetected && quietMs>=200) observedPauseMs=maxOf(observedPauseMs,quietMs)
     if(!speechDetected && quietMs>=120) burstSamples=0
     quietSamples=0;voicedSamples+=frameSamples;burstSamples+=frameSamples
     if(burstSamples*1000/Wav.RATE>=320) speechDetected=true
     lastVoice=clock()
    } else {
     quietSamples+=frameSamples
     if(!speechDetected && quietMs>=120) {burstSamples=0;voicedSamples=0}
    }
    frameEnergy=0;frameCount=0
   }
  }
 }
}
