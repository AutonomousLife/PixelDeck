package com.droiddeck.launcher.frontend

import com.droiddeck.launcher.session.SessionPrefs
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [33])
class AddedGameImportTest {
    @get:Rule val tmp = TemporaryFolder()
    private val context get() = RuntimeEnvironment.getApplication()

    @Before fun reset() {
        SessionPrefs.setAddedGamesDirs(context, emptyList())
        SessionPrefs.setAddedGameEntries(context, "[]")
        SessionPrefs.setGameStorage(context, SessionPrefs.GAME_STORAGE_OFF, "")
        File(context.filesDir, "session/added-games.json").delete()
    }

    private fun exe(folder: File, path: String) = File(folder, path).apply { parentFile!!.mkdirs(); writeText("game") }

    @Test fun previewsEitherOneGameOrACollectionAndSkipsInstallers() {
        val collection = tmp.newFolder("Games")
        val first = File(collection, "Example").apply { mkdirs() }
        val second = File(collection, "Other").apply { mkdirs() }
        exe(first, "Example.exe")
        exe(first, "setup.exe")
        exe(second, "Binaries/Win64/Other.exe")
        exe(File(collection, "Installer"), "setup.exe")
        assertEquals(listOf("Example", "Other"), AddedGames.preview(collection).map { it.name })
        assertEquals(first, AddedGames.preview(first).single().folder)
        assertEquals(second, AddedGames.preview(second).single().folder)
    }

    @Test fun individuallySelectedNestedExecutableIsBoundAndListedImmediately() {
        val folder = tmp.newFolder("Example")
        val file = exe(folder, "Binaries/Win64/Custom.exe")
        assertEquals(folder, AddedGames.suggestedFolder(file))
        AddedGames.add(context, AddedGames.Selection(folder, file, "My mod"))
        val game = AddedGames.scan(context).single()
        assertEquals("My mod", game.name)
        assertTrue(game.nonSteam)
        assertNull(game.steamAppId)
        assertEquals(folder, AddedGames.roots(context).single().host)
        assertTrue(game.guestExe.endsWith("/Binaries/Win64/Custom.exe"))
        assertTrue(AddedGames.pending(context, game))
        assertEquals("My mod", Library.launchableGames(context).single().name)
        AddedGames.writeListing(context, listOf(game))
        assertFalse(AddedGames.pending(context, game))
    }

    @Test fun steamLibraryContainerIsNotImportedAsAGame() {
        val library = tmp.newFolder("Library")
        exe(library, "steamapps/common/Owned/Owned.exe")
        val unowned = exe(library, "steamapps/common/Other/Binaries/Win64/Other.exe")
        File(library, "steamapps/appmanifest_123.acf").writeText("\"installdir\" \"Owned\"")
        SessionPrefs.setGameStorage(context, library.path, "Library")
        assertTrue(AddedGames.candidates(File(library, "steamapps")).isEmpty())
        assertTrue(AddedGames.preview(library).isEmpty())
        assertEquals(unowned, AddedGames.scan(context).single().exe)
        assertEquals("Other", AddedGames.scan(context).single().name)
    }

    @Test fun editingTargetAndNameKeepsShortcutIdentityAndMarksItPending() {
        val folder = tmp.newFolder("Example")
        val first = exe(folder, "Example.exe")
        val alternate = exe(folder, "Mod.exe")
        AddedGames.add(context, AddedGames.Selection(folder, first))
        val original = AddedGames.scan(context).single()
        AddedGames.writeListing(context, listOf(original))
        AddedGames.changeExecutable(context, folder.path, alternate.path)
        val edited = AddedGames.scan(context).single()
        assertEquals(original.gameId, edited.gameId)
        assertEquals(alternate, edited.exe)
        assertTrue(AddedGames.pending(context, edited))
        AddedGames.add(context, AddedGames.Selection(folder, alternate, "Renamed mod"))
        assertEquals(original.gameId, AddedGames.scan(context).single().gameId)
    }

    @Test fun existingFolderImportsKeepTheirIdentityWhenChangingExecutable() {
        val collection = tmp.newFolder("Games")
        val folder = File(collection, "Example").apply { mkdirs() }
        exe(folder, "Example.exe")
        val alternate = exe(folder, "Mod.exe")
        SessionPrefs.setAddedGamesDirs(context, listOf(collection.path))
        val original = AddedGames.scan(context).single()
        AddedGames.changeExecutable(context, folder.path, alternate.path)
        assertEquals(original.appId, AddedGames.scan(context).single().appId)
        assertFalse(AddedGames.scan(context).single().nonSteam)
    }

    @Test fun overlappingFolderAndIndividualImportsDoNotDuplicateAGame() {
        val collection = tmp.newFolder("Games")
        val folder = File(collection, "Example").apply { mkdirs() }
        val file = exe(folder, "Example.exe")
        AddedGames.add(context, AddedGames.Selection(folder, file))
        val original = AddedGames.scan(context).single().gameId
        SessionPrefs.setAddedGamesDirs(context, listOf(collection.path))
        assertEquals(1, AddedGames.roots(context).size)
        assertEquals(original, AddedGames.scan(context).single().gameId)
    }

    @Test fun executableOutsideGameFolderIsRejectedWithoutChangingEntry() {
        val folder = tmp.newFolder("Example")
        val file = exe(folder, "Example.exe")
        val outside = exe(tmp.newFolder("Other"), "Other.exe")
        AddedGames.add(context, AddedGames.Selection(folder, file))
        assertThrows(IllegalArgumentException::class.java) { AddedGames.changeExecutable(context, folder.path, outside.path) }
        assertEquals(file, AddedGames.scan(context).single().exe)
    }

    @Test fun aSingleGameFolderCanBeImportedWithoutAParentCollection() {
        val folder = tmp.newFolder("Example")
        val file = exe(folder, "Example.exe")
        SessionPrefs.setAddedGamesDirs(context, listOf(folder.path))
        assertEquals(file, AddedGames.scan(context).single().exe)
    }

    @Test fun missingExplicitTargetDoesNotSilentlySwitchToAnotherExecutable() {
        val folder = tmp.newFolder("Example")
        val file = exe(folder, "Mod.exe")
        exe(folder, "Example.exe")
        SessionPrefs.setAddedGamesDirs(context, listOf(folder.parentFile!!.path))
        AddedGames.add(context, AddedGames.Selection(folder, file))
        file.delete()
        assertTrue(AddedGames.scan(context).isEmpty())
    }

    @Test fun storageAliasesShareTheExistingBindWithoutLosingTheManualGame() {
        val collection = tmp.newFolder("Games")
        val folder = File(collection, "Example").apply { mkdirs() }
        val file = exe(folder, "Example.exe")
        val alias = File(tmp.root, "Alias")
        java.nio.file.Files.createSymbolicLink(alias.toPath(), collection.toPath())
        SessionPrefs.setAddedGamesDirs(context, listOf(alias.path))
        AddedGames.add(context, AddedGames.Selection(folder, file))
        assertEquals(1, AddedGames.roots(context).size)
        assertTrue(AddedGames.scan(context).single().guestExe.endsWith("/Example/Example.exe"))
    }
}
