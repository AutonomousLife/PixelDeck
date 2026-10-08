"""The Windows loop must reject stale sources, avoid caching unverified downloads and refresh staged files."""
import hashlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import zipfile

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pixel-build.py"))
GLOBALS = MODULE["stage"].__globals__


class PixelBuildTest(unittest.TestCase):
    def stage_fixture(self, root, stamp_digest, existing):
        """Fake pinned APK with one desktop script, plus a stamp recording an earlier digest."""
        apk = io.BytesIO()
        with zipfile.ZipFile(apk, "w") as z:
            z.writestr("assets/linuxfs/usr/local/bin/droiddeck-x", "fresh")
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
        with patch.dict(GLOBALS, ROOT=root, CACHE=outer, DIGEST=digest, PIXEL_COMPONENTS=[]):
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

    def test_stale_sources_fail_before_artifact_fetch(self):
        with patch.dict(GLOBALS, PIXEL_COMPONENTS=[("runtime", 1, "archive", "wrong")]):
            with self.assertRaisesRegex(RuntimeError, "runtime sources changed"):
                MODULE["stage"]()

    def test_bad_download_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.zip"
            with patch.object(GLOBALS["subprocess"], "run") as fetch:
                fetch.return_value.stdout = b"wrong artifact"
                with self.assertRaisesRegex(RuntimeError, "Downloaded artifact checksum mismatch"):
                    MODULE["checked_archive"](path, "example", "0" * 64)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
