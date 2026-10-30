package com.serexe.sarah

import android.app.Application
import java.io.File

/** Upgrade cleanup of legacy plaintext replies before any Activity/service entry. */
class SarahApplication:Application() {
 override fun onCreate() {super.onCreate();purgeLegacyReplies(cacheDir)}
}

internal fun purgeLegacyReplies(directory:File) {
 val files=try {directory.listFiles() ?: throw IllegalStateException("Legacy reply cache enumeration failed")}
  catch (e:Exception) {throw IllegalStateException("Legacy reply cache enumeration failed",e)}
 files.filter {it.isFile && it.name.startsWith("reply-") && it.name.endsWith(".mp3")}
  .forEach {if(!it.delete()) throw IllegalStateException("Legacy reply cache cleanup failed")}
}