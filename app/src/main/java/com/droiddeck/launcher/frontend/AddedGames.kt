package com.droiddeck.launcher.frontend

import android.content.Context
import android.util.Log
import com.droiddeck.launcher.runtime.LinuxRuntime
import org.json.JSONObject
import org.json.JSONArray
import com.droiddeck.launcher.session.GameStorage
import com.droiddeck.launcher.session.SessionPrefs
import java.io.File
import java.util.zip.CRC32

/** Windows game folders shared with the Steam session. */
object AddedGames {
    private const val TAG = "AddedGames"
    private const val LIBRARY = "/mnt/droiddeck-sd"
    private const val LEGACY_LIBRARY = "/mnt/bannerlator-sd"

    class Game(
        val folder: File, val name: String, val exe: File, val guestExe: String, val guestDir: String,
        /** The client's 32-bit appid for this shortcut, as an unsigned value. */
        val appId: Long,
        /** What steam://rungameid/ takes for a shortcut. */
        val gameId: Long,
        val candidates: List<File>,
        val steamAppId: Int? = null,
        val nonSteam: Boolean = false,
    ) {
        fun folderName(): String = folder.name
    }

    /** One Games folder and where the session sees it. */
    class Root(val host: File, val guest: String)

    data class Selection(val folder: File, val exe: File, val name: String = folder.name)
    private data class Entry(val selection: Selection, val id: Long)

    private fun entries(context: Context): List<Entry> = runCatching {
        val array = JSONArray(SessionPrefs.addedGameEntries(context))
        List(array.length()) { i ->
            val o = array.getJSONObject(i)
            Entry(Selection(File(o.getString("folder")), File(o.getString("exe")), o.getString("name")), o.getLong("id"))
        }
    }.getOrDefault(emptyList())

    /** Explicit executable choices keep their identity when their name or target changes. */
    fun add(context: Context, selection: Selection) {
        require(selection.name.isNotBlank())
        require(selection.exe.isFile && selection.exe.extension.equals("exe", true))
        require(selection.folder.isDirectory && selection.exe.canonicalPath.startsWith(selection.folder.canonicalPath + "/"))
        val old = entries(context)
        val key = selection.folder.canonicalPath
        val existing = old.firstOrNull { it.selection.folder.canonicalPath == key }
        val scanned = scan(context).firstOrNull { it.folder.canonicalPath == key }
        val id = existing?.id ?: scanned?.appId ?: (CRC32().apply {
            update((selection.exe.canonicalPath + selection.name).toByteArray())
        }.value or 0x80000000L)
        val array = JSONArray()
        for (entry in old.filterNot { it.selection.folder.canonicalPath == key } + Entry(selection, id)) {
            array.put(JSONObject().put("folder", entry.selection.folder.path).put("exe", entry.selection.exe.path)
                .put("name", entry.selection.name).put("id", entry.id))
        }
        SessionPrefs.setAddedGameEntries(context, array.toString())
        SessionPrefs.setAddedGameExe(context, selection.folder.path, selection.exe.path)
    }

    fun changeExecutable(context: Context, folder: String, exe: String) {
        val current = scan(context).firstOrNull { it.folder.path == folder } ?: return
        require(File(exe).isFile && exe.endsWith(".exe", true))
        require(File(exe).canonicalPath.startsWith(current.folder.canonicalPath + "/"))
        SessionPrefs.setAddedGameId(context, folder, current.appId)
        SessionPrefs.setAddedGameExe(context, folder, exe)
    }

    fun suggestedFolder(exe: File): File {
        var folder = requireNotNull(exe.parentFile)
        while (folder.name.lowercase() in setOf("bin", "binaries", "win64", "win32", "x64", "x86", "amd64")) {
            folder = folder.parentFile ?: break
        }
        return folder
    }

    /** Accept one game or a collection; preview only launchable games, not installers. */
    fun preview(folder: File): List<Selection> {
        val children = folder.listFiles().orEmpty()
        if (children.any { it.isFile && it.extension.equals("exe", true) && !SKIP.matches(it.name) } ||
            children.any { it.isDirectory && (it.name.equals("Binaries", true) || it.name.equals("bin", true)) }) {
            return candidates(folder).firstOrNull()?.let { listOf(Selection(folder, it)) } ?: emptyList()
        }
        return children.filter { it.isDirectory }.sortedBy { it.name.lowercase() }
            .mapNotNull { game -> candidates(game).firstOrNull()?.let { Selection(game, it) } }
    }

    /**
     * The chosen folders with their guest paths: /root/Games/<folder name>, or with a short hash of
     * the host path when two chosen folders share a name (so a folder's guest path, and with it
     * every shortcut's appid, does not change when another folder is added or removed).
     */
    fun roots(context: Context): List<Root> {
        val hosts = SessionPrefs.addedGamesDirs(context).map { File(it) }
        val names = hosts.groupingBy { it.name.lowercase() }.eachCount()
        val collections = hosts.map { host ->
            val name = host.name.ifEmpty { "games" }
            val guestName = if ((names[name.lowercase()] ?: 0) > 1) name + "-" + "%08x".format(CRC32().apply { update(host.path.toByteArray()) }.value).take(4) else name
            Root(host, "$GUEST_DIR/$guestName")
        }
        return collections + entries(context).map { it.selection.folder }.distinctBy { it.canonicalPath }
            .filter { folder -> collections.none { folder.canonicalPath == it.host.canonicalPath || folder.canonicalPath.startsWith(it.host.canonicalPath + "/") } }
            .map { Root(it, "$GUEST_DIR/game-" + "%08x".format(CRC32().apply { update(it.canonicalPath.toByteArray()) }.value)) }
    }

    private val SKIP = Regex(
        "(?i)^(unins.*|setup.*|.*redist.*|vcredist.*|dxsetup.*|dxwebsetup.*|.*crash.*|.*report.*|dotnet.*|directx.*|.*prereq.*" +
            "|.*installer.*|.*uninstall.*|.*updater?.*|.*config(ur.*)?|.*settings.*|.*editor.*|.*server.*|.*benchmark.*|.*helper.*|.*eac.*|.*easyanticheat.*|.*battleye.*)\\.exe$",
    )

    /** Under here the chosen Games folders are bound inside the session, one each. */
    const val GUEST_DIR = "/root/Games"

    /** Where a host path appears inside the session, or null when the session cannot see it. */
    fun guestPath(context: Context, host: File): String? {
        val path = host.canonicalPath
        // The Games folders are bound on their own, so a folder anywhere - an SD card, a USB
        // drive - works without being inside one of the other binds.
        for (root in roots(context)) {
            val dir = root.host.canonicalPath
            if (path == dir) return root.guest
            if (path.startsWith("$dir/")) return root.guest + "/" + path.removePrefix("$dir/")
        }
        SessionPrefs.romsDir(context).takeIf { it.isNotEmpty() }?.let { roms ->
            val dir = File(roms).canonicalPath
            if (path.startsWith("$dir/")) return "/root/ROMs/" + path.removePrefix("$dir/")
        }
        GameStorage.effective(context)?.let { lib ->
            val dir = File(lib.path).canonicalPath
            if (path.startsWith("$dir/")) return "$LIBRARY/" + path.removePrefix("$dir/")
        }
        return null
    }

    /** The .exe files a game folder offers, best first. */
    fun candidates(folder: File): List<File> {
        val exes = ArrayList<File>()
        folder.walkTopDown().maxDepth(4).filter { it.isFile && it.extension.equals("exe", true) && !SKIP.matches(it.name) }.forEach(exes::add)
        val key = folder.name.lowercase().replace(Regex("[^a-z0-9]"), "")
        return exes.sortedWith(
            compareByDescending<File> { it.parentFile == folder }
                .thenByDescending { it.nameWithoutExtension.lowercase().replace(Regex("[^a-z0-9]"), "").let { n -> n == key || key.startsWith(n) || n.startsWith(key) } }
                .thenByDescending { it.length() },
        )
    }

    fun scan(context: Context): List<Game> {
        val out = ArrayList<Game>()
        val explicit = entries(context)
        val explicitFolders = explicit.map { it.selection.folder.canonicalPath }.toSet()
        for (entry in explicit) {
            val selection = entry.selection
            scanGame(context, selection.folder, out, selection, entry.id)
        }
        val folders = SessionPrefs.addedGamesDirs(context).map(::File) + listOfNotNull(
            GameStorage.effective(context)?.let { File(it.path) },
            GameStorage.effective(context)?.let { File(it.path, "steamapps/common") },
        )
        for (dir in folders.distinctBy { it.absolutePath }) {
            if (!dir.isDirectory) { Log.w(TAG, "$dir is not a folder; skipped"); continue }
            val steamInstalls = steamInstallDirs(dir)
            val selectedFolders = if (dir in SessionPrefs.addedGamesDirs(context).map(::File)) preview(dir).map { it.folder }
                else dir.listFiles { f -> f.isDirectory }?.sortedBy { it.name.lowercase() } ?: emptyList()
            for (folder in selectedFolders) {
                if (folder.name.lowercase() in steamInstalls || folder.canonicalPath in explicitFolders) continue
                scanGame(context, folder, out)
            }
        }
        return out.distinctBy { it.folder.canonicalPath }
    }

    /**
     * The folders under a library's steamapps/common that a manifest beside it already claims.
     * Steam lists those itself, so a shortcut would only add a non-Steam copy of the game. Steam
     * may lowercase installdir on Android's case-insensitive storage, so names compare lowercased.
     */
    internal fun steamInstallDirs(dir: File): Set<String> {
        val steamapps = dir.parentFile?.takeIf { dir.name == "common" && it.name == "steamapps" } ?: return emptySet()
        return steamapps.listFiles { f -> f.isFile && f.name.startsWith("appmanifest_") && f.name.endsWith(".acf") }
            .orEmpty()
            .mapNotNull { manifest ->
                runCatching { INSTALL_DIR.find(manifest.readText())?.groupValues?.get(1)?.trim()?.lowercase() }.getOrNull()
            }
            .filter { it.isNotEmpty() }
            .toSet()
    }

    private val INSTALL_DIR = Regex("\"installdir\"\\s*\"([^\"]*)\"", RegexOption.IGNORE_CASE)

    private fun scanGame(context: Context, folder: File, out: MutableList<Game>, selection: Selection? = null, id: Long? = null) {
        run {
            val candidates = candidates(folder)
            val chosen = SessionPrefs.addedGameExe(context, folder.path).takeIf { it.isNotEmpty() }?.let { File(it) }?.takeIf { it.isFile }
            val exe = if (selection != null) chosen ?: selection.exe.takeIf { it.isFile } ?: return
                else chosen ?: candidates.firstOrNull() ?: return
            val guestExe = guestPath(context, exe)
            if (guestExe == null) { Log.w(TAG, "${folder.name}: the session cannot see ${exe.path}"); return }
            val guestDir = guestPath(context, exe.parentFile ?: folder) ?: return
            val name = selection?.name ?: folder.name
            // Keyed by the pre-rename path so shortcut ids, and the prefixes and saves under them, stay put.
            val crc = CRC32().apply { update(("\"${guestExe.replaceFirst(Regex("^$LIBRARY/"), "$LEGACY_LIBRARY/")}\"" + name).toByteArray()) }.value
            val appId = id ?: SessionPrefs.addedGameId(context, folder.path).takeIf { it != 0L } ?: (crc or 0x80000000L)
            val steamRoot = File(LinuxRuntime.rootDir(context), "root/.local/share/Steam")
            val steamId = if (selection != null) null else steamRoute(steamRoot, appId)
            out.add(Game(folder, name, exe, guestExe, guestDir, appId,
                steamId?.toLong() ?: ((appId shl 32) or 0x02000000L), candidates, steamId, selection != null))
        }
    }

    private fun steamRoute(root: File, appId: Long): Int? = runCatching {
        val users = File(root, "config/loginusers.vdf").readText()
        val blocks = Regex(""""(\d{5,})"\s*\{([^}]*)\}""")
        val recent = blocks.findAll(users).firstOrNull { Regex(""""MostRecent"\s*"1"""").containsMatchIn(it.groupValues[2]) }
            ?: return@runCatching null
        val account = recent.groupValues[1].toLong() - 76561197960265728L
        JSONObject(File(root, "userdata/$account/config/.droiddeck-routes.json").readText())
            .optInt(appId.toString()).takeIf { it > 0 }
    }.getOrNull()

    fun pending(context: Context, game: Game): Boolean = runCatching {
        val array = JSONArray(File(context.filesDir, "session/added-games.json").readText())
        (0 until array.length()).none { i ->
            val o = array.getJSONObject(i)
            o.getLong("appid") == game.appId && o.getString("exe") == game.guestExe && o.getString("name") == game.name
        }
    }.getOrDefault(true)

    /** The list the session hands the runtime's shortcuts writer; one file per session start. */
    fun writeListing(context: Context, games: List<Game>): File {
        val file = File(context.filesDir, "session/added-games.json").apply { parentFile?.mkdirs() }
        val json = StringBuilder("[")
        games.forEachIndexed { i, g ->
            if (i > 0) json.append(',')
            json.append("{\"name\":").append(quote(g.name)).append(",\"exe\":").append(quote(g.guestExe))
                .append(",\"nonSteam\":").append(g.nonSteam)
                .append(",\"folder\":").append(quote(guestPath(context, g.folder) ?: g.guestDir))
                .append(",\"dir\":").append(quote(g.guestDir)).append(",\"appid\":").append(g.appId)
            // The art, as the session sees it: the app's cache is bound at its own path, a file in
            // the game's folder at the folder's guest path.
            val art = AddedGameArt.resolve(context, g)
            val pieces = listOf("p" to art.portrait, "header" to art.header, "hero" to art.hero, "logo" to art.logo, "icon" to art.icon)
                .mapNotNull { (k, f) -> f?.let { file -> artGuestPath(context, file)?.let { k to it } } }
            if (pieces.isNotEmpty()) json.append(",\"art\":{").append(pieces.joinToString(",") { (k, v) -> quote(k) + ":" + quote(v) }).append('}')
            json.append('}')
        }
        file.writeText(json.append(']').toString())
        return file
    }

    private fun artGuestPath(context: Context, file: File): String? {
        val files = context.filesDir.absolutePath
        if (file.absolutePath.startsWith("$files/")) return file.absolutePath
        return guestPath(context, file)
    }

    private fun quote(s: String): String = JSONObject.quote(s)
}
