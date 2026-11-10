package com.serexe.sarah

import org.junit.Assert.*
import org.junit.Test

class WakePhraseTest {
    @Test fun exactVariantResultOnly() {
        val lenovo = BuildConfig.FLAVOR == "lenovo"
        assertEquals(if (lenovo) 0.24f else 0.25f, BuildConfig.WAKE_KEYWORD_THRESHOLD, 0.0001f)
        assertEquals(if (lenovo) "Nova" else "Hey Sarah", WakePhrase.display)
        assertTrue(WakePhrase.matchesResult(if (lenovo) "NOVA" else "HEY_SARAH"))
        assertFalse(WakePhrase.matchesResult(if (lenovo) "HEY_SARAH" else "NOVA"))
        assertFalse(WakePhrase.matchesResult("SARAH"))
        assertFalse(WakePhrase.matchesResult("nova"))
        assertFalse(WakePhrase.matchesResult(" NOVA"))
        assertFalse(WakePhrase.matchesResult(""))
    }
}
