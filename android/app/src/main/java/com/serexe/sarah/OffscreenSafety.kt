package com.serexe.sarah

import android.Manifest
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/** Service lease is held through final cleanup. All Vault instances share the same lock. */
internal object OffscreenOwnership {
 internal class LeaseHeld:IllegalStateException("Offscreen command owns state")
 private var owner:Any?=null
 private var revision=0L
 private val released=MutableStateFlow(0L)
 val releases=released.asStateFlow()
 @Synchronized fun epoch():Long=revision
 @Synchronized fun acquire(candidate:Any):Boolean {if(owner!=null) return false;owner=candidate;revision++;return true}
 @Synchronized fun held():Boolean=owner!=null
 @Synchronized fun owns(candidate:Any):Boolean=owner===candidate
 @Synchronized fun release(candidate:Any) {if(owner===candidate) {owner=null;released.value=released.value+1}}
 @Synchronized fun <T> guarded(candidate:Any?,body:()->T):T {
  if(owner!=null && owner!==candidate) throw LeaseHeld()
  return body()
 }
}

internal object NotificationAvailability {
 const val CHANNEL="sarah-local-microphone"
 fun evaluate(permission:Boolean,enabled:Boolean,importance:Int?):Boolean=
  permission && enabled && importance!=null && importance>NotificationManager.IMPORTANCE_NONE
 fun allowed(context:Context):Boolean=try {
  val manager=context.getSystemService(NotificationManager::class.java)
  evaluate(Build.VERSION.SDK_INT<33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED,
   manager.areNotificationsEnabled(),manager.getNotificationChannel(CHANNEL)?.importance)
 } catch (_:Exception) {false}
}

/** Monotonic time plus PCM frame budget; thirty seconds is a discard-only safety bound. */
internal class CommandCaptureLimit(private val startedNanos:Long,private val clock:()->Long,
 private val maxNanos:Long=30_000_000_000L) {
 val expired:Boolean get()=clock()-startedNanos>=maxNanos
 fun bytesAllowed(current:Int,incoming:Int):Int {
  if(expired) return 0
  return minOf(incoming,((Wav.MAX_SAMPLES*2)-current).coerceAtLeast(0)) and -2
 }
}

/** Cue is permitted only after native recording is confirmed, before any PCM is kept. */
object MicReadyCueGate {
 enum class Result { PLAYED, OUTPUT_MUTED, FAILED }
 fun outputMuted(volume:Int,streamMuted:Boolean)=volume<=0 || streamMuted
 suspend fun play(recording:Boolean,muted:Boolean,start:()->Boolean,drain:suspend ()->Unit):Result {
  if(!recording) return Result.FAILED
  if(muted) return Result.OUTPUT_MUTED
  if(!start()) return Result.FAILED
  drain() // No command PCM is admitted until cue and acoustic tail have passed.
  return Result.PLAYED
 }
}