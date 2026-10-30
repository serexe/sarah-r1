package com.serexe.sarah

/** Existing bounded window remains default; explicit persistent opt-in belongs to live service only. */
internal class ListenerWindow(private val startedAt:Long,private val persistent:Boolean=false) {
 fun valid(now:Long):Boolean = now>=startedAt && (persistent || now-startedAt<LIMIT_MS)
 companion object {const val LIMIT_MS=120000L}
}
