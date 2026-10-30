package com.serexe.sarah

import android.Manifest
import android.app.KeyguardManager
import android.app.role.RoleManager
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Build

/** Public API policy, rechecked at acquisition, each PCM chunk, and finalization. */
internal object AudioEligibility {
 fun allowed(context:Context, wake:Boolean=false):Boolean = try {
  val audio=context.getSystemService(AudioManager::class.java)
  context.checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED &&
   context.getSystemService(KeyguardManager::class.java)?.isDeviceLocked==false &&
   audio.mode==AudioManager.MODE_NORMAL && !audio.isMicrophoneMute &&
   (!wake || (Build.VERSION.SDK_INT>=29 && roleManager(context)?.isRoleHeld(RoleManager.ROLE_ASSISTANT)==true))
 } catch (_:Exception) {false}
}

/** One physical audio owner. Release only after actual resource cleanup. */
internal object AudioArbiter {
 private var owner:Any?=null
 @Synchronized fun acquire(candidate:Any):Boolean {if(owner!=null) return false;owner=candidate;return true}
 @Synchronized fun release(candidate:Any) {if(owner===candidate) owner=null}
 @Synchronized fun idle()=owner==null
}

/** Production stop boundary: cancellation precedes framework work; no off before release ACK. */
internal class ListenerSession(beforeNativeStart:()->Unit={},beforeNativeOperation:()->Unit={}) {
 val gate=ListenerGate()
 val nativeStart=NativeStartOwnership(beforeNativeStart,beforeNativeOperation)
 @Volatile var released=false;private set
 fun stopListening() {nativeStart.cancel {gate.stop()}}
 // Focus callback entry shared by service and deterministic pending-start test.
 fun onAudioFocusChange(change:Int) {if(change<=0) stopListening()}
 fun cancelBefore(frameworkStop:()->Unit) {stopListening();frameworkStop()}
 fun releaseAfter(cleanup:()->Boolean,eligible:()->Boolean,dispatch:()->Unit,acknowledged:()->Unit={}):Boolean {
  if(released) return true
  if(!runCatching {cleanup()}.getOrDefault(false)) {stopListening();return false}
  released=true
  AudioArbiter.release(this)
  acknowledged()
  val wake=gate.released() && eligible()
  if(wake) dispatch()
  return true
 }
}
