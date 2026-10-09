#!/usr/bin/env python3
"""Generate and verify an isolated ASan diagnostic build of the production recipe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError("Production recipe changed; inspect diagnostic integration anchor: " + old)
    return text.replace(old, new, 1)


def generate(recipe):
    recipe = replace_once(recipe, "git sudo zstd binutils curl", "git sudo zstd binutils curl python")
    recipe = replace_once(recipe, "  done\n}\nif declare -f prepare", "  done\n"
                          "  python /work/tools/pixel-probe/gamescope-asan.py prepare .\n"
                          "}\nif declare -f prepare")
    recipe = replace_once(recipe, "makepkg -A -s --noconfirm", "cat >> PKGBUILD <<'ASAN_BUILD'\n"
                          "options+=('!strip' '!debug' '!lto')\n"
                          'CFLAGS+=\\" -fsanitize=address -fno-omit-frame-pointer -fno-lto -g\\"\n'
                          'CXXFLAGS+=\\" -fsanitize=address -fno-omit-frame-pointer -fno-lto -g\\"\n'
                          'LDFLAGS+=\\" -fsanitize=address -fno-lto\\"\n'
                          "ASAN_BUILD\nmakepkg -A -s --noconfirm")
    recipe = replace_once(recipe, "strip --strip-unneeded out/usr/local/bin/gamescope || true",
                          "python tools/pixel-probe/gamescope-asan.py verify /work")
    return recipe


def prepare(source):
    path = source / "meson.build"
    text = path.read_text()
    text = replace_once(text, "  default_options: [", "  default_options: [\n"
                        "    'b_sanitize=address', 'b_lto=false', 'b_ndebug=false',\n"
                        "    'buildtype=debugoptimized', 'strip=false',\n")
    path.write_text(text)


def check_commands(commands):
    found = {"gamescope": 0, "wlroots": 0}
    for entry in commands:
        file = entry["file"].replace("\\", "/")
        group = "wlroots" if "subprojects/wlroots/" in file else "gamescope" if "/src/" in file and "subprojects/" not in file else None
        if group is None:
            continue
        args = entry.get("arguments") or shlex.split(entry["command"])
        if not any(a.startswith("-fsanitize=") and "address" in a.split("=", 1)[1].split(",") for a in args):
            raise RuntimeError("Missing ASan instrumentation: " + file)
        if "-fno-omit-frame-pointer" not in args or not any(re.fullmatch(r"-g(?:[0-9]|gdb[0-9]?)?", a) for a in args):
            raise RuntimeError("Missing frame pointers/debug information: " + file)
        if any(a == "-flto" or a.startswith("-flto=") for a in args):
            raise RuntimeError("LTO enabled in diagnostic build: " + file)
        found[group] += 1
    if not all(found.values()):
        raise RuntimeError("Need actual instrumented Gamescope and static wlroots compilation: " + str(found))
    return found


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT)


def verify(work):
    databases = list((work / "pkg/arch").rglob("compile_commands.json"))
    if len(databases) != 1:
        raise RuntimeError("Expected one actual Meson compile database: " + str(databases))
    commands = json.loads(databases[0].read_text())
    counts = check_commands(commands)
    binary = work / "out/usr/local/bin/gamescope"
    sections = run("readelf", "-SW", str(binary))
    dynamic = run("readelf", "-dW", str(binary))
    symbols = run("readelf", "-sW", str(binary))
    if ".debug_info" not in sections or "__asan_init" not in symbols:
        raise RuntimeError("Packaged Gamescope lost ASan or debug information")
    if "libwlroots" in dynamic:
        raise RuntimeError("Diagnostic Gamescope uses a shared wlroots instead of instrumented static fallback")
    libasan_name = re.findall(r"Shared library: \[(libasan[^]]+)\]", dynamic)
    if len(libasan_name) != 1:
        raise RuntimeError("Expected one dynamically linked ASan runtime")
    libasan = Path(run("gcc", "-print-file-name=libasan.so").strip()).resolve()
    if not libasan.is_file():
        raise RuntimeError("Compiler ASan runtime not found")
    target = work / "diagnostic"
    (target / "bin").mkdir(parents=True)
    (target / "lib").mkdir()
    shutil.copy2(binary, target / "bin/gamescope")
    shutil.copy2(libasan, target / "lib" / libasan_name[0])
    shutil.copy2(databases[0], target / "compile_commands.json")
    shutil.copy2(work / "pkg/arch/PKGBUILD", target / "PKGBUILD")
    probe = target / "bin/asan-probe"
    run("gcc", "-O1", "-g", "-fsanitize=address", "-fno-omit-frame-pointer",
        "-o", str(probe), str(work / "tools/pixel-probe/gamescope-asan-probe.c"))
    result = subprocess.run([str(probe)], env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=1"),
                            capture_output=True, text=True)
    (target / "probe-ci.log").write_text(result.stdout + result.stderr)
    if result.returncode == 0 or "AddressSanitizer: heap-use-after-free" not in result.stderr:
        raise RuntimeError("Intentional ASan probe did not produce the expected diagnostic")
    reports = []
    for path in (target / "bin/gamescope", target / "lib" / libasan_name[0], probe):
        reports.append(str(path.relative_to(target)) + "\n" + run("readelf", "-dW", str(path)) +
                       run("readelf", "-VW", str(path)) + run("readelf", "-nW", str(path)))
    (target / "elf-report.txt").write_text("\n".join(reports))
    inputs = [work / "tools/gamescope/build-in-arch.sh", work / "asan-build.sh",
              work / "tools/pixel-probe/gamescope-asan.py", work / "tools/pixel-probe/gamescope-asan-probe.c",
              *sorted((work / "tools/gamescope/patches").glob("*.patch"))]
    source = work / "pkg/arch/src/gamescope"
    if not (source / "meson.build").is_file():
        raise RuntimeError("Prepared Gamescope source directory is missing")
    # Preserve the prepared source identity, compiler, and actual flags for offline diagnosis.
    manifest = {"sourceCommit": os.environ.get("GITHUB_SHA", ""), "compiler": run("gcc", "--version"),
                "instrumentedCommands": counts,
                "gamescopeCommit": run("git", "-C", str(source), "rev-parse", "HEAD").strip(),
                "preparedSourceHashes": {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted(source.rglob("*")) if p.is_file() and ".git" not in p.parts and
                    (p.suffix in (".c", ".cpp", ".h", ".hpp") or p.name in ("meson.build", "meson_options.txt"))},
                "recipeAndPatches": {
                    str(p.relative_to(work)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
                "files": {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(target.rglob("*")) if p.is_file()}}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("generate", "prepare", "verify"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    if args.mode == "generate":
        print(generate(args.path.read_text()), end="")
    elif args.mode == "prepare":
        prepare(args.path)
    else:
        verify(args.path)


if __name__ == "__main__":
    main()
