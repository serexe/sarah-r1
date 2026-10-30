package com.serexe.sarah

import java.util.concurrent.CompletableFuture

/** Production ownership boundary. Only the preparing thread touches pending native resources.
 * Stop invalidates immediately; it never waits behind initialize/prepare. Completion acknowledges
 * cleanup, not merely cancellation. Native start alone is serialized with invalidation.
 */
internal class PlaybackOwnership(private val beforeInitialization:()->Unit = {},
 private val dispatchCleanup:((()->Unit)->Unit) = {it()}) {
 interface Resource {
  fun initialize()
  fun prepare()
  fun start()
  fun close():Boolean
 }
 private class Attempt(val id:Long) {
  val closed=CompletableFuture<Boolean>()
  var resource:Resource?=null
  var started=false
  var closing=false
 }
 private val lock=Any()
 private var generation=0L
 private var current:Attempt?=null
 private var lastClosed=CompletableFuture.completedFuture(true)

 fun play(eligible:()->Boolean, create:(Long)->Resource):Boolean {
  val pair=synchronized(lock) {
   val old=current
   check(old==null || (old.started && !old.closing)) {"Playback cleanup pending"}
   val next=Attempt(++generation)
   current=next
   next to old
  }
  val attempt=pair.first
  var started=false
  try {
   pair.second?.let {check(cleanup(it).get()) {"Playback cleanup failed"}}
   beforeInitialization()
   if(!allowed(attempt,eligible)) return false
   // Factory only constructs a resource holder. initialize owns all fallible native work.
   val resource=create(attempt.id)
   attempt.resource=resource
   if(!allowed(attempt,eligible)) return false
   resource.initialize()
   if(!allowed(attempt,eligible)) return false
   resource.prepare() // deliberately outside lock; Stop can invalidate while blocked
   synchronized(lock) {
    if(current===attempt && generation==attempt.id && eligible()) {
     resource.start()
     // A synchronous native/focus callback may invalidate reentrantly during start.
     if(current===attempt && generation==attempt.id) {
      attempt.started=true
      started=true
     }
    }
   }
   return started
  } finally {
   if(!started) cleanup(attempt)
  }
 }
 private fun allowed(attempt:Attempt,eligible:()->Boolean)=synchronized(lock) {
  current===attempt && generation==attempt.id && eligible()
 }
 fun stop():CompletableFuture<Boolean> {
  val result=synchronized(lock) {
   generation++
   val a=current
   (a?.closed ?: lastClosed) to a?.takeIf {it.started}
  }
  result.second?.let {a->dispatchCleanup {cleanup(a)}}
  return result.first
 }
 fun finish(id:Long,success:Boolean,done:(Boolean)->Unit) {
  val a=synchronized(lock) {
   current?.takeIf {it.id==id && generation==id}?.also {generation++}
  } ?: return
  if(a.started) dispatchCleanup {cleanup(a)}
  a.closed.thenAccept {done(success && it)}
 }
 private fun cleanup(attempt:Attempt):CompletableFuture<Boolean> {
  val owns=synchronized(lock) {
   if(attempt.closing) false else {attempt.closing=true;true}
  }
  if(owns) {
   val clean=runCatching {attempt.resource?.close() ?: true}.getOrDefault(false)
   synchronized(lock) {
    if(current===attempt) {current=null;lastClosed=attempt.closed}
   }
   attempt.closed.complete(clean)
  }
  return attempt.closed
 }
}
