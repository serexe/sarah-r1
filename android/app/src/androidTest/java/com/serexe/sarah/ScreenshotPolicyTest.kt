package com.serexe.sarah

import android.content.ComponentName
import android.content.pm.ActivityInfo
import android.view.WindowManager
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ScreenshotPolicyTest {
 @Test fun mainActivityAllowsScreenshots() {
  ActivityScenario.launch(MainActivity::class.java).use { scenario ->
   scenario.onActivity { activity ->
    assertEquals(0, activity.window.attributes.flags and WindowManager.LayoutParams.FLAG_SECURE)
    val info = activity.packageManager.getActivityInfo(ComponentName(activity, MainActivity::class.java), 0)
    assertEquals(0, info.flags and ActivityInfo.FLAG_EXCLUDE_FROM_RECENTS)
   }
  }
 }
}
