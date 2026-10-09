package com.droiddeck.launcher.input

import com.droiddeck.launcher.session.SessionState
import com.droiddeck.launcher.wayland.WaylandCompositor
import java.io.File
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.Implementation
import org.robolectric.annotation.Implements
import org.robolectric.annotation.LooperMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE,
    shadows = [PadBridgeReleaseTest.Writer::class, PadBridgeReleaseTest.FrameTiming::class])
@LooperMode(LooperMode.Mode.PAUSED)
class PadBridgeReleaseTest {
    private lateinit var bridge: PadBridge
    private var originalDeckPad = false

    @Before fun setUp() {
        originalDeckPad = SessionState.deckPad
        Writer.last = PadState()
        bridge = PadBridge(File("unused-test-ring"))
        assertTrue(bridge.start())
    }

    @After fun tearDown() {
        bridge.stop()
        SessionState.deckPad = originalDeckPad
    }

    @Test fun releaseClearsHeldSteamAndQuickAccessButtons() {
        SessionState.deckPad = true
        bridge.setSystemButtons(true, true)
        assertTrue(Writer.last.isDown(PadState.GUIDE))
        assertTrue(Writer.last.isDown(PadState.QAM))
        bridge.releaseAll()
        assertNeutral()
    }

    @Test fun releaseCancelsDelayedQuickAccessChord() {
        SessionState.deckPad = false
        bridge.triggerQam()
        val generation = generation()
        assertTrue(Writer.last.isDown(PadState.GUIDE))
        bridge.releaseAll()
        assertNeutral()
        callback("pressQamA", generation)
        callback("releaseQamA", generation)
        callback("releaseQamGuide", generation)
        assertNeutral()
    }

    @Test fun staleTapReleaseCannotReleaseNewQuickAccessTap() {
        SessionState.deckPad = true
        bridge.triggerQam()
        val oldGeneration = generation()
        bridge.releaseAll()
        bridge.triggerQam()
        callback("releaseQamTap", oldGeneration)
        assertTrue(Writer.last.isDown(PadState.QAM))
        callback("releaseQamTap", generation())
        assertNeutral()
    }

    private fun assertNeutral() {
        for (button in 0..PadState.QAM) assertFalse("button $button held", Writer.last.isDown(button))
        assertEquals(0f, Writer.last.leftX, 0f)
        assertEquals(0f, Writer.last.leftTrigger, 0f)
    }

    private fun generation() = PadBridge::class.java.getDeclaredField("qamChordGeneration").let {
        it.isAccessible = true
        it.getInt(bridge)
    }

    private fun callback(name: String, generation: Int) {
        PadBridge::class.java.getDeclaredMethod(name, Int::class.javaPrimitiveType).apply {
            isAccessible = true
        }.invoke(bridge, generation)
    }

    @Implements(FakeInputWriter::class)
    class Writer {
        @Implementation fun open() = true
        @Implementation fun close() {}
        @Implementation fun writePad(state: PadState) { last = PadState().also { it.copyFrom(state) } }
        companion object {
            @JvmStatic @Implementation fun __staticInitializer__() {}
            var last = PadState()
        }
    }

    @Implements(WaylandCompositor::class)
    class FrameTiming {
        companion object {
            @JvmStatic @Implementation fun __staticInitializer__() {}
            @JvmStatic @Implementation fun recentFrameIntervalMs() = 16L
        }
    }
}
