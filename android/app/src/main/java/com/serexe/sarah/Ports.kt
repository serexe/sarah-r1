package com.serexe.sarah

import org.json.JSONObject

/** Seams used by production owner and local deterministic tests. */
interface BridgePort {
 fun health():JSONObject
 fun create():String
 fun submit(conversation:String,request:String,wav:ByteArray):String
 fun lookup(request:String):JSONObject
 fun poll(turn:String):JSONObject
 fun cancel(turn:String):JSONObject
 fun confirm(turn:String,conversation:String,nonce:String,hash:String,accept:Boolean):JSONObject
 fun audio(turn:String):ByteArray
}
interface StateStore {
 fun load():JSONObject
 fun save(value:JSONObject)
 fun reset()
}
interface AudioCapture {
 val capped:Boolean
 val speechDetected:Boolean get()=true
 val endpointReached:Boolean get()=false
 suspend fun record()
 fun stop()
 fun finish():ByteArray
 fun discard()
}
interface AudioPlayback {
 fun play(bytes:ByteArray)
 fun stop()
}
