package com.serexe.sarah

import org.junit.Assert.assertEquals
import org.junit.Test

class ListenerPermissionFlowTest {
 @Test fun freshConfirmationWithExistingGrantsMayStart() {
  assertEquals(ListenerPermissionFlow.Action.START, ListenerPermissionFlow.confirmed(true))
 }
 @Test fun firstConfirmationRequestsPermissionButGrantNeverStartsListener() {
  assertEquals(ListenerPermissionFlow.Action.REQUEST_PERMISSION, ListenerPermissionFlow.confirmed(false))
  assertEquals(ListenerPermissionFlow.Action.CONFIRM_AGAIN, ListenerPermissionFlow.permissionResult(true))
  assertEquals(ListenerPermissionFlow.Action.START, ListenerPermissionFlow.confirmed(true))
 }
 @Test fun deniedPermissionCannotStart() {
  assertEquals(ListenerPermissionFlow.Action.DENIED, ListenerPermissionFlow.permissionResult(false))
 }
}
