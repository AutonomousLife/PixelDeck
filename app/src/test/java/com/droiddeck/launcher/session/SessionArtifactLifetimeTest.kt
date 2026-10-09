package com.droiddeck.launcher.session

import android.app.Notification
import android.os.Looper
import java.util.concurrent.atomic.AtomicInteger
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import org.robolectric.annotation.LooperMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
@LooperMode(LooperMode.Mode.PAUSED)
class SessionArtifactLifetimeTest {
    private lateinit var service: SessionService
    private lateinit var pending: AtomicInteger
    private val originalPhase = SessionState.phase
    private val originalRunning = SessionState.running

    @Before fun foregroundService() {
        service = Robolectric.buildService(SessionService::class.java).create().get()
        service.startForeground(11, Notification())
        pending = SessionService::class.java.getDeclaredField("artifactCollections").let {
            it.isAccessible = true
            it.get(service) as AtomicInteger
        }
        SessionState.running = false
        SessionState.phase = SessionPhase.IDLE
    }

    @After fun restoreState() {
        SessionState.phase = originalPhase
        SessionState.running = originalRunning
        service.onDestroy()
    }

    private fun invoke(name: String) {
        SessionService::class.java.getDeclaredMethod(name).apply { isAccessible = true }.invoke(service)
        shadowOf(Looper.getMainLooper()).idle()
    }

    @Test fun endedSessionStaysForegroundUntilEveryCollectionFinishes() {
        pending.set(2)
        invoke("stopServiceWhenArtifactsComplete")
        assertFalse(shadowOf(service).isForegroundStopped)
        assertFalse(shadowOf(service).isStoppedBySelf)
        invoke("artifactsCollected")
        assertFalse(shadowOf(service).isStoppedBySelf)
        invoke("artifactsCollected")
        assertTrue(shadowOf(service).isForegroundStopped)
        assertTrue(shadowOf(service).isStoppedBySelf)
    }

    @Test fun olderCollectionCannotStopANewRunningSession() {
        pending.set(1)
        SessionState.running = true
        SessionState.phase = SessionPhase.READY
        invoke("artifactsCollected")
        assertFalse(shadowOf(service).isForegroundStopped)
        assertFalse(shadowOf(service).isStoppedBySelf)
    }

    @Test fun completedCollectionCannotEndUnfinishedGuestTeardown() {
        pending.set(1)
        SessionState.phase = SessionPhase.STOPPING
        invoke("artifactsCollected")
        assertFalse(shadowOf(service).isStoppedBySelf)
        SessionState.phase = SessionPhase.FAILED
        invoke("stopServiceWhenArtifactsComplete")
        assertTrue(shadowOf(service).isStoppedBySelf)
    }
}
