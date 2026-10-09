package com.droiddeck.launcher.agent

import android.content.Intent
import android.os.Looper
import android.util.Base64
import com.droiddeck.launcher.SessionActivity
import com.droiddeck.launcher.session.SessionService
import java.util.concurrent.CountDownLatch
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
class AgentStartActivityTest {
    @Before fun completeRecovery() {
        // Avoid running real filesystem recovery; keep the activity's real worker and callbacks.
        val field = AgentBridgeProvider::class.java.getDeclaredField("recoveryComplete")
        field.isAccessible = true
        (field.get(null) as CountDownLatch).countDown()
    }

    private fun request(json: String) = Intent().putExtra(
        AgentStartActivity.EXTRA_REQUEST,
        Base64.encodeToString(json.toByteArray(Charsets.UTF_8), Base64.NO_WRAP),
    )

    private fun finishRecoveryCallbacks() {
        Thread.getAllStackTraces().keys.filter { it.name == "agent-start-recovery" }.forEach {
            it.join(5_000)
            assertFalse("Recovery worker did not finish", it.isAlive)
        }
        shadowOf(Looper.getMainLooper()).idle()
    }

    @Test fun creationForwardsAValidSteamRequest() {
        val activity = Robolectric.buildActivity(
            AgentStartActivity::class.java,
            request("""{"mode":"steam","steamUi":"desktop","steamUrl":"steam://open/library"}"""),
        ).create().get()
        finishRecoveryCallbacks()

        val launched = shadowOf(activity).nextStartedActivity
        assertEquals(SessionActivity::class.java.name, launched.component!!.className)
        assertEquals(SessionService.ACTION_AGENT_START, launched.action)
        assertEquals(SessionService.MODE_STEAM, launched.getStringExtra(SessionService.EXTRA_MODE))
        assertEquals("desktop", launched.getStringExtra(SessionService.EXTRA_STEAM_UI))
        assertEquals("steam://open/library", launched.getStringExtra(SessionService.EXTRA_STEAM_URL))
        assertTrue(activity.isFinishing)
        assertNull(shadowOf(activity).nextStartedActivity)
    }

    @Test fun missingRequestFinishesWithoutStartingASession() {
        val activity = Robolectric.buildActivity(AgentStartActivity::class.java, Intent()).create().get()
        finishRecoveryCallbacks()
        assertTrue(activity.isFinishing)
        assertNull(shadowOf(activity).nextStartedActivity)
    }

    @Test fun newIntentSupersedesAnEarlierQueuedRecoveryCallback() {
        val controller = Robolectric.buildActivity(
            AgentStartActivity::class.java, request("""{"mode":"steam"}"""),
        ).create()
        val newer = request("""{"mode":"run","program":"/usr/bin/true","programArgs":["one","two"]}""")
        controller.newIntent(newer)
        finishRecoveryCallbacks()

        val activity = controller.get()
        assertSame(newer, activity.intent)
        val launched = shadowOf(activity).nextStartedActivity
        assertEquals(SessionService.MODE_RUN, launched.getStringExtra(SessionService.EXTRA_MODE))
        assertEquals("/usr/bin/true", launched.getStringExtra(SessionService.EXTRA_PROGRAM))
        assertArrayEquals(arrayOf("one", "two"), launched.getStringArrayExtra(SessionService.EXTRA_PROGRAM_ARGS))
        assertNull(shadowOf(activity).nextStartedActivity)
    }

    @Test fun destroyedActivityDoesNotLaunchFromPendingRecovery() {
        val controller = Robolectric.buildActivity(
            AgentStartActivity::class.java, request("""{"mode":"steam"}"""),
        ).create()
        controller.destroy()
        finishRecoveryCallbacks()
        assertTrue(controller.get().isDestroyed)
        assertNull(shadowOf(controller.get()).nextStartedActivity)
    }
}
