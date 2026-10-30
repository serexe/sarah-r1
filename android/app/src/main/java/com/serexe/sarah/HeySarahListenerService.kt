package com.serexe.sarah

import android.Manifest
import android.annotation.SuppressLint
import android.app.*
import android.app.role.RoleManager
import android.content.*
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.media.*
import android.os.*
import kotlinx.coroutines.flow.MutableStateFlow

/** Explicit foreground consent starts a persistent local-only microphone FGS.
 * Locked/offscreen hits notify; only visible unlocked hits hand off after microphone release.
 */
class HeySarahListenerService:Service() {
 private var session=ListenerSession()
 private val gate get()=session.gate
 private val main=Handler(Looper.getMainLooper())
 private var worker:Thread?=null
 private val listenerCleanup=ListenerCleanup()
 private var window:ListenerWindow?=null
 private var wakeLock:PowerManager.WakeLock?=null
 @Volatile private var command:OffscreenCommand?=null
 private var visibleCommand:VisibleCommandHandoff?=null
 private var foregroundNotification:Notification?=null
 private var closed=false
 private val teardown=ServiceTeardown(
  {session.stopListening();command?.stop();visibleCommand?.stop()},
  {worker==null && listenerCleanup.complete && session.released && command?.cleanupComplete!=false && (visibleCommand==null || (visibleCommand?.cleanupComplete==true && AudioArbiter.idle()))},
  {stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()})
 private fun requestStop() {
  teardown.stop() // synchronous invalidation; no framework stopService
  main.post {
   // Pending/cold STOP has no native work. Never infer this from a failed/dead worker:
   // begin() makes complete=false before the worker can acquire anything.
   if(worker==null && listenerCleanup.complete && !session.released) complete() else finishService()
  }
 }

 private val interruptions=object:BroadcastReceiver() {
  override fun onReceive(context:Context?,intent:Intent?) {
   if(intent?.action==AudioManager.ACTION_AUDIO_BECOMING_NOISY) session.stopListening()
  }
 }
 private val audio by lazy {getSystemService(AudioManager::class.java)}
 override fun onBind(intent:Intent?) : IBinder? = null
 override fun onCreate() {
  super.onCreate();current?.let {session=it};instance=this
  registerReceiver(interruptions,IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY))
 }
 private fun safe():Boolean = try {
  checkSelfPermission(Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED &&
   NotificationAvailability.allowed(this) &&

   (Build.VERSION.SDK_INT>=29 && roleManager(this)?.isRoleHeld(RoleManager.ROLE_ASSISTANT)==true) &&
   audio.mode==AudioManager.MODE_NORMAL && !audio.isMicrophoneMute && !audio.isMusicActive
 } catch (_:Exception) {false}
 override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
  if(intent?.action==STOP) {stop(this);return START_NOT_STICKY}
  if(intent?.action!=START || !permit || worker!=null) {if(worker==null && command==null) {session.stopListening();complete()};return START_NOT_STICKY}
  permit=false
  session=current ?: run {stopSelf();return START_NOT_STICKY}
  window=ListenerWindow(optedStart,persistent=true)
  val nm=getSystemService(NotificationManager::class.java)
  nm.createNotificationChannel(NotificationChannel(CHANNEL,"Hey Sarah microphone",NotificationManager.IMPORTANCE_LOW))
  if(!session.gate.listening(true) || !safe()) {session.stopListening();complete();return START_NOT_STICKY}
  val stop=PendingIntent.getService(this,1,Intent(this,HeySarahListenerService::class.java).setAction(STOP),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
  val open=PendingIntent.getActivity(this,2,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
  val n=Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.ic_btn_speak_now)
   .setContentTitle("Hey Sarah · microphone active").setContentText("Persistent listening · Stop anytime")
   .setVisibility(Notification.VISIBILITY_PUBLIC).setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",stop).build()).build()
  foregroundNotification=n
  try {
   if(Build.VERSION.SDK_INT>=30) startForeground(71,n,ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE) else startForeground(71,n)
   // Explicit opt-in retains CPU for local detection until Stop or fail-closed teardown.
   // Do not restart a microphone FGS from background if the OS destroys this owner.
   wakeLock=getSystemService(PowerManager::class.java).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"sarah:local-keyword").also {it.acquire()}
   stage("listening")
   listenerCleanup.begin()
   worker=Thread({listen()},"sarah-local-keyword").also {it.start()}
  } catch (_:Exception) {session.stopListening();complete()}
  return START_NOT_STICKY
 }
 @SuppressLint("MissingPermission")
 private fun listen() {
  var recorder:AudioRecord?=null
  var engine:HeySarahKeywordEngine?=null
  var focus:AudioFocusRequest?=null
  var startAttempted=false
  var routesAttempted=false
  var recordingCallbackAttempted=false

  val silenced=object:AudioManager.AudioRecordingCallback() {
   override fun onRecordingConfigChanged(configs:MutableList<AudioRecordingConfiguration>) {
    val session=recorder?.audioSessionId ?: return
    if(Build.VERSION.SDK_INT>=29 && configs.any {it.clientAudioSessionId==session && it.isClientSilenced}) this@HeySarahListenerService.session.stopListening()
   }
  }
  val routes=object:AudioDeviceCallback() {
   override fun onAudioDevicesRemoved(devices:Array<out AudioDeviceInfo>) {if(devices.isNotEmpty()) session.stopListening()}
  }
  try {
   check(safe())
   routesAttempted=true
   audio.registerAudioDeviceCallback(routes,main)
   val request=AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_EXCLUSIVE)
    .setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANT).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
    .setOnAudioFocusChangeListener({session.onAudioFocusChange(it)},main).build()
   focus=request
   check(audio.requestAudioFocus(request)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED)
   val min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
   check(min>0)
   val r=listenerCleanup.construct {AudioRecord(MediaRecorder.AudioSource.MIC,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,maxOf(min,4096))}
   recorder=r;check(r.state==AudioRecord.STATE_INITIALIZED)
   recordingCallbackAttempted=true
   audio.registerAudioRecordingCallback(silenced,main)
   val e=listenerCleanup.construct {HeySarahKeywordEngine(assets)};engine=e
   e.arm() // JNI stream recreation outside stop/native-start ownership lock.
   check(session.nativeStart.start({gate.listening(safe()) && window?.valid(SystemClock.elapsedRealtime())==true}) {startAttempted=true;r.startRecording()})
   val chunk=ShortArray(320)

   while(gate.listening(safe()) && window?.valid(SystemClock.elapsedRealtime())==true) {
    val n=r.read(chunk,0,chunk.size,AudioRecord.READ_NON_BLOCKING)
    check(n>=0)
    if(n>0 && gate.listening(safe()) && e.acceptPcm16(chunk,n)) {if(gate.hit()) stage("hit");break}
    Thread.sleep(20)
   }
  } catch (_:Exception) {session.stopListening()}
  finally {
   val released=listenerCleanup.finish(
    if(startAttempted) ({recorder!!.stop()}) else null,
    recorder?.let {r -> {r.release()}},
    engine?.let {e -> {e.close()}},
    if(recordingCallbackAttempted) ({audio.unregisterAudioRecordingCallback(silenced)}) else null,
    if(routesAttempted) ({audio.unregisterAudioDeviceCallback(routes)}) else null,
    focus?.let {request -> {check(audio.abandonAudioFocusRequest(request)==AudioManager.AUDIOFOCUS_REQUEST_GRANTED)}})
   if(!released) session.stopListening()
   main.post {
    // Recorder/native release precedes command callback; late Stop/background invalidates wake.
    complete()
   }
  }
 }
 private fun complete() {
  var dispatched=false
  session.releaseAfter({
   listenerCleanup.complete
  }, {safe() && window?.valid(SystemClock.elapsedRealtime())==true}, {
   dispatched=true
   if(visible && getSystemService(PowerManager::class.java).isInteractive) {
    val listenerOwner=session
    var resolved=false
    lateinit var handoff:VisibleCommandHandoff
    val completion=ServiceCommandCompletion(
     {listenerCleanup.complete && listenerOwner.released && AudioArbiter.idle() && !OffscreenOwnership.held()},
     {ServiceRearmPolicy.allowed(current===listenerOwner && session===listenerOwner && !closed,
      teardown.stopped,teardown.destroyed,optedStart,SystemClock.elapsedRealtime(),safe(),
      AudioEligibility.allowed(this,true),resolved,persistent=true)}, {visibleCommand=null;rearmAfterCommand()}, {finishService()})
    handoff=VisibleCommandHandoff(
     {visibleCommand===handoff && current===listenerOwner && !closed && !teardown.stopped && !teardown.destroyed &&
      window?.valid(SystemClock.elapsedRealtime())==true},
     {resolved=it;completion.complete()})
    visibleCommand=handoff
    val handed=AudioEligibility.allowed(this,true) && runCatching {onWake?.invoke()==true}.getOrDefault(false)
    if(!handed) {visibleCommand=null;stage("fallback");notifyWake();finishService()}
   } else if(AudioEligibility.allowed(this,true) && current===session && window?.valid(SystemClock.elapsedRealtime())==true) {
    lateinit var completion:ServiceCommandCompletion
    // Fresh finite command budget, independent of the persistent listener opt-in.
    val owner=OffscreenCommand(this,ListenerWindow(SystemClock.elapsedRealtime(),persistent=false),
     {current===session && !teardown.stopped && !teardown.destroyed && status.value!="off"}, {stage(it)}, {completion.complete()})
    completion=ServiceCommandCompletion(
     {command===owner && listenerCleanup.complete && session.released && owner.cleanupComplete && !OffscreenOwnership.held()},
     {ServiceRearmPolicy.allowed(current===session && !closed,teardown.stopped,teardown.destroyed,
      optedStart,SystemClock.elapsedRealtime(),safe(),AudioEligibility.allowed(this,true),owner.rearmAllowed,persistent=true)},
     {rearmAfterCommand()}, {finishService()})
    command=owner
    if(!owner.start()) {stage("fallback");notifyWake();finishService()}
   } else {
    stage("locked");notifyWake()
    // Locked wake never records a command. Continue only local keyword capture
    // under this same explicitly opted-in FGS after native listener release.
    val isDeviceLocked=getSystemService(KeyguardManager::class.java)?.isDeviceLocked==true
    if(!(isDeviceLocked && current===session && !closed && !teardown.stopped && !teardown.destroyed &&
      window?.valid(SystemClock.elapsedRealtime())==true && safe() && AudioArbiter.idle() && rearmAfterCommand())) finishService()
   }
  }, {worker=null;stage("released")}).also {released ->
   if(!released) {stage("cleanup-failed");return}
  }
  if(!dispatched) finishService()
 }
 private fun rearmAfterCommand():Boolean {
  // Same still-running microphone FGS; never cold-start from background, renew consent,
  // or extend opt-in. Command completion already acknowledged native cleanup.
  val thread=try {Thread({listen()},"sarah-local-keyword")} catch (_:Exception) {return false}
  val next=ListenerSession()
  if(!AudioArbiter.acquire(next)) return false
  if(!next.gate.start(true)) {AudioArbiter.release(next);return false}
  command=null;session=next;current=next
  listenerCleanup.begin()
  worker=thread
  return try {stage("listening");thread.start();true} catch (_:Exception) {
   next.stopListening()
   // Only a never-started thread proves no recorder/JNI acquisition. Otherwise
   // keep ownership until the real worker's finally acknowledges native release.
   if(thread.state==Thread.State.NEW) {
    worker=null;listenerCleanup.finish(null,null,null,null,null,null)
    next.releaseAfter({listenerCleanup.complete},{false},{})
   }
   false
  }
 }
 private fun stage(label:String) {
  if(closed || teardown.destroyed || current!==session) return
  if(label!="stopped" && !NotificationAvailability.allowed(this)) {stop(this);return}
  StageTrail.write(this,label)
  status.value=if(label=="listening") "Wake listening" else label
  // Notification contains stage category, never command text, transcript, or token.
  if(foregroundNotification!=null && status.value!="off") {
   val stop=PendingIntent.getService(this,1,Intent(this,HeySarahListenerService::class.java).setAction(STOP),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
   try {getSystemService(NotificationManager::class.java).notify(71,Notification.Builder(this,CHANNEL)
    .setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Hey Sarah · microphone active")
    .setContentText(if(label=="listening") "Persistent listening · Stop anytime" else "Stage: $label · Stop anytime").setVisibility(Notification.VISIBILITY_PUBLIC)
    .setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",stop).build()).build())} catch (_:Exception) {stop(this)}
  }
 }
 private fun finishService() {
  if(closed) return
  // Neither a dead listener worker nor cancellation is a native listener/command cleanup ACK.
  if(!teardown.finish()) return
  closed=true
  command?.stop();command=null

  runCatching {wakeLock?.let {if(it.isHeld) it.release()}};wakeLock=null
  if(current===session) current=null
  if(instance===this) instance=null
  optedStart=0;status.value="off"
 }
 private fun notifyWake() {
  // No background activity launch or command submission.
  val open=PendingIntent.getActivity(this,3,Intent(this,MainActivity::class.java).setAction(Intent.ACTION_ASSIST),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
  getSystemService(NotificationManager::class.java).notify(72,Notification.Builder(this,CHANNEL)
   .setSmallIcon(android.R.drawable.ic_btn_speak_now).setContentTitle("Hey Sarah heard")
   .setContentText("Unlock and open Sarah, then tap to talk. No locked-screen auto-recording.")
   .setVisibility(Notification.VISIBILITY_PUBLIC).setContentIntent(open).setAutoCancel(true)
   .setTimeoutAfter(120000).addAction(Notification.Action.Builder(null,"Open Sarah",open).build()).build())
 }
 override fun onTaskRemoved(rootIntent:Intent?) {
  // Recent-card removal is not explicit Stop. Started microphone FGS owns opt-in.
  super.onTaskRemoved(rootIntent)
 }
 override fun onDestroy() {
  // Android may already have removed FGS. This cannot wait for, or veto, OS destruction.
  teardown.destroyed()
  runCatching {wakeLock?.let {if(it.isHeld) it.release()}};wakeLock=null
  runCatching {unregisterReceiver(interruptions)}
  if(!closed) {status.value="destroyed-cleanup-pending";finishService()}
  if(instance===this) instance=null
  super.onDestroy()
 }
 companion object {
  // Read-only same-process cleanup evidence; null means no live service, not ACK true.
  internal fun visibleHandoff():VisibleCommandHandoff?=instance?.visibleCommand?.takeIf {it.owned()}
  internal fun cleanupSnapshot():Pair<Boolean?,Boolean?> = instance?.let {
   (it.listenerCleanup.complete && it.session.released) to it.command?.cleanupComplete
  } ?: (null to null)
  private const val START="com.serexe.sarah.LISTEN_ONCE"
  private const val STOP="com.serexe.sarah.STOP_LISTENER"
  private const val CHANNEL="sarah-local-microphone"
  val status=MutableStateFlow("off")
  @Volatile var visible=false
  @Volatile var onWake:(()->Boolean)?=null // installed only by resumed Activity
  @Volatile private var optedStart=0L

  @Volatile private var permit=false
  @Volatile private var current:ListenerSession?=null
  @Volatile private var instance:HeySarahListenerService?=null
  @Synchronized fun start(context:Context,foregroundReady:Boolean,rearm:Boolean=false) {
   if(!visible || !foregroundReady || !AudioEligibility.allowed(context,true) || status.value!="off") return
   val now=SystemClock.elapsedRealtime()
   if(rearm && (optedStart==0L || !ListenerWindow(optedStart,persistent=true).valid(now))) return
   if(!rearm) optedStart=now
   context.getSystemService(NotificationManager::class.java).cancel(72)
   val next=ListenerSession()
   if(!AudioArbiter.acquire(next)) return
   next.gate.start(true);current=next;permit=true;status.value="starting";StageTrail.write(context,"starting")
   try {context.startForegroundService(Intent(context,HeySarahListenerService::class.java).setAction(START))}
   catch (_:Exception) {permit=false;next.cancelBefore {};AudioArbiter.release(next);current=null;optedStart=0;status.value="off"}
  }
  fun stop(context:Context) {
   permit=false;optedStart=0
   current?.stopListening()
   if(current!=null) status.value="stopping"
   instance?.requestStop() // existing owner only: never cold-start a service to stop it
   StageTrail.write(context,"stopped")
  }
  suspend fun cancelAndAwait(context:Context) {
   stop(context)
   kotlinx.coroutines.withTimeout(3000) {while(!AudioArbiter.idle()) kotlinx.coroutines.delay(10)}
  }
  suspend fun awaitIdle() {
   kotlinx.coroutines.withTimeout(3000) {while(!AudioArbiter.idle()) kotlinx.coroutines.delay(10)}
  }
 }
}
