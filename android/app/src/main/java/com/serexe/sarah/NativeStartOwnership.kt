package com.serexe.sarah

/** Shared cancellation/native-start boundary. Hooks allow tests to pause before and inside ownership. */
internal class NativeStartOwnership(private val beforeNativeStart:()->Unit={},private val beforeNativeOperation:()->Unit={}) {
 private var stopped=false
 fun start(eligible:()->Boolean,nativeStart:()->Unit):Boolean {
  beforeNativeStart()
  return synchronized(this) {
   if(stopped || !eligible()) false
   else {beforeNativeOperation();nativeStart();true}
  }
 }
 fun cancel(invalidate:()->Unit={}) {synchronized(this) {stopped=true;invalidate()}}
}
