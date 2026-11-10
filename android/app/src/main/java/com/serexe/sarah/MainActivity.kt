package com.serexe.sarah

import android.Manifest
import android.app.KeyguardManager
import android.app.role.RoleManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.AudioManager
import android.os.Bundle
import android.provider.Settings
import android.net.Uri
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val charcoal=Color(0xff151817)
private val surfaceDark=Color(0xff202523)
private val orange=Color(0xffff742e)
private val cream=Color(0xfff5f3ed)
private val sage=Color(0xffb6c9b6)
class MainActivity:ComponentActivity() {
 private val vm by viewModels<SarahViewModel>()
 private var roleAvailable by mutableStateOf(false)
 private var roleHeld by mutableStateOf(false)
 private var assistantOpened by mutableStateOf(false)
 private var receiverRegistered=false
 private fun assistantSettings() {try {startActivity(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))} catch (_:Exception) {try {startActivity(Intent(Settings.ACTION_SETTINGS))} catch (_:Exception) {}}}
 private val roleRequest=registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {refreshRole();if(!roleHeld) assistantSettings()}
 private fun refreshRole() {
  if(Build.VERSION.SDK_INT<29) {roleAvailable=false;roleHeld=false;return}
  val manager=roleManager(this)
  roleAvailable=manager?.isRoleAvailable(RoleManager.ROLE_ASSISTANT)==true
  roleHeld=roleAvailable && manager?.isRoleHeld(RoleManager.ROLE_ASSISTANT)==true
 }
 private fun locked()=getSystemService(KeyguardManager::class.java)?.isDeviceLocked==true
 private val interruptions=object:BroadcastReceiver() {
  override fun onReceive(context:Context?,intent:Intent?) {
   when(intent?.action) {
    Intent.ACTION_SCREEN_OFF -> {HeySarahListenerService.visible=false;vm.onBackground()}
    AudioManager.ACTION_AUDIO_BECOMING_NOISY -> {HeySarahListenerService.stop(this@MainActivity);vm.routeInterrupted()}
   }
  }
 }
 override fun onCreate(savedInstanceState:Bundle?) {
  super.onCreate(savedInstanceState)
  if(locked()) {finish();return}
  assistantOpened=isAssistantInvocation(intent)
  refreshRole()
  setContent {
   val colors=darkColorScheme(primary=Color(0xffc4b3df),onPrimary=Color(0xff231e2e),background=Color(0xff15141c),onBackground=Color(0xfff0edf6),surface=Color(0xff211e2b),onSurface=Color(0xfff0edf6))
   MaterialTheme(colorScheme=colors) { SarahScreen(vm,roleAvailable,roleHeld,assistantOpened) {
    if(Build.VERSION.SDK_INT>=29) {
     val manager=roleManager(this)
     if(manager?.isRoleAvailable(RoleManager.ROLE_ASSISTANT)==true && !manager.isRoleHeld(RoleManager.ROLE_ASSISTANT))
      try {roleRequest.launch(manager.createRequestRoleIntent(RoleManager.ROLE_ASSISTANT))} catch (_:Exception) {assistantSettings()}
     else if(!roleHeld) assistantSettings()
    }
   } }
  }
 }
 override fun onNewIntent(intent:Intent) {super.onNewIntent(intent);setIntent(intent);if(locked()) {finish();return};assistantOpened=isAssistantInvocation(intent)}
 override fun onResume() {super.onResume();if(locked()) {finish();return};refreshRole();HeySarahListenerService.visible=true
  HeySarahListenerService.onWake={
   if(locked() || !getSystemService(android.os.PowerManager::class.java).isInteractive || !HeySarahListenerService.visible) false else vm.acceptWake(HeySarahListenerService.visibleHandoff()).also {accepted->
    if(accepted) runCatching {getSystemService(Vibrator::class.java)?.vibrate(VibrationEffect.createOneShot(60,VibrationEffect.DEFAULT_AMPLITUDE))}
   }
  }
 }
 override fun onPause() {HeySarahListenerService.visible=false;HeySarahListenerService.onWake=null;super.onPause()}
 override fun onStart() {super.onStart();if(locked()) {finish();return};vm.onForeground();registerReceiver(interruptions,IntentFilter().apply {addAction(Intent.ACTION_SCREEN_OFF);addAction(AudioManager.ACTION_AUDIO_BECOMING_NOISY)});receiverRegistered=true}
 override fun onStop() {HeySarahListenerService.visible=false;if(receiverRegistered) {unregisterReceiver(interruptions);receiverRegistered=false};vm.onBackground();super.onStop()}
}
@Composable private fun SarahScreen(vm:SarahViewModel,roleAvailable:Boolean,roleHeld:Boolean,assistantOpened:Boolean,onRequestRole:()->Unit) {
 val ui by vm.ui.collectAsStateWithLifecycle();val context=LocalContext.current
 var showSettings by rememberSaveable { mutableStateOf(false) }
 var showAbout by rememberSaveable { mutableStateOf(false) }
 var advanced by rememberSaveable { mutableStateOf(false) }
 var confirmClear by remember { mutableStateOf(false) }
 BackHandler(enabled=showAbout || showSettings) {if(showAbout) showAbout=false else showSettings=false}
 var url by remember { mutableStateOf("") };var token by remember { mutableStateOf("") };var ca by remember { mutableStateOf<ByteArray?>(null) }
 var caStatus by remember { mutableStateOf("System trust only") }
 var permissionDenied by remember { mutableStateOf(false) };var confirmNew by remember {mutableStateOf(false)};var confirmReset by remember {mutableStateOf(false)}
 val listener by HeySarahListenerService.status.collectAsStateWithLifecycle()
 LaunchedEffect(listener) {if(listener=="off") vm.syncAfterService()}
 var listenerConsent by remember {mutableStateOf(false)}
 var listenerPermissionReady by remember {mutableStateOf(false)}
 val mic=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if(granted && HeySarahListenerService.status.value=="off") {permissionDenied=false;vm.startCapture()} else permissionDenied=true }
 val listenerPermission=rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { granted ->
  // Android may deliver this before onResume/reconnect. Never drop or replay a start
  // across that boundary: permission grant requires a new visible confirmation.
  listenerPermissionReady=ListenerPermissionFlow.permissionResult(
   (if(Build.VERSION.SDK_INT>=33) arrayOf(Manifest.permission.RECORD_AUDIO,Manifest.permission.POST_NOTIFICATIONS)
    else arrayOf(Manifest.permission.RECORD_AUDIO)).all {granted[it]==true})==ListenerPermissionFlow.Action.CONFIRM_AGAIN
 }
 val startListener={listenerConsent=true}
 val musicPermission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { /* User must retry voice request after grant. */ }
 val certPicker=rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
  if(uri!=null) try {
   context.contentResolver.openInputStream(uri)?.use {stream-> val bytes=Bounded.read(stream,65536);require(bytes.isNotEmpty());ca=bytes;caStatus="Private CA selected (certificate only)" }
  } catch (_:Exception) {ca=null;caStatus="Certificate rejected or too large"}
 }
 val bg=MaterialTheme.colorScheme.background;val fg=MaterialTheme.colorScheme.onBackground
 Surface(color=bg,modifier=Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
  Box(Modifier.fillMaxSize()) {
   if(showAbout) AboutPage(context,vm) {showAbout=false}
   else if(showSettings || !ui.hasConfig) Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal=20.dp)) {
    if(ui.hasConfig) TextButton(onClick={showSettings=false},modifier=Modifier.heightIn(min=48.dp)) {Text("‹ Back to Sarah")}
    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
     Text("Settings",style=MaterialTheme.typography.titleLarge,modifier=Modifier.weight(1f))
     TextButton(onClick={showAbout=true}) {Text("About")}
    }
    Text("Connection",style=MaterialTheme.typography.titleMedium)
    Status(ui)
    if(ui.hasConfig) OutlinedButton(onClick=vm::reconnect,modifier=Modifier.heightIn(min=48.dp)) {Text("Check connection")}
    Spacer(Modifier.height(12.dp))
    Text("Voice & listener",style=MaterialTheme.typography.titleMedium)
    Text("Phone-local music uses only audio already in this phone's shared library. No radio or cloud catalog is connected.",style=MaterialTheme.typography.bodySmall)
    if(!PhoneMedia.hasLibraryPermission(context)) OutlinedButton(onClick={musicPermission.launch(if(Build.VERSION.SDK_INT>=33) Manifest.permission.READ_MEDIA_AUDIO else Manifest.permission.READ_EXTERNAL_STORAGE)}) {Text("Allow phone music library")}
    else Text("Phone music library access granted",style=MaterialTheme.typography.bodySmall)
    AssistantSetup(roleAvailable,roleHeld,assistantOpened,onRequestRole)
    ListenerControls(listener,ui,ui.canCapture && AssistantWakePolicy.roleSatisfied(context),listenerPermissionReady,startListener,{HeySarahListenerService.stop(context);vm.discard()})
    if(!ui.hasConfig) Column {
     Text("Enter HTTPS bridge origin and separate revocable Android device token. No provider or smart-home credentials.",color=fg)
     Spacer(Modifier.height(18.dp))
     OutlinedTextField(url,{url=it},label={Text("HTTPS bridge address")},placeholder={Text("https://companion.example.invalid")},singleLine=true,modifier=Modifier.fillMaxWidth(),keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Uri))
     Spacer(Modifier.height(12.dp))
     OutlinedTextField(token,{token=it},label={Text("Device token")},visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth())
     Spacer(Modifier.height(12.dp))
     Text(caStatus,color=fg)
     TextButton(onClick={certPicker.launch(arrayOf("application/x-x509-ca-cert","application/pkix-cert","application/octet-stream","*/*"))},modifier=Modifier.heightIn(min=48.dp)) {Text("Import private CA certificate")}
     Text("Optional CA replaces system trust for this connection; normal hostname verification remains required.",style=MaterialTheme.typography.bodySmall)
     Spacer(Modifier.height(12.dp))
     Button(onClick={vm.configure(url,token,ca)},modifier=Modifier.fillMaxWidth().heightIn(min=60.dp)) {Text("Save & connect")}
     if(ui.status.startsWith("Secure storage unavailable")) TextButton(onClick={confirmReset=true}) {Text("Reset inaccessible local pairing")}
    }
    TextButton(onClick={advanced=!advanced},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text(if(advanced) "Advanced ⌄" else "Advanced ›")}
    if(advanced) Column {
     TextButton(onClick={context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:${context.packageName}")))},modifier=Modifier.heightIn(min=48.dp)) {Text("Android app permissions")}
     if(ui.hasConfig) {
      TextButton(onClick={confirmNew=true},modifier=Modifier.heightIn(min=48.dp)) {Text("New server conversation…")}
      TextButton(onClick={confirmClear=true},modifier=Modifier.heightIn(min=48.dp)) {Text("Clear local history…")}
      TextButton(onClick={confirmReset=true},modifier=Modifier.heightIn(min=48.dp)) {Text("Reset local pairing…")}
     }
    }
   } else CompanionScreen(ui,listener,vm,{showSettings=true},startListener,
    {HeySarahListenerService.stop(context);vm.discard()},
    {mic.launch(Manifest.permission.RECORD_AUDIO)},permissionDenied,
    {context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,Uri.parse("package:${context.packageName}")))})

   if(listenerConsent) AlertDialog(onDismissRequest={listenerConsent=false},title={Text("Enable persistent local ${WakePhrase.display}?")},text={Text("Until you explicitly Stop, a foreground microphone service listens locally even after closing or swiping away the app. Android shows an ongoing microphone notification and privacy indicator; continuous listening and CPU wake lock use battery. No wake buffer is saved/uploaded. On an unlocked wake, the listener microphone releases before command recording with a readiness chime, an adaptive 1.6–3.2-second silence endpoint after speech, and a 30-second discard-only safety cap; a completed command is sent once to the paired bridge; reply may play aloud. If bridge explicitly asks for a clarification, microphone may reopen after speech for one 9-second answer window in same conversation; silence returns to wake listening. No confirmation or action approval by spoken answer. Without persistent opt-in, tap microphone manually to answer. Locked wake only notifies: no unlock bypass, recording, or automatic confirmation. OS process death, reboot, or Force stop ends listening until a visible new opt-in. Black-screen phone behavior remains unverified.")},confirmButton={TextButton(onClick={
    listenerConsent=false
    val required=if(Build.VERSION.SDK_INT>=33) arrayOf(Manifest.permission.RECORD_AUDIO,Manifest.permission.POST_NOTIFICATIONS) else arrayOf(Manifest.permission.RECORD_AUDIO)
    when(ListenerPermissionFlow.confirmed(required.all {context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED})) {
     ListenerPermissionFlow.Action.START -> {listenerPermissionReady=false;HeySarahListenerService.start(context,vm.ui.value.canCapture && AssistantWakePolicy.roleSatisfied(context))}
     ListenerPermissionFlow.Action.REQUEST_PERMISSION -> {listenerPermissionReady=false;listenerPermission.launch(required)}
     else -> Unit
    }
   }) {Text("Enable until Stop")}},dismissButton={TextButton(onClick={listenerConsent=false}) {Text("Not now")}})
   if(confirmNew) AlertDialog(onDismissRequest={confirmNew=false},title={Text("New server conversation?")},text={Text("Recording will be discarded. Pending server work may continue; this will not undo actions. A separate conversation is created.")},confirmButton={TextButton(onClick={confirmNew=false;vm.newConversation()}) {Text("Create new")}},dismissButton={TextButton(onClick={confirmNew=false}) {Text("Keep current")}})
   if(confirmClear) AlertDialog(onDismissRequest={confirmClear=false},title={Text("Clear local history?")},text={Text("Only this device's visible transcript is cleared. Server conversations, pending work, and actions are not deleted or undone.")},confirmButton={TextButton(onClick={confirmClear=false;vm.clearLocal()}) {Text("Clear local history")}},dismissButton={TextButton(onClick={confirmClear=false}) {Text("Keep")}})
   if(confirmReset) AlertDialog(onDismissRequest={confirmReset=false},title={Text("Clear local pairing?")},text={Text("Local token, transcript, and request identity will be erased. Server conversations and actions are not deleted. Ask bridge administrator for a new device token.")},confirmButton={TextButton(onClick={confirmReset=false;vm.resetPairing()}) {Text("Clear pairing")}},dismissButton={TextButton(onClick={confirmReset=false}) {Text("Keep")}})
  }
 }
}
@Composable private fun CompanionScreen(ui:SarahViewModel.Ui,listener:String,vm:SarahViewModel,onSettings:()->Unit,onListener:()->Unit,onStopListener:()->Unit,onMic:()->Unit,denied:Boolean,onPermissions:()->Unit) {
 var expanded by rememberSaveable {mutableStateOf(false)}
 val context=LocalContext.current
 val scope=rememberCoroutineScope()
 var alertError by remember {mutableStateOf(false)}
 var scheduleReadError by remember {mutableStateOf(false)}
 val localTimers by produceState(initialValue=Pair(emptyList<ScheduleEntry>(),System.currentTimeMillis()),context) {
  while(true) {
   val loaded=withContext(Dispatchers.IO) {runCatching {localSchedule(context).list("timer")}}
   scheduleReadError=loaded.isFailure
   if(loaded.isSuccess) value=Pair(loaded.getOrThrow(),System.currentTimeMillis())
   delay(1000)
  }
 }
 val ringing by produceState(initialValue=emptyList<ScheduleEntry>(),context) {
  while(true) {
   value=withContext(Dispatchers.IO) {runCatching {localSchedule(context).list().filter {it.state=="ringing"}}.getOrDefault(emptyList())}
   delay(1000)
  }
 }
 val counting=localTimers.first.filter {it.state=="active" || it.state=="delivering"}
 val state=when(ui.phase) {
  "recording" -> if(ui.status.startsWith("Starting microphone")) "Starting microphone" else "Listening"
  "playing" -> "Speaking"
  "polling" -> when {
   ui.status.startsWith("Server: thinking") -> "Thinking"
   ui.status.startsWith("Server: transcribing") -> "Transcribing"
   ui.status.startsWith("Server: acting") -> "Working"
   else -> "Waiting for Sarah"
  }
  "finalizing","uploading" -> "Sending"
  "reply_audio_pending" -> "Preparing audio"
  "confirming" -> "Confirmation needed"
  "cancelling" -> "Stopping"
  "ready","done","cancelled" -> if(ui.canCapture) "Ready" else "Not connected"
  "error" -> "Needs attention"
  "uncertain" -> "Outcome uncertain"
  else -> "Connecting"
 }
 if(BuildConfig.FLAVOR=="lenovo") {
  LenovoResponseScreen(ui,listener,vm,state,expanded,{expanded=!expanded},onSettings,onListener,onStopListener,onMic,denied,onPermissions,
   counting,ringing,localTimers.second,scheduleReadError,alertError,{alertError=it},scope,context)
 } else {
 Column(Modifier.fillMaxSize()) {
  Row(Modifier.fillMaxWidth().padding(start=24.dp,end=12.dp,top=12.dp),verticalAlignment=Alignment.CenterVertically) {
   Column(Modifier.weight(1f)) {
    Text("SARAH",style=MaterialTheme.typography.titleMedium,letterSpacing=2.sp)
    Text(if(ui.canCapture) "● Connected" else if(ui.phase in setOf("recording","finalizing","uploading","polling","reply_audio_pending","playing","confirming","cancelling")) "Voice session" else "○ Connection needs attention",style=MaterialTheme.typography.labelSmall,color=Color(0xffb9b1c7))
   }
   TextButton(onClick=onSettings,modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp).semantics {contentDescription="Connection and settings"}) {Text("⚙",fontSize=24.sp)}
  }
  if(scheduleReadError) Text("Local timers unavailable. Existing timer state not confirmed.",modifier=Modifier.fillMaxWidth().padding(horizontal=24.dp),style=MaterialTheme.typography.bodySmall)
  if(counting.isNotEmpty()) Column(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=4.dp)) {
   Text("Current timers",style=MaterialTheme.typography.labelLarge)
   Column(Modifier.fillMaxWidth().heightIn(max=190.dp).verticalScroll(rememberScrollState())) {
    counting.forEach {entry ->
     Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
      Column(Modifier.weight(1f)) {
       Text(entry.title,maxLines=1,overflow=TextOverflow.Ellipsis,style=MaterialTheme.typography.bodyMedium)
       Text(if(!entry.scheduled) "Scheduling pending · ${TimerCountdown.remaining(entry.dueMillis,localTimers.second)}"
        else TimerCountdown.remaining(entry.dueMillis,localTimers.second),style=MaterialTheme.typography.labelMedium)
      }
      TextButton(onClick={scope.launch {
       alertError=withContext(Dispatchers.IO) {runCatching {localSchedule(context).cancel(entry.id,kind="timer")}.getOrDefault(false).not()}
      }},modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp)) {Text("Cancel")}
     }
    }
   }
  }
  if(ringing.isNotEmpty()) Column(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=8.dp)) {
   Text("Local alert ringing",style=MaterialTheme.typography.labelLarge)
   ringing.forEach {entry ->
    Button(onClick={scope.launch {
     alertError=withContext(Dispatchers.IO) {runCatching {localSchedule(context).dismiss(entry.id)}.getOrDefault(false).not()}
    }},modifier=Modifier.fillMaxWidth().heightIn(min=56.dp)) {
     Text("■ Stop ${entry.kind} · ${entry.title.take(40)}",maxLines=2,overflow=TextOverflow.Ellipsis)
    }
   }
  }
  if(alertError) Text("Local stop not confirmed. Check current timers or notification; do not repeat uncertain writes.",modifier=Modifier.fillMaxWidth().padding(horizontal=24.dp),style=MaterialTheme.typography.bodySmall)
  BoxWithConstraints(Modifier.weight(1f).fillMaxWidth().padding(horizontal=24.dp,vertical=8.dp)) {
   val actionMaxHeight=maxHeight*.70f
   Column(Modifier.fillMaxSize(),horizontalAlignment=Alignment.CenterHorizontally) {
    Text(state,color=MaterialTheme.colorScheme.primary,style=MaterialTheme.typography.titleSmall)
    CompanionWaveform(ui.phase,vm,Modifier.weight(1f).fillMaxWidth())
    // Only exceptional/large-font action content scrolls. No outer screen scrolling.
    Column(Modifier.widthIn(max=340.dp).heightIn(max=actionMaxHeight).verticalScroll(rememberScrollState())) {
     if(ui.phase in setOf("error","uncertain","ready")) Text(ui.status,style=MaterialTheme.typography.bodySmall)
     ActionPanel(ui,vm,onMic,denied,onPermissions)
     if(ui.phase in setOf("finalizing","uploading","reply_audio_pending","cancelling","creating")) {
      OutlinedButton(onClick={},enabled=false,modifier=Modifier.heightIn(min=48.dp)) {Text("■ Stop unavailable during $state")}
     }
    }
   }
  }
  Surface(shape=RoundedCornerShape(topStart=26.dp,topEnd=26.dp),color=MaterialTheme.colorScheme.surface) {
   Column(Modifier.fillMaxWidth().padding(horizontal=24.dp,vertical=8.dp)) {
    TextButton(onClick={expanded=!expanded},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
     Text("History",modifier=Modifier.weight(1f),textAlign=TextAlign.Start)
     Text(if(expanded) "⌄" else "›")
    }
    HorizontalDivider(color=Color(0xff393143))
    Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
     TextButton(onClick=if(listener=="off") onListener else onSettings,modifier=Modifier.weight(1f).heightIn(min=48.dp)) {Text("“${WakePhrase.display}”",modifier=Modifier.weight(1f),textAlign=TextAlign.Start);Text(if(listener=="off") "Off  ›" else "$listener  ›")}
     if(listener!="off") TextButton(onClick=onStopListener,modifier=Modifier.heightIn(min=48.dp)) {Text("Stop microphone")}
    }
   }
  }
 }
 }
 if(expanded) Dialog(onDismissRequest={expanded=false}) {
  Surface(shape=RoundedCornerShape(24.dp),modifier=Modifier.fillMaxWidth().fillMaxHeight(.8f)) {
   Column(Modifier.padding(16.dp)) {
    Row(verticalAlignment=Alignment.CenterVertically) {
     Text("History",style=MaterialTheme.typography.titleLarge,modifier=Modifier.weight(1f))
     TextButton(onClick={expanded=false},modifier=Modifier.heightIn(min=48.dp)) {Text("Close")}
    }
    LazyColumn(Modifier.weight(1f).fillMaxWidth(),verticalArrangement=Arrangement.spacedBy(12.dp)) {
     if(ui.transcript.isEmpty()) item {Text("No local exchange yet.")}
     items(ui.transcript) { (who,text) -> Column {
      Text(if(who=="YOU") "You" else "Sarah",style=MaterialTheme.typography.labelMedium,color=MaterialTheme.colorScheme.primary)
      Text(text,style=MaterialTheme.typography.bodyMedium)
     } }
     item {Text(ui.status,style=MaterialTheme.typography.bodySmall)}
    }
   }
  }
 }
}
/** Lenovo-only A2: the phone retains its previous screen and controls. */
@Composable private fun LenovoResponseScreen(
 ui:SarahViewModel.Ui,listener:String,vm:SarahViewModel,state:String,expanded:Boolean,onHistory:()->Unit,
 onSettings:()->Unit,onListener:()->Unit,onStopListener:()->Unit,onMic:()->Unit,
 denied:Boolean,onPermissions:()->Unit,counting:List<ScheduleEntry>,ringing:List<ScheduleEntry>,
 now:Long,scheduleReadError:Boolean,alertError:Boolean,onAlertError:(Boolean)->Unit,
 scope:kotlinx.coroutines.CoroutineScope,context:Context
) {
 val lavender=MaterialTheme.colorScheme.primary
 val caption=ui.responseText
 // Server returns the whole answer before chunk playback, not a text stream.
 // Reveal advances only while the real MediaPlayer position advances. This is
 // deliberately approximate pacing, NOT word/audio alignment.
 var playedMs by remember(caption) {mutableLongStateOf(0L)}
 LaunchedEffect(ui.phase,caption) {
  if(ui.phase=="playing" && !caption.isNullOrBlank()) {
   var previous=0
   while(true) {
    val position=vm.playbackPositionMs()
    if(position>previous) playedMs+=(position-previous).toLong()
    previous=position
    delay(80)
   }
  }
 }
 val visibleAnswer=when {
  caption.isNullOrBlank()->null
  ui.phase in setOf("playing","polling")->caption.take((playedMs*18L/1000L).coerceIn(0L,caption.length.toLong()).toInt())
  else->caption
 }
 Column(Modifier.fillMaxSize()) {
  Row(Modifier.fillMaxWidth().padding(start=24.dp,end=12.dp,top=8.dp),verticalAlignment=Alignment.CenterVertically) {
   Text("SARAH",style=MaterialTheme.typography.titleMedium,letterSpacing=2.sp,modifier=Modifier.weight(1f))
   TextButton(onClick=onSettings,modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp).semantics {contentDescription="Connection and settings"}) {Text("⚙",fontSize=24.sp)}
  }
  if(scheduleReadError) Text("Local timers unavailable. Existing timer state not confirmed.",modifier=Modifier.padding(horizontal=20.dp),style=MaterialTheme.typography.bodySmall)
  if(counting.isNotEmpty() || ringing.isNotEmpty()) Column(Modifier.fillMaxWidth().heightIn(max=142.dp).verticalScroll(rememberScrollState()).padding(horizontal=20.dp)) {
   counting.forEach {entry-> Row(verticalAlignment=Alignment.CenterVertically) {
    Text("${entry.title} · ${TimerCountdown.remaining(entry.dueMillis,now)}",modifier=Modifier.weight(1f),maxLines=1,overflow=TextOverflow.Ellipsis)
    TextButton(onClick={scope.launch {onAlertError(withContext(Dispatchers.IO) {runCatching {localSchedule(context).cancel(entry.id,kind="timer")}.getOrDefault(false).not()})}},modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp)) {Text("Cancel")}
   }}
   ringing.forEach {entry->Button(onClick={scope.launch {onAlertError(withContext(Dispatchers.IO) {runCatching {localSchedule(context).dismiss(entry.id)}.getOrDefault(false).not()})}},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("■ Stop ${entry.kind} · ${entry.title.take(40)}",maxLines=1)}}
  }
  if(alertError) Text("Local stop not confirmed. Check current timers; do not repeat uncertain writes.",modifier=Modifier.padding(horizontal=20.dp),style=MaterialTheme.typography.bodySmall)
  Column(Modifier.weight(1f).fillMaxWidth().padding(horizontal=22.dp),horizontalAlignment=Alignment.CenterHorizontally) {
   Text(state,color=lavender,style=MaterialTheme.typography.titleSmall,modifier=Modifier.padding(top=8.dp))
   // The playback-driven waveform is unchanged; only its containing layout moves.
   CompanionWaveform(ui.phase,vm,Modifier.weight(.52f).fillMaxWidth())
   Column(Modifier.weight(.48f).fillMaxWidth().verticalScroll(rememberScrollState()),horizontalAlignment=Alignment.CenterHorizontally) {
    if(caption!=null) {
     Text("SARAH SAYS",color=lavender,style=MaterialTheme.typography.labelMedium)
     Spacer(Modifier.height(12.dp))
     Text(visibleAnswer.orEmpty(),style=MaterialTheme.typography.titleLarge,textAlign=TextAlign.Center,lineHeight=29.sp)
    } else if(ui.phase !in setOf("ready","done")) Text(ui.status,style=MaterialTheme.typography.bodyMedium,textAlign=TextAlign.Center)
    if(caption!=null && ui.phase in setOf("error","uncertain","cancelled")) Text(ui.status,style=MaterialTheme.typography.bodySmall,textAlign=TextAlign.Center)
    if(denied) {Text("Microphone denied. Enable permission in Android settings.",style=MaterialTheme.typography.bodySmall);TextButton(onClick=onPermissions,modifier=Modifier.heightIn(min=48.dp)) {Text("Open app settings")}}
    if(ui.phase=="recording") Text("Recording · adaptive pause. Discard with footer; Stop & send sends once.",style=MaterialTheme.typography.bodySmall,textAlign=TextAlign.Center)
    if(ui.phase in setOf("uncertain","confirming","polling","finalizing","uploading","reply_audio_pending","cancelling","creating","disconnected") || ui.phase=="error" && !ui.canCapture) {
     ActionPanel(ui,vm,onMic,denied,onPermissions)
    }
   }
  }
  Surface(shape=RoundedCornerShape(20.dp),color=MaterialTheme.colorScheme.surface,modifier=Modifier.fillMaxWidth().padding(horizontal=8.dp,vertical=6.dp)) {
   Row(Modifier.fillMaxWidth().padding(horizontal=8.dp,vertical=5.dp),verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(4.dp)) {
    Column(Modifier.weight(1f)) {
     Text(if(ui.canCapture) "● Connected" else if(listener!="off" || ui.phase in setOf("recording","playing","polling")) "● Voice session" else "○ Connection",style=MaterialTheme.typography.labelSmall,maxLines=1,overflow=TextOverflow.Ellipsis)
     Text(when {ui.phase=="recording"->"Recording now";listener=="off"->"Microphone off";ui.phase=="playing"->"Wake paused during reply";listener=="Wake listening"->"Wake ready · mic on";else->"Wake: $listener"},style=MaterialTheme.typography.labelSmall,color=Color(0xffa99fb8),maxLines=1,overflow=TextOverflow.Ellipsis)
    }
    OutlinedButton(onClick=when {listener!="off"->onStopListener;ui.phase=="recording"->vm::discard;else->onListener},modifier=Modifier.heightIn(min=48.dp).semantics {contentDescription=when {listener!="off"->"Stop microphone";ui.phase=="recording"->"Discard recording";else->"Enable persistent ${WakePhrase.display} microphone"}},contentPadding=PaddingValues(horizontal=7.dp)) {
     Text(when {listener!="off"->"Stop mic";ui.phase=="recording"->"Discard";else->"Wake off"},style=MaterialTheme.typography.labelSmall,maxLines=1)
    }
    val canTalk=ui.hasConfig && ui.canCapture && listener=="off" && ui.phase in setOf("ready","done","error","cancelled")
    Button(onClick=when(ui.phase) {"playing"->vm::stopAudio;"recording"->vm::send;else->onMic},enabled=ui.phase in setOf("playing","recording") || canTalk,modifier=Modifier.heightIn(min=48.dp),contentPadding=PaddingValues(horizontal=10.dp)) {
     Text(when(ui.phase) {"playing"->"■ Stop";"recording"->"■ Stop & send";"ready","done","error","cancelled"->"Tap to talk";else->"Working"},style=MaterialTheme.typography.labelMedium,maxLines=1)
    }
    TextButton(onClick=onHistory,modifier=Modifier.sizeIn(minWidth=48.dp,minHeight=48.dp).semantics {contentDescription=if(expanded) "Close history" else "History"},contentPadding=PaddingValues(0.dp)) {Text("History ›",style=MaterialTheme.typography.labelSmall,maxLines=1)}
   }
  }
 }
}
@Composable private fun ListenerControls(state:String,ui:SarahViewModel.Ui,canStart:Boolean,permissionReady:Boolean,onStart:()->Unit,onStop:()->Unit) {
 Column {
  Text("${WakePhrase.display}: $state · microphone stays on until Stop. Locked wake notifies only. Black-screen behavior unverified.",style=MaterialTheme.typography.bodySmall)
  if(state=="off") {
   OutlinedButton(onClick=onStart,enabled=canStart) {Text("Enable persistent ${WakePhrase.display}")}
   if(permissionReady) Text("Microphone permission granted. Tap Enable ${WakePhrase.display} again to start listening.",style=MaterialTheme.typography.bodySmall)
  } else OutlinedButton(onClick=onStop) {Text("Stop ${WakePhrase.display} microphone")}
  if(state=="off" && ui.phase in setOf("recording","finalizing","uploading","polling","reply_audio_pending","playing")) TextButton(onClick=onStop) {Text("Stop hands-free listening (current server work continues)")}
 }
}
@Composable private fun AssistantSetup(available:Boolean,held:Boolean,opened:Boolean,onRequest:()->Unit) {
 Column(Modifier.fillMaxWidth().padding(vertical=4.dp)) {
  Text(assistantRoleStatus(available,held),style=MaterialTheme.typography.bodySmall)
  if(opened) Text("Assistant opened. Unlock and tap to talk; no recording starts automatically.",style=MaterialTheme.typography.bodySmall)
  if(available && !held) TextButton(onClick=onRequest,modifier=Modifier.heightIn(min=48.dp)) {Text("Set as default assistant")}
 }
}
internal fun formatInstalledVersion(versionName:String?,versionCode:Long):String =
 "${versionName?.takeIf {it.isNotBlank()} ?: "Unknown"} (build $versionCode)"

@Composable private fun AboutPage(context:Context,vm:SarahViewModel,onBack:()->Unit) {
 val info=remember(context) {context.packageManager.getPackageInfo(context.packageName,0)}
 val name=remember(context) {context.applicationInfo.loadLabel(context.packageManager).toString()}
 var diagnostic by remember {mutableStateOf<String?>(null)}
 Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp)) {
  TextButton(onClick=onBack,modifier=Modifier.heightIn(min=48.dp)) {Text("‹ Back")}
  Spacer(Modifier.height(12.dp))
  Text("About $name",style=MaterialTheme.typography.headlineMedium)
  Spacer(Modifier.height(20.dp))
  Text("App version",style=MaterialTheme.typography.labelLarge)
  val buildCode=if(Build.VERSION.SDK_INT>=28) info.longVersionCode else info.versionCode.toLong()
  Text(formatInstalledVersion(info.versionName,buildCode),style=MaterialTheme.typography.bodyLarge)
  Spacer(Modifier.height(16.dp))
  Text("App name",style=MaterialTheme.typography.labelLarge)
  Text(name,style=MaterialTheme.typography.bodyLarge)
  Spacer(Modifier.height(16.dp))
  Text("Package",style=MaterialTheme.typography.labelLarge)
  Text(context.packageName,style=MaterialTheme.typography.bodyLarge)
  Spacer(Modifier.height(16.dp))
  Text("Android version / API",style=MaterialTheme.typography.labelLarge)
  Text("${Build.VERSION.RELEASE} / ${Build.VERSION.SDK_INT}",style=MaterialTheme.typography.bodyLarge)
  Spacer(Modifier.height(16.dp))
  Text("Local diagnostics · not a fix",style=MaterialTheme.typography.labelLarge)
  Button(onClick={diagnostic=vm.diagnosticSnapshot(buildCode)},modifier=Modifier.heightIn(min=48.dp)) {Text("Capture diagnostics")}
  diagnostic?.let {Text(it,style=MaterialTheme.typography.bodySmall)}
  Spacer(Modifier.height(16.dp))
  Text("Send / Share includes only app build, fixed error code, HTTP status, phase, chunk ACK progress, and saved ID presence/length/SHA256 prefix. No tokens, URLs, transcripts, audio or raw IDs. Explicit tap only; no automatic retry. Not a recovery action.")
  Button(onClick={vm.sendDiagnostics(buildCode)},modifier=Modifier.heightIn(min=48.dp)) {Text("Send diagnostics")}
  val delivery by vm.diagnosticDelivery.collectAsState()
  Text(delivery)
  OutlinedButton(onClick={
   val intent=android.content.Intent(android.content.Intent.ACTION_SEND).apply {type="text/plain";putExtra(android.content.Intent.EXTRA_TEXT,vm.shareDiagnostics(buildCode))}
   context.startActivity(android.content.Intent.createChooser(intent,"Share sanitized diagnostics"))
  },modifier=Modifier.heightIn(min=48.dp)) {Text("Share diagnostics")}
  Text(vm.shareDiagnostics(buildCode),style=MaterialTheme.typography.bodySmall)
 }
}
@Composable private fun Status(ui:SarahViewModel.Ui) {
 val text="${ui.phase.replaceFirstChar {it.uppercase()}} · ${ui.status}"
 Surface(tonalElevation=2.dp,shape=RoundedCornerShape(12.dp),modifier=Modifier.fillMaxWidth().padding(vertical=10.dp)) {
  Text(text,modifier=Modifier.padding(12.dp).semantics {contentDescription="Status: $text"},style=MaterialTheme.typography.bodyMedium)
 }
}
@Composable private fun ActionPanel(ui:SarahViewModel.Ui,vm:SarahViewModel,onMic:()->Unit,denied:Boolean,onSettings:()->Unit) {
 var recoveryConfirm by remember { mutableStateOf(false) }
 if(recoveryConfirm && ui.phase=="uncertain") AlertDialog(
  onDismissRequest={recoveryConfirm=false},
  title={Text("Clear only approved local tracking?")},
  text={Text("Only the exact approved missing request can pass. Stop ${WakePhrase.display} first. A fresh authenticated status check must return not_found, with no admitted turn or active audio. Keeps history, conversation, pairing, permissions, action records and audio ACKs. Never resends the old request. Any mismatch or network/auth failure keeps tracking blocked.")},
  confirmButton={TextButton(onClick={recoveryConfirm=false;vm.recoverApprovedLocalRequest()}) {Text("Check & clear approved tracking")}},
  dismissButton={TextButton(onClick={recoveryConfirm=false}) {Text("Keep tracking")}}
 )
 Column(Modifier.fillMaxWidth().imePadding().padding(bottom=12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
  if(ui.phase=="recording") {
   Text(if(ui.status.startsWith("Starting microphone")) "Microphone starting · wait for cue" else "Microphone active · adaptive speech pause · maximum 30 seconds",style=MaterialTheme.typography.labelMedium)
   Button(onClick=vm::send,modifier=Modifier.fillMaxWidth().heightIn(min=72.dp)) {Text("■ Stop & send",style=MaterialTheme.typography.titleMedium)}
   OutlinedButton(onClick=vm::discard,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Discard recording")}
  } else if(ui.phase=="playing") {
   Text("Stops current speech and remaining generation · no action rollback")
   Button(onClick=vm::stopAudio,modifier=Modifier.fillMaxWidth().heightIn(min=72.dp)) {Text("■ Stop")}
  } else if(ui.phase=="uncertain") {
   Text("No automatic resend. Server actions may already have happened.")
   Button(onClick=vm::checkExisting,modifier=Modifier.fillMaxWidth().heightIn(min=64.dp)) {Text("Check existing request status")}
   OutlinedButton(onClick={recoveryConfirm=true},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Recover approved local request")}
   OutlinedButton(onClick=vm::reconnect,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Check connection")}
   TextButton(onClick=vm::cancelTurn) {Text("■ Stop server turn (no rollback)")}
  } else if(ui.phase=="confirming" && ui.confirmation!=null) {
   Text("Server confirmation: ${ui.confirmation.optString("label").take(200)}")
   Text("Accepting is not proof action succeeded.")
   Button(onClick={vm.confirm(true)},modifier=Modifier.fillMaxWidth().heightIn(min=56.dp)) {Text("Confirm once")}
   OutlinedButton(onClick={vm.confirm(false)},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Deny")}
   TextButton(onClick=vm::cancelTurn) {Text("■ Stop server turn (no rollback)")}
  } else if(ui.phase=="polling") {
   Text("Waiting for actual server status; no progress estimate")
   OutlinedButton(onClick=vm::cancelTurn,modifier=Modifier.fillMaxWidth().heightIn(min=56.dp)) {Text("■ Stop server turn (no rollback)")}
  } else if(ui.hasConfig && ui.canCapture && ui.phase in setOf("ready","done","error","cancelled")) {
   val listening by HeySarahListenerService.status.collectAsStateWithLifecycle()
   Button(onClick=onMic,enabled=listening=="off",modifier=Modifier.fillMaxWidth().heightIn(min=72.dp)) {Text("● Tap to talk",style=MaterialTheme.typography.titleMedium)}
   if(listening!="off") Text("Stop ${WakePhrase.display} before manual command capture.")
   if(denied) {Text("Microphone denied. Enable permission in Android settings.");TextButton(onClick=onSettings) {Text("Open app settings")}}
  } else {
   Text("Authenticated connection required before recording",style=MaterialTheme.typography.bodySmall)
   if(ui.hasConfig) OutlinedButton(onClick=vm::reconnect,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {Text("Check connection")}
  }
 }
}
