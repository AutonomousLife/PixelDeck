"""Fail closed when the real diagnostic recipe or compilation loses instrumentation."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(ROOT / "tools/pixel-probe/gamescope-asan.py"))


def command(file, flags="-fsanitize=address -fno-omit-frame-pointer -fno-lto -g"):
    return {"file": file, "command": "gcc " + flags + " -c " + file}


class GamescopeAsanTest(unittest.TestCase):
    def test_generator_retains_production_patches_but_disables_stripping(self):
        recipe = (ROOT / "tools/gamescope/build-in-arch.sh").read_text()
        diagnostic = MODULE["generate"](recipe)
        self.assertIn("patch -p1 --no-backup-if-mismatch", diagnostic)
        self.assertIn("wlroots-0.20.2.tar.bz2", diagnostic)
        self.assertIn("options+=('!strip' '!debug' '!lto')", diagnostic)
        self.assertNotIn("strip --strip-unneeded out/usr/local/bin/gamescope", diagnostic)
        self.assertIn("gamescope-asan.py verify /work", diagnostic)
        self.assertIn("gamescope-asan.py prepare .", diagnostic)
        self.assertEqual((ROOT / "tools/gamescope/build-in-arch.sh").read_text(), recipe)

    def test_changed_recipe_anchor_is_rejected(self):
        recipe = (ROOT / "tools/gamescope/build-in-arch.sh").read_text()
        with self.assertRaisesRegex(RuntimeError, "Production recipe changed"):
            MODULE["generate"](recipe.replace("makepkg -A -s --noconfirm", "makepkg --different"))

    def test_actual_compile_commands_need_both_components(self):
        entries = [command("../src/wlserver.cpp"), command("../subprojects/wlroots/types/wlr_surface.c")]
        self.assertEqual(MODULE["check_commands"](entries), {"gamescope": 1, "wlroots": 1})
        with self.assertRaisesRegex(RuntimeError, "static wlroots"):
            MODULE["check_commands"](entries[:1])

    def test_each_missing_required_flag_and_lto_are_rejected(self):
        good = command("../src/wlserver.cpp")
        for flags in ("-g -fno-omit-frame-pointer", "-g -fsanitize=address",
                      "-fsanitize=address -fno-omit-frame-pointer", "-g -fsanitize=address -fno-omit-frame-pointer -flto"):
            for file in ("../src/rendervulkan.cpp", "../subprojects/wlroots/types/wlr_surface.c"):
                with self.subTest(flags=flags, file=file), self.assertRaises(RuntimeError):
                    MODULE["check_commands"]([good, command(file, flags)])


if __name__ == "__main__":
    unittest.main()
