package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class NoiseSuppressionTrialTest {
 private class FakeEffect:NoiseSuppressionTrial.Effect {
  var result=0; var controlled=true; var active=true; var releases=0
  var throwEnable=false; var throwRelease=false
  override fun enable():Int {if(throwEnable) throw IllegalStateException("fixture");return result}
  override fun enabled()=active
  override fun hasControl()=controlled
  override fun release() {releases++;if(throwRelease) throw IllegalStateException("fixture")}
 }
 private class FakeFactory(val effect:FakeEffect?=FakeEffect()):NoiseSuppressionTrial.Factory {
  var available=true; var calls=0; var session=-1; var throwCreate=false; var throwAvailability=false
  override fun available():Boolean {if(throwAvailability) throw IllegalStateException("fixture");return available}
  override fun create(sessionId:Int):NoiseSuppressionTrial.Effect? {
   calls++;session=sessionId;if(throwCreate) throw IllegalStateException("fixture");return effect
  }
 }
 @Test fun attachesToOwningSessionAndReleasesExactlyOnce() {
  val factory=FakeFactory();val events=mutableListOf<String>()
  val trial=NoiseSuppressionTrial.attach(123,"wake",factory,events::add)
  assertEquals(123,factory.session)
  assertEquals(listOf("wake NS available=true attached=true enabled=true fallback=none"),events)
  assertTrue(trial.close());assertTrue(trial.close());assertEquals(1,factory.effect!!.releases)
 }
 @Test fun unavailableAndAvailabilityExceptionLeaveMicUnchanged() {
  for(fail in listOf(false,true)) {
   val factory=FakeFactory();factory.available=false;factory.throwAvailability=fail
   val events=mutableListOf<String>()
   assertTrue(NoiseSuppressionTrial.attach(1,"command",factory,events::add).close())
   assertEquals(0,factory.calls);assertEquals(0,factory.effect!!.releases)
   assertTrue(events.single().contains("fallback=unavailable"))
  }
 }
 @Test fun nullOrThrowingCreateFallsBack() {
  for(factory in listOf(FakeFactory(null),FakeFactory().apply {throwCreate=true})) {
   val events=mutableListOf<String>()
   assertTrue(NoiseSuppressionTrial.attach(2,"wake",factory,events::add).close())
   assertEquals(1,factory.calls);assertTrue(events.single().contains("fallback=create"))
  }
 }
 @Test fun refusedFailedOrUncontrolledEnableReleasesBeforeCapture() {
  for(configure in listOf<(FakeEffect)->Unit>({it.result=-1},{it.throwEnable=true},{it.active=false},{it.controlled=false})) {
   val effect=FakeEffect().also(configure);val events=mutableListOf<String>()
   val trial=NoiseSuppressionTrial.attach(3,"command",FakeFactory(effect),events::add)
   assertTrue(trial.close());assertEquals(1,effect.releases)
   assertTrue(events.single().contains("fallback=enable"))
  }
 }
 @Test fun failedReleaseIsReportedWithoutThrowingOrSecondRelease() {
  val effect=FakeEffect().apply {throwRelease=true};val events=mutableListOf<String>()
  val trial=NoiseSuppressionTrial.attach(4,"wake",FakeFactory(effect),events::add)
  assertFalse(trial.close());assertTrue(trial.close());assertEquals(1,effect.releases)
  assertTrue(events.last().contains("release=failed"))
 }
 @Test fun diagnosticFailureCannotBlockCapture() {
  val effect=FakeEffect()
  val trial=NoiseSuppressionTrial.attach(5,"wake",FakeFactory(effect)) {throw IllegalStateException("logger")}
  assertTrue(trial.close());assertEquals(1,effect.releases)
 }
}