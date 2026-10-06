"""The Windows loop must reject stale sources and avoid caching unverified downloads."""
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "pixel-build.py"))
GLOBALS = MODULE["stage"].__globals__


class PixelBuildTest(unittest.TestCase):
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
