package com.droiddeck.launcher.core

import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File
import java.nio.file.AccessDeniedException
import java.nio.file.Files
import java.nio.file.OpenOption
import java.nio.file.StandardOpenOption

class FileUtilsMoveTest {
    @Test fun windowsMoveWaitsForABriefFileLock() {
        assumeTrue(File.separatorChar == '\\')
        val root = Files.createTempDirectory("pixeldeck-move-")
        val source = Files.createDirectory(root.resolve("staged"))
        val target = root.resolve("installed")
        val library = source.resolve("driver.so")
        Files.write(library, "driver".toByteArray())
        // JDK-only option, accessed reflectively because Android does not expose it.
        val noShareDelete = Class.forName("com.sun.nio.file.ExtendedOpenOption")
            .enumConstants!!.first { (it as Enum<*>).name == "NOSHARE_DELETE" } as OpenOption
        val held = Files.newByteChannel(library, StandardOpenOption.READ, noShareDelete)
        try {
            try {
                Files.move(source, target)
                fail("The test lock must deny an immediate directory move")
            } catch (_: AccessDeniedException) { }
            val release = Thread { Thread.sleep(50); held.close() }.apply { start() }
            FileUtils.moveDirectory(source.toFile(), target.toFile())
            release.join()
            assertEquals("driver", String(Files.readAllBytes(target.resolve("driver.so"))))
        } finally {
            held.close()
            for (path in listOf(library, source, target.resolve("driver.so"), target, root)) Files.deleteIfExists(path)
        }
    }
}
