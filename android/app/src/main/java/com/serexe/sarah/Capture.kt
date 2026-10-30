package com.serexe.sarah

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.AudioManager
import android.media.AudioFocusRequest
import android.media.AudioAttributes
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

/** No file written. Stop/discard clears in-memory PCM; hard cap never auto-sends. */
class Capture(private val context:Context,private val onInterrupted:()->Unit = {},private val commandLimit:Boolean=false):AudioCapture {
 var onMicReady:(MicReadyCueGate.Result)->Unit = {}
 @Volatile private var recorder:AudioRecord?=null
 @Volatile internal var releaseComplete=true;private set
 private val buffer=ByteArrayOutputStream()
 @Volatile override var capped=false;private set
 private var endpoint=CommandEndpoint(SystemClock::elapsedRealtimeNanos)
 override val speechDetected:Boolean get()=endpoint.speechDetected
 @Volatile override var endpointReached=false;private set
 @Volatile private var stopping=false
 private val nativeStart=NativeStartOwnership()
 @Volatile private var interrupted=false
 @Volatile private var limit:CommandCaptureLimit?=null
 private val watchdog=if(commandLimit) Executors.newSingleThreadScheduledExecutor { task->Thread(task,"sarah-capture-cutoff").apply {isDaemon=true} } else null
 var eligibility:()->Boolean={AudioEligibility.allowed(context)}
 private fun eligible():Boolean {
  if(!eligibility() || !AudioEligibility.allowed(context)) return false
  if(android.os.Build.VERSION.SDK_INT>=29 && recorder?.activeRecordingConfiguration?.isClientSilenced==true) return false
  return true
 }
 private val silencing=object:AudioManager.AudioRecordingCallback() {
  override fun onRecordingConfigChanged(configs:MutableList<android.media.AudioRecordingConfiguration>) {
   val id=recorder?.audioSessionId ?: return
   if(android.os.Build.VERSION.SDK_INT>=29 && configs.any {it.clientAudioSessionId==id && it.isClientSilenced}) interrupt()
  }
 }
 private val manager=context.getSystemService(AudioManager::class.java)
 private val routes=object:AudioDeviceCallback() {
  override fun onAudioDevicesRemoved(removed:Array<out AudioDeviceInfo>) {if(removed.isNotEmpty() && !stopping) interrupt()}
 }
 private var focus:AudioFocusRequest?=null
 private fun interrupt() {interrupted=true;stop();onInterrupted()}
 @SuppressLint("MissingPermission")
 override suspend fun record()=withContext(Dispatchers.IO) {
  check(eligible())
  val min=AudioRecord.getMinBufferSize(Wav.RATE,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
  check(min>0) { "16 kHz PCM input unavailable" }
  check(AudioArbiter.acquire(this@Capture)) {"Audio busy"}
  releaseComplete=false
  val r=try {
   AudioRecord(MediaRecorder.AudioSource.MIC,Wav.RATE,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,maxOf(min,4096)).also {
    check(it.state==AudioRecord.STATE_INITIALIZED) {it.release();"16 kHz PCM input unavailable"}
   }
  } catch(e:Exception) { /* No release ACK if construction/release failed. */ throw e}
  recorder=r;buffer.reset();capped=false;endpointReached=false;endpoint=CommandEndpoint(SystemClock::elapsedRealtimeNanos)
  try {
   if(stopping) return@withContext
   val request=AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
    .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
    .setOnAudioFocusChangeListener {if(it<=0 && !stopping) interrupt()}.build()
   check(manager.requestAudioFocus(request)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {"Microphone audio focus unavailable"}
   focus=request
   manager.registerAudioDeviceCallback(routes,Handler(Looper.getMainLooper()))
   manager.registerAudioRecordingCallback(silencing,Handler(Looper.getMainLooper()))
   check(nativeStart.start({!stopping && coroutineContext.isActive && eligible()}) {
    r.startRecording()
    if(commandLimit) {
     limit=CommandCaptureLimit(SystemClock.elapsedRealtimeNanos(),SystemClock::elapsedRealtimeNanos)
     watchdog?.schedule({capped=true;stop()},30,TimeUnit.SECONDS)
    }
   })
   val chunk=ByteArray(2048)
   // Explicit media route, not notification/ringer volume. Reuse capture's assistant
   // focus and AudioArbiter owner; never change global stream volume or DND.
   val muted=MicReadyCueGate.outputMuted(manager.getStreamVolume(AudioManager.STREAM_MUSIC),
    manager.isStreamMute(AudioManager.STREAM_MUSIC))
   var cue:AudioTrack?=null
   try {
    val result=MicReadyCueGate.play(r.recordingState==AudioRecord.RECORDSTATE_RECORDING && eligible(),muted,
     {
      val pcm=MicReadyPcm.samples()
      AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
       .setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
       .setAudioFormat(AudioFormat.Builder().setSampleRate(MicReadyPcm.RATE)
        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
       .setTransferMode(AudioTrack.MODE_STATIC).setBufferSizeInBytes(pcm.size*2).build().also {track->
        cue=track
        // MODE_STATIC starts in STATE_NO_STATIC_DATA; write transitions to INITIALIZED.
        check(track.state==AudioTrack.STATE_NO_STATIC_DATA || track.state==AudioTrack.STATE_INITIALIZED)
        check(track.write(pcm,0,pcm.size)==pcm.size && track.state==AudioTrack.STATE_INITIALIZED)
        track.play()
       }
      true
     }) {
      val until=SystemClock.elapsedRealtime()+MicReadyPcm.DRAIN_MS
      while(SystemClock.elapsedRealtime()<until && !stopping && coroutineContext.isActive) {
       if(!eligible()) {interrupt();break}
       val count=r.read(chunk,0,chunk.size,AudioRecord.READ_NON_BLOCKING)
       if(count<0 && !stopping) throw IllegalStateException("Microphone interrupted")
       if(count==0) kotlinx.coroutines.delay(10)
      }
     }
    check(result!=MicReadyCueGate.Result.FAILED && !stopping && coroutineContext.isActive) {"Microphone readiness cue unavailable"}
    onMicReady(result) // Native recording confirmed; cue/tail excluded before any readiness claim.
   } finally {cue?.let {runCatching {it.stop()};it.release()}}
   while (coroutineContext.isActive && !capped && !stopping) {
    if(limit?.expired==true) {capped=true;break}
    if(!eligible()) {interrupt();break}
    val n=r.read(chunk,0,chunk.size,AudioRecord.READ_NON_BLOCKING)
    if(!eligible()) {interrupt();break}
    if(n==0) kotlinx.coroutines.delay(20)
    if (n<0 && !stopping) throw IllegalStateException("Microphone interrupted")
    if (n>0 && !stopping && limit?.expired!=true) synchronized(buffer) {
     endpoint.accept(chunk,n)
     val left=Wav.MAX_SAMPLES*2-buffer.size()
     val permitted=limit?.bytesAllowed(buffer.size(),n) ?: minOf(n,left)
     buffer.write(chunk,0,minOf(permitted,left));if (buffer.size()>=Wav.MAX_SAMPLES*2) capped=true
    }
    // Admit fresh PCM first, so renewed activity resets the pause before deciding.
    if(commandLimit && endpoint.reached) {endpointReached=true;break}
   }
   check(!interrupted) {"Microphone interrupted"}
  } catch(e:Exception) {interrupted=true;throw e}
  finally {
   recorder=null
   watchdog?.shutdownNow()
   try {r.stop()} catch (_:Exception) {}
   val released=runCatching {r.release()}.isSuccess
   run {
    val callbacks=runCatching {manager.unregisterAudioRecordingCallback(silencing)}.isSuccess
    val routesClosed=runCatching {manager.unregisterAudioDeviceCallback(routes)}.isSuccess
    val focusClosed=runCatching {focus?.let {manager.abandonAudioFocusRequest(it)}}.isSuccess;focus=null
    if(released && callbacks && routesClosed && focusClosed) {AudioArbiter.release(this@Capture);releaseComplete=true}
    else {interrupted=true;throw IllegalStateException("Capture cleanup failed")}
   }
  }
 }
 // READ_NON_BLOCKING loop owns native stop/release on IO; callers only invalidate.
 override fun stop() { nativeStart.cancel {stopping=true} }
 override fun finish():ByteArray=synchronized(buffer) {
  check(!interrupted && eligible() && !capped && buffer.size()<=Wav.MAX_SAMPLES*2) {"Microphone interrupted or command over limit"}
  val bytes=buffer.toByteArray();buffer.reset();Wav.encode(bytes)
 }
 override fun discard() { stop();synchronized(buffer) { buffer.reset() } }
}
