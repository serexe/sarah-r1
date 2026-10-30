package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files

class LegacyReplyPurgeTest {
 @Test fun nullEnumerationFailsClosed() {
  val directory=object:File("synthetic-cache") {override fun listFiles():Array<File>?=null}
  val e=assertThrows(IllegalStateException::class.java) {purgeLegacyReplies(directory)}
  assertEquals("Legacy reply cache enumeration failed",e.message)
 }
 @Test fun enumerationExceptionFailsClosed() {
  val directory=object:File("synthetic-cache") {override fun listFiles():Array<File> = throw SecurityException("synthetic denial")}
  val e=assertThrows(IllegalStateException::class.java) {purgeLegacyReplies(directory)}
  assertEquals("Legacy reply cache enumeration failed",e.message)
  assertTrue(e.cause is SecurityException)
 }
 @Test fun deleteFailureFailsClosed() {
  val reply=object:File("reply-synthetic.mp3") {override fun isFile()=true;override fun delete()=false}
  val directory=object:File("synthetic-cache") {override fun listFiles()=arrayOf<File>(reply)}
  assertThrows(IllegalStateException::class.java) {purgeLegacyReplies(directory)}
 }
 @Test fun onlyDirectLegacyRepliesRemoved() {
  val directory=Files.createTempDirectory("sarah-purge").toFile()
  try {
   val legacy=File(directory,"reply-old.mp3").apply {writeText("synthetic")}
   val other=File(directory,"other.mp3").apply {writeText("keep")}
   val suffix=File(directory,"reply-other.txt").apply {writeText("keep")}
   val nested=File(directory,"nested").apply {mkdir()}
   val child=File(nested,"reply-child.mp3").apply {writeText("keep")}
   purgeLegacyReplies(directory)
   assertFalse(legacy.exists());assertEquals("keep",other.readText());assertEquals("keep",suffix.readText());assertEquals("keep",child.readText())
  } finally {directory.deleteRecursively()}
 }
}
