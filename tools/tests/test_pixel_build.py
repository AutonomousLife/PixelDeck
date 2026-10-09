"""The Windows loop must reject stale sources, avoid caching unverified downloads and refresh staged files."""
import hashlib
import io
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import zipfile

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pixel-build.py"))
GLOBALS = MODULE["stage"].__globals__


class PixelBuildTest(unittest.TestCase):
    def stage_fixture(self, root, stamp_digest, existing, revision=None):
        """Fake pinned APK with one desktop script, plus a stamp recording an earlier digest."""
        apk = io.BytesIO()
        with zipfile.ZipFile(apk, "w") as z:
            z.writestr("assets/linuxfs/usr/local/bin/droiddeck-x", "fresh")
            z.writestr("META-INF/version-control-info.textproto",
                       'repositories { revision: "' + (revision or MODULE["UPSTREAM_SOURCE_COMMIT"]) + '" }')
        outer = root / "upstream.zip"
        with zipfile.ZipFile(outer, "w") as z:
            z.writestr("app.apk", apk.getvalue())
        digest = hashlib.sha256(outer.read_bytes()).hexdigest()
        stamp = root / "build/pixel-probe/staged-digest"
        stamp.parent.mkdir(parents=True)
        stamp.write_text((stamp_digest or digest) + "\n")
        staged = root / "app/src/main/assets/linuxfs/usr/local/bin/droiddeck-x"
        staged.parent.mkdir(parents=True)
        staged.write_text(existing)
        with patch.dict(GLOBALS, ROOT=root, CACHE=outer, DIGEST=digest, PIXEL_COMPONENTS=[],
                        UPSTREAM_NATIVE_INPUTS=[], NATIVE_COMPONENT=None):
            MODULE["stage"]()
        return staged, stamp, digest

    def test_new_apk_digest_replaces_stale_staged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            staged, stamp, digest = self.stage_fixture(Path(directory), "old-digest", existing="stale")
            self.assertEqual(staged.read_text(), "fresh")
            self.assertEqual(stamp.read_text(), digest + "\n")

    def test_unchanged_digest_keeps_local_staged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            # Stamp already matches the pinned digest, so a local edit is left alone.
            staged, _, _ = self.stage_fixture(Path(directory), None, existing="local edit")
            self.assertEqual(staged.read_text(), "local edit")

    def test_changed_archive_source_revision_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "source revision changed"):
                self.stage_fixture(root, "old-digest", "existing", revision="other-commit")
            self.assertEqual((root / "app/src/main/assets/linuxfs/usr/local/bin/droiddeck-x").read_text(),
                             "existing")

    def test_stale_sources_fail_before_artifact_fetch(self):
        with patch.dict(GLOBALS, PIXEL_COMPONENTS=[("runtime", 1, "archive", "wrong")],
                        UPSTREAM_NATIVE_INPUTS=[], NATIVE_COMPONENT=None):
            with self.assertRaisesRegex(RuntimeError, "runtime sources changed"):
                MODULE["stage"]()

    def test_each_upstream_native_group_rejects_modified_added_and_deleted_inputs(self):
        for group, patterns, _ in MODULE["UPSTREAM_NATIVE_INPUTS"]:
            for change in ("modify", "delete", "add"):
                with self.subTest(group=group, change=change), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    # Use the actual production patterns, including globs and fixed paths.
                    relative = patterns[0].replace("*", "original")
                    source = root / relative
                    source.parent.mkdir(parents=True)
                    source.write_bytes(b"baseline\n")
                    with patch.dict(GLOBALS, ROOT=root, PIXEL_COMPONENTS=[], NATIVE_COMPONENT=None):
                        expected = MODULE["input_digest"](patterns)
                        if change == "modify":
                            source.write_bytes(b"changed\n")
                        elif change == "delete":
                            source.unlink()
                        else:
                            glob = next((p for p in patterns if "*" in p), None)
                            if glob is None:
                                # Fixed-path groups cannot gain inputs without a pattern change.
                                continue
                            added = root / glob.replace("*", "added")
                            added.parent.mkdir(parents=True, exist_ok=True)
                            added.write_bytes(b"new source\n")
                        with patch.dict(GLOBALS, UPSTREAM_NATIVE_INPUTS=[(group, patterns, expected)]), \
                                patch.object(GLOBALS["subprocess"], "run") as fetch:
                            with self.assertRaisesRegex(RuntimeError, "rebuild the affected Linux prebuilts"):
                                MODULE["stage"]()
                            fetch.assert_not_called()

    def test_native_digest_ignores_checkout_scripts_and_test_sources_and_normalizes_crlf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "tools/linuxfs/preload/native.c"
            native.parent.mkdir(parents=True)
            native.write_bytes(b"native\n")
            patterns = [p for _, group_patterns, _ in MODULE["UPSTREAM_NATIVE_INPUTS"]
                        for p in group_patterns]
            with patch.dict(GLOBALS, ROOT=root):
                expected = MODULE["input_digest"](patterns)
                for relative in ("tools/linuxfs/desktop/droiddeck-gpu",
                                 "tools/linuxfs/overlay/usr/local/bin/droiddeck-session",
                                 "tools/linuxfs/preload/tests/example.c"):
                    script = root / relative
                    script.parent.mkdir(parents=True, exist_ok=True)
                    script.write_text("checkout change")
                native.write_bytes(b"native\r\n")
                self.assertEqual(MODULE["input_digest"](patterns), expected)

    def test_every_declared_native_input_pattern_changes_the_digest(self):
        for group, patterns, _ in MODULE["UPSTREAM_NATIVE_INPUTS"]:
            for pattern in patterns:
                with self.subTest(group=group, pattern=pattern), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    source = root / pattern.replace("*", "input")
                    source.parent.mkdir(parents=True)
                    source.write_text("baseline")
                    with patch.dict(GLOBALS, ROOT=root):
                        expected = MODULE["input_digest"](patterns)
                        source.write_text("modified native input")
                        self.assertNotEqual(MODULE["input_digest"](patterns), expected)

    def test_bad_download_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.zip"
            with patch.object(GLOBALS["subprocess"], "run") as fetch:
                fetch.return_value.stdout = b"wrong artifact"
                with self.assertRaisesRegex(RuntimeError, "Downloaded artifact checksum mismatch"):
                    MODULE["checked_archive"](path, "example", "0" * 64)
            self.assertFalse(path.exists())

    def test_native_artifact_stages_all_outputs_and_rejects_wrong_manifest(self):
        outputs = ("libfakeinput.so", "x86_64/libblsession.so", "x86_64/libfakeinput.so",
                   "x86_64/libfaultreport.so", "x86_64/libthunkaudit.so", "x86_64/libvulkan-thunk.so",
                   "i386/libblsession.so", "i386/libfakeinput.so")
        for matching in (True, False):
            with self.subTest(matching=matching), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _, _, upstream_digest = self.stage_fixture(root, None, "existing")
                expected = hashlib.sha256().hexdigest()  # This fixture has no native sources.
                archive = root / "build/pixel-components/native-123.zip"
                archive.parent.mkdir(parents=True)
                with zipfile.ZipFile(archive, "w") as z:
                    z.writestr("source.json", json.dumps({"sourceDigest": expected if matching else "wrong"}))
                    for relative in outputs:
                        z.writestr(relative, ("rebuilt " + relative).encode())
                    z.writestr("../../outside", "must not extract")
                digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                destination = root / "app/src/main/assets/linuxfs"
                for relative in outputs:
                    file = destination / relative
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_bytes(b"old native")
                with patch.dict(GLOBALS, ROOT=root, CACHE=root / "upstream.zip", DIGEST=upstream_digest,
                                PIXEL_COMPONENTS=[], UPSTREAM_NATIVE_INPUTS=[],
                                NATIVE_COMPONENT=(123, digest, expected)):
                    if matching:
                        MODULE["stage"]()
                    else:
                        with self.assertRaisesRegex(RuntimeError, "source digest disagrees"):
                            MODULE["stage"]()
                for relative in outputs:
                    self.assertEqual((destination / relative).read_bytes(),
                                     ("rebuilt " + relative).encode() if matching else b"old native")
                self.assertFalse((root / "app/src/main/outside").exists())
                self.assertEqual((destination / "usr/local/bin/droiddeck-x").read_text(), "existing")


if __name__ == "__main__":
    unittest.main()
