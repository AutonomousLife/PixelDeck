package com.droiddeck.launcher.session

/**
 * Which session screen last became visible. Two can overlap: "Try again" and an agent start finish
 * the ended screen and open a fresh one, and Android stops the old activity only after the new one
 * has started. The old one's "hidden" then arrived after the new one's "visible", and the service
 * suspended a session that was still starting, on screen ("Steam is paused" over "Starting Steam").
 * A screen reports hidden only while it is still the one that was shown last.
 */
class VisibilityOwner {
    private var owner: Any? = null

    @Synchronized
    fun shown(screen: Any) {
        owner = screen
    }

    /** True when [screen]'s going out of sight is the session's; false when a newer screen took over. */
    @Synchronized
    fun hidden(screen: Any): Boolean {
        if (owner !== screen) return false
        owner = null
        return true
    }

    /** Drops [screen] without reporting anything, so a destroyed activity is not kept alive. */
    @Synchronized
    fun forget(screen: Any) {
        if (owner === screen) owner = null
    }

    companion object {
        val sessionScreens = VisibilityOwner()
    }
}
