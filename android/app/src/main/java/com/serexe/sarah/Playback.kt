package com.serexe.sarah

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.MediaDataSource
import android.os.Handler
import android.os.Looper

class Playback(private val context:Context,private val onDone:(Boolean)->Unit):AudioPlayback {
 private val manager=context.getSystemService(AudioManager::class.java)
 private val main=Handler(Looper.getMainLooper())
 private val completed:(Boolean)->Unit={success->main.post {onDone(success)}}
 private val ownership=PlaybackOwnership(dispatchCleanup={task->cleanupExecutor.execute(task)})
 /** Foreground callers keep existing policy; offscreen supplies scope + live safety checks. */
 @Volatile internal var eligibility:()->Boolean={true}
 private val attributes=AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
 override fun play(bytes:ByteArray) {
  check(ownership.play({eligibility()}) {id->ReplyResource(bytes,id)}) {"Playback cancelled"}
 }
 override fun stop() {ownership.stop()}
 internal fun stopAcknowledgement()=ownership.stop()
 private companion object {
  val cleanupExecutor=java.util.concurrent.Executors.newCachedThreadPool {r->Thread(r,"sarah-playback-release").apply {isDaemon=true}}
 }
 internal suspend fun stopAndAwait():Boolean {
  return CommandCleanup.await(null,{true},ownership.stop())
 }
 /** Holder is assigned before initialization: every partially initialized resource is reclaimed. */
 private inner class ReplyResource(private val bytes:ByteArray,private val id:Long):PlaybackOwnership.Resource {
  private var player:MediaPlayer?=null
  private var source:MediaDataSource?=null
  private var focus:AudioFocusRequest?=null
  private var acquired=false
  private var routesRegistered=false
  private val routes=object:AudioDeviceCallback() {
   override fun onAudioDevicesRemoved(removedDevices:Array<out AudioDeviceInfo>) {
    if(removedDevices.isNotEmpty()) ownership.finish(id,false,completed)
   }
  }
  override fun initialize() {
   check(AudioArbiter.acquire(this)) {"Audio busy"};acquired=true
   val request=AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT).setAudioAttributes(attributes)
    .setOnAudioFocusChangeListener({if(it<=0) ownership.finish(id,false,completed)},Handler(Looper.getMainLooper())).build()
   focus=request
   check(manager.requestAudioFocus(request)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {"Audio focus unavailable"}
   routesRegistered=true
   manager.registerAudioDeviceCallback(routes,Handler(Looper.getMainLooper()))
   val memory=bytes.copyOf()
   source=object:MediaDataSource() {
    override fun getSize():Long=memory.size.toLong()
    @Synchronized override fun readAt(position:Long,buffer:ByteArray,offset:Int,size:Int):Int {
     if(position<0 || position>=memory.size) return -1
     val n=minOf(size,memory.size-position.toInt());System.arraycopy(memory,position.toInt(),buffer,offset,n);return n
    }
    @Synchronized override fun close() {memory.fill(0)}
   }
   val p=MediaPlayer();player=p
   p.setAudioAttributes(attributes);p.setDataSource(source!!)
   p.setOnCompletionListener {ownership.finish(id,true,completed)}
   p.setOnErrorListener {_,_,_->ownership.finish(id,false,completed);true}
  }
  override fun prepare() {player!!.prepare()}
  override fun start() {player!!.start()}
  override fun close():Boolean {
   val p=player;player=null
   runCatching {p?.stop()}
   val released=runCatching {p?.release()}.isSuccess
   val abandoned=runCatching {focus?.let {manager.abandonAudioFocusRequest(it)}}.isSuccess;focus=null
   val unregistered=runCatching {if(routesRegistered) manager.unregisterAudioDeviceCallback(routes)}.isSuccess
   routesRegistered=false
   val erased=runCatching {source?.close()}.isSuccess;source=null
   val clean=released && abandoned && unregistered && erased
   if(acquired && clean) {AudioArbiter.release(this);acquired=false}
   return clean
  }
 }
}
