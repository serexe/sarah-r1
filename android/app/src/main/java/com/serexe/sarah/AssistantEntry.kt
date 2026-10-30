package com.serexe.sarah

import android.app.role.RoleManager
import android.content.Intent
import android.os.Build
import android.app.KeyguardManager
import android.content.Context
import android.service.voice.VoiceInteractionService
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService
import android.speech.RecognitionService
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.os.Bundle

/** No ambient recorder or implicit submission: system invocation opens the existing manual voice UI. */
internal fun assistantRoleStatus(available:Boolean, held:Boolean):String = when {
 !available -> "Assistant role unavailable on this device. Tap to talk still works."
 held -> "S.A.R.A.H is the default assistant. System gesture opens tap to talk."
 else -> "Not the default assistant. Tap to talk still works."
}

internal fun isAssistantInvocation(intent:Intent?):Boolean =
 intent?.action == Intent.ACTION_ASSIST || intent?.action == ACTION_SARAH_SESSION

internal const val ACTION_SARAH_SESSION = "com.serexe.sarah.action.SESSION"

/** One foreground launch per visible framework session; lockscreen launches are refused. */
internal class AssistantInvocationGate {
 private var launched=false
 fun claim(locked:Boolean):Boolean {
  if(locked || launched) return false
  launched=true
  return true
 }
 fun reset() {launched=false}
}

internal fun roleManager(context:Context):RoleManager? =
 if (Build.VERSION.SDK_INT >= 29) context.getSystemService(RoleManager::class.java) else null

/** The framework binds this only after selection; no hotword detector is started here. */
class SarahVoiceInteractionService:VoiceInteractionService()

class SarahSessionService:VoiceInteractionSessionService() {
 override fun onNewSession(args:Bundle?):VoiceInteractionSession = SarahSession(this)
}

class SarahSession(context:Context):VoiceInteractionSession(context) {
 private var launched=false
 override fun onShow(args:Bundle?,showFlags:Int) {
  super.onShow(args,showFlags)
  if (launched) return
  launched=true
  // Never read assist data or screenshot. Locked invocation never launches app or mic.
  if (context.getSystemService(KeyguardManager::class.java)?.isDeviceLocked == true) {
   hide();return
  }
  try {
   context.startActivity(Intent(context,MainActivity::class.java).apply {
    action=ACTION_SARAH_SESSION
    addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
   })
  } finally { hide() }
 }
 override fun onHide() {super.onHide();launched=false}
 override fun onHandleAssist(data:Bundle?,structure:android.app.assist.AssistStructure?,content:android.app.assist.AssistContent?) { /* deliberately ignored */ }
 override fun onHandleScreenshot(screenshot:android.graphics.Bitmap?) { /* deliberately ignored */ }
}

/** Required VIS metadata recognizer; SARAH does not expose its bridge capture as speech API. */
class SarahRecognitionService:RecognitionService() {
 override fun onStartListening(intent:Intent?,callback:Callback) {callback.error(SpeechRecognizer.ERROR_CLIENT)}
 override fun onStopListening(callback:Callback) {callback.error(SpeechRecognizer.ERROR_CLIENT)}
 override fun onCancel(callback:Callback) {callback.error(SpeechRecognizer.ERROR_CLIENT)}
}
