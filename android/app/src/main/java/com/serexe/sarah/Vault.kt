package com.serexe.sarah

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import org.json.JSONObject
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Whole state is encrypted and atomically replaced before network submission. No plaintext fallback. */
class Vault(private val context:Context,private val owner:Any?=null):StateStore {
 private val file=AtomicFile(File(context.filesDir,"state.enc"))
 private fun key():SecretKey {
  val ks=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
  (ks.getKey("sarah-v1",null) as? SecretKey)?.let { return it }
  return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
   init(KeyGenParameterSpec.Builder("sarah-v1",KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build())
  }.generateKey()
 }
 override fun load():JSONObject=OffscreenOwnership.guarded(owner) { readState() }
 @Synchronized private fun readState():JSONObject {
  if (!file.baseFile.exists()) return JSONObject()
  val all=file.openRead().use { it.readBytes() }; require(all.size>28 && all.size<524288)
  val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,all.copyOfRange(0,12)))
  return JSONObject(String(cipher.doFinal(all.copyOfRange(12,all.size)),Charsets.UTF_8))
 }
 override fun save(value:JSONObject)=OffscreenOwnership.guarded(owner) { writeState(value) }
 @Synchronized private fun writeState(value:JSONObject) {
  // AndroidKeyStore AES-GCM disallows caller-supplied encryption nonces by default.
  val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key())
  val nonce=cipher.iv.also { require(it.size==12) }
  val bytes=nonce+cipher.doFinal(value.toString().toByteArray(Charsets.UTF_8))
  val out=file.startWrite()
  try { out.write(bytes);file.finishWrite(out) } catch (e:Exception) { file.failWrite(out);throw e }
 }
 override fun reset()=OffscreenOwnership.guarded(owner) { deleteState() }
 @Synchronized private fun deleteState() {
  file.delete()
  KeyStore.getInstance("AndroidKeyStore").apply {load(null);deleteEntry("sarah-v1")}
 }
}
