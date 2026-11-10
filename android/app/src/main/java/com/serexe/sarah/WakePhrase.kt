package com.serexe.sarah

/** Flavor-owned wake wording and strict native result. Never accepts a fuzzy token alias. */
internal object WakePhrase {
    val display: String get() = BuildConfig.WAKE_PHRASE
    fun matchesResult(result: String): Boolean = result == BuildConfig.WAKE_RESULT_ALIAS
}
