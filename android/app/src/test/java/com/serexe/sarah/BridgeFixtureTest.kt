package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.MockResponse
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLHandshakeException

/** Local synthetic HTTPS bridge. No personal endpoint, credentials, or live calls. */
class BridgeFixtureTest {
 private val secret="x".repeat(48)
 @Test fun routesAndReadOnlyRecovery() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Synthetic fixture CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer()
  server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false)
  server.start()
  try {
   val origin="https://localhost:${server.port}"
   val api=Bridge(origin,secret,ca.certificate.encoded)
   server.enqueue(MockResponse().setResponseCode(200).setBody("{\"protocol\":1,\"ready\":true}"))
   assertEquals(1,api.health().getInt("protocol"))
   server.enqueue(MockResponse().setResponseCode(201).setBody("{\"conversation\":\"c1\"}"))
   assertEquals("c1",api.create())
   server.enqueue(MockResponse().setResponseCode(202).setBody("{\"turn\":\"t1\"}"))
   assertEquals("t1",api.submit("c1","request-1",Wav.encode(ByteArray(8000))))
   val submit=server.takeRequest(2,TimeUnit.SECONDS)!! // health first
   assertEquals("/v1/health",submit.path)
   assertEquals("POST",server.takeRequest(2,TimeUnit.SECONDS)!!.method)
   val upload=server.takeRequest(2,TimeUnit.SECONDS)!!
   assertEquals("audio/wav",upload.getHeader("Content-Type"))
   assertEquals("c1",upload.getHeader("X-Conversation"))
   assertEquals("request-1",upload.getHeader("Idempotency-Key"))
   assertEquals("Bearer $secret",upload.getHeader("Authorization"))
   server.enqueue(MockResponse().setResponseCode(200).setBody("{\"id\":\"t1\",\"conversation\":\"c1\",\"state\":\"done\",\"detail\":\"Fixture reply\",\"transcript\":\"Hi\",\"audio\":false}"))
   assertEquals("done",api.lookup("request-1").getString("state"))
   assertEquals("GET",server.takeRequest(2,TimeUnit.SECONDS)!!.method)
   assertEquals(4,server.requestCount) // no duplicate POST
  } finally {server.shutdown()}
 }
 @Test fun redirectsDeniedAndNoCredentialForwarding() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Fixture CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer();server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false);server.start()
  val target=MockWebServer();target.start()
  try {
   server.enqueue(MockResponse().setResponseCode(302).addHeader("Location",target.url("/stolen")))
   assertThrows(Bridge.Failure::class.java) {Bridge("https://localhost:${server.port}",secret,ca.certificate.encoded).health()}
   assertEquals(0,target.requestCount)
   assertEquals("/v1/health",server.takeRequest().path)
  } finally {server.shutdown();target.shutdown()}
 }
 @Test fun untrustedAndWrongHostnameRejected() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Fixture CA").build()
  val leaf=HeldCertificate.Builder().commonName("wrong.invalid").addSubjectAlternativeName("wrong.invalid").signedBy(ca).build()
  val server=MockWebServer();server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false);server.start()
  try {
   assertThrows(Exception::class.java) {Bridge("https://localhost:${server.port}",secret,ca.certificate.encoded).health()}
   assertThrows(Exception::class.java) {Bridge("https://localhost:${server.port}",secret).health()}
  } finally {server.shutdown()}
 }
 @Test fun statusAndPayloadFixture() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Fixture CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer();server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false);server.start()
  try {
   val api=Bridge("https://localhost:${server.port}",secret,ca.certificate.encoded)
   for (status in listOf(403,409,429,503)) {
    server.enqueue(MockResponse().setResponseCode(status).setBody("{\"error\":\"fixture\"}"))
    try {api.lookup("r1");fail("Expected $status")} catch (e:Bridge.Failure) {assertEquals(status,e.status)}
   }
   server.enqueue(MockResponse().setResponseCode(200).addHeader("Content-Type","audio/mpeg").setBody("synthetic audio bytes"))
   assertTrue(api.audio("t1").isNotEmpty())
   server.enqueue(MockResponse().setResponseCode(200).setBody("{\"state\":\"cancelled\"}"))
   api.cancel("t1")
   repeat(5) {server.takeRequest()}
   assertEquals("{}",server.takeRequest().body.readUtf8())
  } finally {server.shutdown()}
 }
}
