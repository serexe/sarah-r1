package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class WakePhraseTest {
    @Test fun exactVariantResultOnly() {
        val lenovo = BuildConfig.FLAVOR == "lenovo"
        assertEquals(if (lenovo) 0.24f else 0.25f, BuildConfig.WAKE_KEYWORD_THRESHOLD, 0.0001f)
        assertEquals(if (lenovo) "Sarah" else "Hey Sarah", WakePhrase.display)
        assertTrue(WakePhrase.matchesResult(if (lenovo) "SARAH" else "HEY_SARAH"))
        assertFalse(WakePhrase.matchesResult(if (lenovo) "HEY_SARAH" else "SARAH"))
        assertFalse(WakePhrase.matchesResult("sarah"))
        assertFalse(WakePhrase.matchesResult(" SARAH"))
        assertFalse(WakePhrase.matchesResult(""))
    }
}
