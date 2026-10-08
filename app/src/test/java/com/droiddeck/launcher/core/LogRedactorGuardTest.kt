package com.droiddeck.launcher.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * [LogRedactor.redact] skips a pattern only when the line cannot match it. These lines sit at the
 * edges of those checks (mixed case, values in the middle of a timestamped line, shapes that only
 * one pattern catches), so a guard that wrongly skipped would leak them.
 */
class LogRedactorGuardTest {
    private val ts = "[2026-10-08 06:14:55] "

    @Test fun mixedCaseKeywordsStillRedact() {
        assertFalse(LogRedactor.redact("${ts}Using jWt 25484942796017334").contains("25484942796017334"))
        assertFalse(LogRedactor.redact("${ts}ToKeN=abcd1234efgh").contains("abcd1234efgh"))
        assertFalse(LogRedactor.redact("${ts}SESSIONID: zzzz9999yyyy").contains("zzzz9999yyyy"))
        assertFalse(LogRedactor.redact("${ts}Steam GUARD code: K7X2P").contains("K7X2P"))
        assertFalse(LogRedactor.redact("${ts}Two-Factor: Q8W3E").contains("Q8W3E"))
    }

    @Test fun guidAndWebApiKeyMidLine() {
        val guid = "3F2504E0-4F89-11D3-9A0C-0305E82C3301"
        assertFalse(LogRedactor.redact("${ts}machine $guid ok").contains(guid))
        val key = "0123456789ABCDEF0123456789abcdef"
        assertFalse(LogRedactor.redact("${ts}k=$key;").contains(key))
    }

    @Test fun steamIdsAndExternalAddress() {
        assertEquals("${ts}[U:1:*****6789]", LogRedactor.redact("${ts}[U:1:123456789]"))
        assertFalse(LogRedactor.redact("${ts}EXTERNAL ADDRESS 2001:db8:1:2::5").contains("2001:db8:1:2::5"))
    }

    @Test fun residualAndLongTokens() {
        assertFalse(LogRedactor.redact("${ts}MachineAuth AbCdEfGhIjKlMnOp").contains("AbCdEfGhIjKlMnOp"))
        val long = "A".repeat(90)
        assertFalse(LogRedactor.redact("${ts}blob $long").contains(long))
    }

    @Test fun ordinaryLinesAreUntouched() {
        val line = "${ts}[CStore] network request completed in 42 ms (two retries)"
        assertEquals(line, LogRedactor.redact(line))
    }
}
