package com.serexe.sarah

/** Permission grant is not listener consent. A fresh confirmation starts after grants exist. */
internal object ListenerPermissionFlow {
 enum class Action { START, REQUEST_PERMISSION, CONFIRM_AGAIN, DENIED }
 fun confirmed(permissionsAlreadyGranted:Boolean):Action =
  if(permissionsAlreadyGranted) Action.START else Action.REQUEST_PERMISSION
 fun permissionResult(allGranted:Boolean):Action =
  if(allGranted) Action.CONFIRM_AGAIN else Action.DENIED
}
