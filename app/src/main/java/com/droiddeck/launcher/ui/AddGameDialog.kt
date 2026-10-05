package com.droiddeck.launcher.ui

import android.app.Activity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.droiddeck.launcher.R
import com.droiddeck.launcher.files.InAppFilePicker
import com.droiddeck.launcher.frontend.AddedGames
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

@Composable
internal fun AddGameDialog(onDismiss: () -> Unit, onAdd: (AddedGames.Selection) -> Unit, onImport: (File) -> Unit) {
    val context = LocalContext.current
    val shown = rememberShown(onDismiss)
    val close = { shown.targetState = false }
    var executable by rememberSaveable { mutableStateOf<String?>(null) }
    var gameFolder by rememberSaveable { mutableStateOf<String?>(null) }
    var importFolder by rememberSaveable { mutableStateOf<String?>(null) }
    var name by rememberSaveable { mutableStateOf("") }
    var advanced by rememberSaveable { mutableStateOf(false) }
    val pickExecutable = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) InAppFilePicker.pickedFile(result.data)?.let { exe ->
            executable = exe.path
            gameFolder = AddedGames.suggestedFolder(exe).path
            name = AddedGames.suggestedFolder(exe).name.takeUnless { it.equals("Download", true) || it.equals("Downloads", true) }
                ?: exe.nameWithoutExtension
            importFolder = null
        }
    }
    val pickImport = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) InAppFilePicker.pickedPath(result.data)?.let {
            importFolder = it; executable = null
        }
    }
    val pickGameFolder = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) InAppFilePicker.pickedPath(result.data)?.let { gameFolder = it }
    }
    val preview by produceState<List<AddedGames.Selection>?>(null, importFolder) {
        value = null
        value = importFolder?.let { withContext(Dispatchers.IO) { AddedGames.preview(File(it)) } }
    }
    val file = executable?.let(::File)
    val folder = gameFolder?.let(::File)
    val valid = file != null && folder != null && name.isNotBlank() &&
        file.canonicalPath.startsWith(folder.canonicalPath + "/")
    AppDialog(shown, close, "addGame", wide = false) {
        DialogHeader(stringResource(R.string.content_games), stringResource(R.string.games_add))
        PrimaryButton(stringResource(if (file == null) R.string.games_choose_exe else R.string.games_change_exe),
            modifier = Modifier.fillMaxWidth()) {
            pickExecutable.launch(InAppFilePicker.buildIntent(context, listOf("exe"), context.getString(R.string.games_choose_exe), gameFolder))
        }
        SecondaryButton(stringResource(R.string.games_import_folder), modifier = Modifier.fillMaxWidth()) {
            pickImport.launch(InAppFilePicker.buildDirIntent(context, context.getString(R.string.games_import_folder), importFolder))
        }
        if (file != null) {
            AdbTextField(name, { name = it.take(80) }, stringResource(R.string.add_app_name), KeyboardType.Text, ImeAction.Done, compact = true)
            Text(file.path, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
            SecondaryButton(stringResource(R.string.drawer_effects_advanced), compact = true) { advanced = !advanced }
            if (advanced) ActionRow(stringResource(R.string.games_game_folder), gameFolder, stringResource(R.string.add_app_change_file)) {
                pickGameFolder.launch(InAppFilePicker.buildDirIntent(context, context.getString(R.string.games_game_folder), gameFolder))
            }
        }
        if (importFolder != null) {
            Text(importFolder!!, color = MaterialTheme.colorScheme.onSurfaceVariant, fontSize = 12.sp)
            when {
                preview == null -> Small(stringResource(R.string.games_scanning))
                preview!!.isEmpty() -> Note(stringResource(R.string.games_import_empty))
                else -> Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (game in preview!!) {
                        Text(game.name, color = MaterialTheme.colorScheme.onBackground)
                        Small(game.exe.name)
                    }
                }
            }
        }
        DialogFooter(
            note = if (file != null && !valid && name.isNotBlank()) stringResource(R.string.games_exe_outside_folder) else null,
            confirm = if (importFolder != null) pluralStringResource(R.plurals.games_import_count, preview?.size ?: 0, preview?.size ?: 0) else stringResource(R.string.add_app_confirm),
            enabled = if (importFolder != null) !preview.isNullOrEmpty() else valid,
            onCancel = close,
            onConfirm = {
                if (importFolder != null) onImport(File(importFolder!!))
                else if (valid) onAdd(AddedGames.Selection(folder!!, file!!, name.trim()))
                close()
            },
        )
    }
}
