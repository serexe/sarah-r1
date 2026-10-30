package com.serexe.sarah

/** One explicit opt-in, one hit. No automatic restart/rearm or stale wake after Stop. */
internal class ListenerGate {
 private var active=false
 private var wake=false
 @Synchronized fun start(safe:Boolean):Boolean {
  if(active || !safe) return false
  active=true;wake=false;return true
 }
 @Synchronized fun listening(safe:Boolean):Boolean {
  if(!safe) stop()
  return active && !wake
 }
 @Synchronized fun hit():Boolean {
  if(!active || wake) return false
  wake=true;return true
 }
 @Synchronized fun stop() {active=false;wake=false}
 /** Only called AFTER recorder and native engine release. */
 @Synchronized fun released():Boolean {
  val dispatch=active && wake
  active=false;wake=false;return dispatch
 }
}
