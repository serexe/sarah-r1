package com.serexe.sarah

/** Actual KWS finally boundary. Every acquired/possibly acquired resource must acknowledge
 * cleanup. Cancellation, a dead worker, and cleanup attempts are not release ACKs.
 * No retries: a thrown/unfinished native call latches ownership closed for this session.
 */
internal class ListenerCleanup {
 @Volatile var complete=true; private set
 private var constructionUncertain=false
 fun begin() {complete=false}
 fun <T> construct(create:()->T):T {
  constructionUncertain=true
  val resource=create()
  constructionUncertain=false
  return resource
 }
 fun finish(stop:(()->Unit)?,release:(()->Unit)?,close:(()->Unit)?,
            recordingCallback:(()->Unit)?,deviceCallback:(()->Unit)?,focus:(()->Unit)?):Boolean {
  var success=!constructionUncertain
  // Do not short circuit: a stop failure must not prevent release/other cleanup attempts.
  for(operation in listOf(stop,release,close,recordingCallback,deviceCallback,focus)) {
   if(operation!=null && runCatching {operation()}.isFailure) success=false
  }
  complete=success
  return success
 }
}
