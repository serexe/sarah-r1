package com.serexe.sarah

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test

class BridgeLimitsTest {
 @Test fun jsonResponsesAndErrorsAreBounded() {
  val ca=HeldCertificate.Builder().certificateAuthority(1).commonName("Test CA").build()
  val leaf=HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").signedBy(ca).build()
  val server=MockWebServer()
  server.useHttps(HandshakeCertificates.Builder().heldCertificate(leaf,ca.certificate).build().sslSocketFactory(),false)
  server.start()
  try {
   val api=Bridge("https://localhost:${server.port}","x".repeat(48),ca.certificate.encoded)
   for (status in listOf(200,403)) {
    server.enqueue(MockResponse().setResponseCode(status).setBody("{\"error\":\""+"x".repeat(262145)+"\"}"))
    val error=assertThrows(IllegalArgumentException::class.java) {api.health()}
    assertEquals("Payload too large",error.message)
   }
   for (path in listOf({api.poll("t1")},{api.lookup("r1")})) {
    server.enqueue(MockResponse().setResponseCode(200).setBody("{\"detail\":\""+"x".repeat(262145)+"\"}"))
    assertThrows(IllegalArgumentException::class.java) {path()}
   }
  } finally {server.shutdown()}
 }
}
