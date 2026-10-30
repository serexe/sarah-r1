package com.serexe.sarah
import org.junit.Assert.*
import org.junit.Test
import java.io.ByteArrayInputStream
import java.util.UUID

class ProtocolTest {
 @Test fun originAndIdentity() {
  assertEquals("https://bridge.example.invalid:8443", Origin.parse("https://bridge.example.invalid:8443/"))
  listOf("http://host", "https://u:p@host", "https://host/path", "https://host?q=x", "https://host/#x").forEach { assertThrows(IllegalArgumentException::class.java) { Origin.parse(it) } }
  assertTrue(Identity.valid(UUID.randomUUID().toString()))
  assertFalse(Identity.valid("../turn"))
 }
 @Test fun wavBoundaries() {
  val pcm=ByteArray(16000) { (it % 127).toByte() }
  val wav=Wav.encode(pcm)
  assertEquals(16044,wav.size)
  assertEquals("RIFF",String(wav.copyOfRange(0,4)))
  assertEquals("WAVE",String(wav.copyOfRange(8,12)))
  assertEquals(16000, Wav.le32(wav,24))
  assertEquals(1, Wav.le16(wav,22))
  assertEquals(16, Wav.le16(wav,34))
  assertEquals(pcm.size,Wav.le32(wav,40))
  assertThrows(IllegalArgumentException::class.java) { Wav.encode(ByteArray(100)) }
  assertThrows(IllegalArgumentException::class.java) { Wav.encode(ByteArray(960002)) }
 }
 @Test fun boundedReads() {
  assertEquals(3,Bounded.read(ByteArrayInputStream(ByteArray(3)),3).size)
  assertThrows(IllegalArgumentException::class.java) {Bounded.read(ByteArrayInputStream(ByteArray(4)),3)}
 }
 @Test fun ownershipAndNoResend() {
  val s=TurnState()
  assertTrue(s.begin("c1","r1"))
  assertFalse(s.begin("c1","r2"))
  s.ambiguous("c1","r1")
  assertEquals("uncertain",s.phase)
  assertEquals("r1",s.lookupRequest())
  assertFalse(s.begin("c1","r2"))
  s.newConversation("c2")
  assertFalse(s.accept("c1","r1","done"))
  assertEquals("ready",s.phase)
 }
}
