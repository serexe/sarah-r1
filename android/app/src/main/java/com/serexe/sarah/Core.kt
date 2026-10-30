package com.serexe.sarah

import java.net.URI
import java.io.InputStream
import java.io.ByteArrayOutputStream
import java.util.UUID

object Origin {
 fun parse(input: String): String {
  val uri = URI(input.trim())
  require(uri.scheme == "https" && uri.host != null && uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null && (uri.rawPath.isNullOrEmpty() || uri.rawPath == "/") && uri.port in -1..65535 && uri.port != 0 && !input.contains('\\')) { "HTTPS origin only" }
  return "https://${uri.host.lowercase()}${if (uri.port < 0) "" else ":${uri.port}"}"
 }
}
object Identity {
 private val pattern=Regex("[A-Za-z0-9_-]{1,100}")
 fun valid(s:String)=pattern.matches(s)
 fun new()=UUID.randomUUID().toString()
}
class TurnState {
 var conversation:String?=null; private set
 var request:String?=null; private set
 var phase="ready"; private set
 fun begin(c:String,r:String):Boolean {
  if (phase !in setOf("ready","done","error","cancelled") || !Identity.valid(c) || !Identity.valid(r)) return false
  conversation=c; request=r; phase="uploading"; return true
 }
 fun ambiguous(c:String,r:String) { if (conversation==c && request==r) phase="uncertain" }
 fun lookupRequest():String?=if (phase=="uncertain") request else null
 fun accept(c:String,r:String,next:String):Boolean {
  if (c!=conversation || r!=request || next !in setOf("transcribing","thinking","confirming","acting","speaking","done","error","cancelled","uncertain")) return false
  phase=next;return true
 }
 fun newConversation(c:String) { require(Identity.valid(c));conversation=c;request=null;phase="ready" }
}
object Wav {
 const val RATE=16000
 const val MAX_SAMPLES=RATE*30
 fun le16(b:ByteArray,i:Int)= (b[i].toInt() and 255) or ((b[i+1].toInt() and 255) shl 8)
 fun le32(b:ByteArray,i:Int)=le16(b,i) or (le16(b,i+2) shl 16)
 private fun put16(b:ByteArray,i:Int,v:Int) { b[i]=v.toByte();b[i+1]=(v shr 8).toByte() }
 private fun put32(b:ByteArray,i:Int,v:Int) { put16(b,i,v);put16(b,i+2,v shr 16) }
 fun encode(pcm:ByteArray):ByteArray {
  require(pcm.size%2==0 && pcm.size in 8000..MAX_SAMPLES*2) { "Capture must be 0.25–30 s, PCM16 mono" }
  val b=ByteArray(44+pcm.size)
  "RIFF".toByteArray().copyInto(b,0);put32(b,4,36+pcm.size)
  "WAVEfmt ".toByteArray().copyInto(b,8);put32(b,16,16);put16(b,20,1);put16(b,22,1)
  put32(b,24,RATE);put32(b,28,RATE*2);put16(b,32,2);put16(b,34,16)
  "data".toByteArray().copyInto(b,36);put32(b,40,pcm.size);pcm.copyInto(b,44)
  return b
 }
}
object Bounded {
 fun read(stream:InputStream,max:Int):ByteArray {
  val output=ByteArrayOutputStream();val block=ByteArray(8192)
  while (true) {
   val count=stream.read(block,0,minOf(block.size,max+1-output.size()))
   if(count<0) return output.toByteArray()
   if(count==0) continue
   output.write(block,0,count)
   require(output.size()<=max) { "Payload too large" }
  }
 }
}
