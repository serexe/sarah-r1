package com.serexe.sarah

import kotlinx.coroutines.*
import java.util.concurrent.CompletableFuture

/** Shared production boundary: cancellation is never a native-release acknowledgement. */
internal object CommandCleanup {
 // Establish command try/finally before Stop can cancel a queued Main dispatch.
 fun launchOwned(scope:CoroutineScope,body:suspend CoroutineScope.()->Unit):Job =
  scope.launch(start=CoroutineStart.UNDISPATCHED) {body()}
 suspend fun await(recording:Job?, captureReleased:()->Boolean,
                   playbackClosed:CompletableFuture<Boolean>, timeoutMs:Long=2500, preparing:Job?=null):Boolean =
  withContext(NonCancellable) {
   withTimeoutOrNull(timeoutMs) {
    recording?.join()
    preparing?.join()
    while(!playbackClosed.isDone) delay(10)
    captureReleased() && runCatching {playbackClosed.get()}.getOrDefault(false)
   } ?: false
  }
}

/** Surviving explicit window only. Screen interactivity is deliberately not a lock check. */
internal object ServiceRearmPolicy {
 fun allowed(ownerCurrent:Boolean,stopped:Boolean,destroyed:Boolean,optedStart:Long,now:Long,
  safe:Boolean,unlocked:Boolean,resolved:Boolean,persistent:Boolean=false):Boolean =
  ownerCurrent && !stopped && !destroyed && optedStart!=0L && ListenerWindow(optedStart,persistent).valid(now) &&
   safe && unlocked && resolved
}

/** Service-owned command completion. Cleanup ACK precedes either continuation or teardown. */
internal class ServiceCommandCompletion(private val clean:()->Boolean,private val eligible:()->Boolean,
 private val restart:()->Boolean,private val finish:()->Unit) {
 private var completed=false
 fun complete():Boolean {
  if(completed || !clean()) return false
  completed=true
  if(eligible() && restart()) return true
  finish()
  return false
 }
}

/** Exact visible handoff capability; stale ViewModels cannot complete a newer command. */
internal class VisibleCommandHandoff(private val current:()->Boolean,private val finished:(Boolean)->Unit) {
 private var completed=false
 val cleanupComplete get()=completed
 var onStop:(()->Unit)?=null
 fun owned()=!completed && current()
 fun complete(resolved:Boolean) {
  if(completed) return
  completed=true;onStop=null;finished(resolved)
 }
 fun stop() {onStop?.invoke()}
}

/** Application teardown is gated; OS destruction is an observation, never vetoable. */
internal class ServiceTeardown(private val invalidate:()->Unit,private val ready:()->Boolean,
                               private val teardown:()->Unit) {
 @Volatile var destroyed=false; private set
 @Volatile var stopped=false; private set
 private var finished=false
 fun stop() {stopped=true;invalidate()}
 fun destroyed() {destroyed=true;stop()}
 @Synchronized fun finish():Boolean {
  if(finished || !ready()) return false
  finished=true
  if(!destroyed) teardown()
  return true
 }
}
