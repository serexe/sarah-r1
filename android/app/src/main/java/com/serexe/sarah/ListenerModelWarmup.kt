package com.serexe.sarah

import java.util.concurrent.CountDownLatch

/** Model-only construction during command work; never owns AudioRecord or the mic lease.
 * Next listener takes sole ownership. Stop closes unused JNI before service-off.
 */
internal class ListenerModelWarmup<T:AutoCloseable>(
 private val create:()->T, private val finished:()->Unit
) {
 private val done=CountDownLatch(1)
 private var value:T?=null
 private var cancelled=false
 private var taken=false
 private var finishedConstruction=false
 private var cleanupSucceeded=false
 private var closeInProgress=false
 private var closeFailed=false
 @Volatile var durationMs:Long?=null; private set
 val complete get()=synchronized(this) {finishedConstruction && cleanupSucceeded && !closeInProgress && !closeFailed}

 fun start():Boolean {
  val thread=try {Thread({
   val started=System.nanoTime()
   var made:T?=null
   var success=true
   if(!isCancelled()) try {made=create()} catch (_:Throwable) {
    success=false // uncertain JNI construction: never acknowledge cleanup
   }
   synchronized(this) {if(!cancelled && success) {value=made;made=null}}
   if(made!=null && runCatching {made.close()}.isFailure) success=false
   durationMs=(System.nanoTime()-started)/1_000_000
   synchronized(this) {cleanupSucceeded=success;finishedConstruction=true}
   done.countDown()
   finished()
  },"sarah-model-warmup")} catch (_:Exception) {return false}
  return try {thread.start();true} catch (_:Exception) {
   // A non-NEW worker may have entered native construction. Retain ownership
   // until its real finally ACK rather than treating a thrown start as empty.
   thread.state!=Thread.State.NEW
  }
 }
 @Synchronized private fun isCancelled()=cancelled
 fun take():T? {
  done.await()
  synchronized(this) {
   if(cancelled || taken || !complete) return null
   taken=true
   return value.also {value=null}
  }
 }
 fun cancel() {
  val unused:T?
  synchronized(this) {
   cancelled=true;unused=value;value=null
   if(unused!=null) closeInProgress=true // not ACKed until close returns
  }
  if(unused!=null) {
   val closed=runCatching {unused.close()}.isSuccess
   synchronized(this) {closeInProgress=false;if(!closed) closeFailed=true}
  }
 }
}
