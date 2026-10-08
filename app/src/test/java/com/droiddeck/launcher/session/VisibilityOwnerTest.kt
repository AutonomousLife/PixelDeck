package com.droiddeck.launcher.session

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VisibilityOwnerTest {
    private val old = Any()
    private val fresh = Any()

    @Test fun anOlderScreenStoppingAfterANewerOneStartedReportsNothing() {
        val v = VisibilityOwner()
        v.shown(old)
        v.shown(fresh)          // Try again: the new screen starts first
        assertFalse(v.hidden(old)) // ...then Android stops the old one
        assertTrue(v.hidden(fresh))
    }

    @Test fun theCurrentScreenGoingAwayIsReportedOnce() {
        val v = VisibilityOwner()
        v.shown(old)
        assertTrue(v.hidden(old))
        assertFalse(v.hidden(old))
    }

    @Test fun recreateReportsHiddenThenShown() {
        val v = VisibilityOwner()
        v.shown(old)
        assertTrue(v.hidden(old)) // a rotation stops the old instance before the new one starts
        v.shown(fresh)
        assertTrue(v.hidden(fresh))
    }

    @Test fun forgetReleasesOnlyTheOwner() {
        val v = VisibilityOwner()
        v.shown(fresh)
        v.forget(old)
        assertTrue(v.hidden(fresh))
    }
}
