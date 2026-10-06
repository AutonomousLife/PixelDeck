#!/usr/bin/env python3
"""Incrementally build PixelDeck on Windows; stage unchanged Linux prebuilts once."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = "repos/Droid-Deck/DroidDeck/actions/artifacts/11390530317"
DIGEST = "2400d77fcd27220325ddb69947592270361cb2813be8a49ec95844b176bceb9d"
CACHE = ROOT / "build/pixel-probe/upstream-ci.zip"

# Keep these cached: Actions artifacts expire. Source builds live in the matching workflows.
PIXEL_COMPONENTS = [
    # Built at 87fea13 and ef8575b respectively; source digests detect stale native binaries.
    ("runtime", 11412689757, "2521cb89e66150616ef0ee0485726379e126336520117dd4ca17b484c4592359",
     "d025bc3abc9bda59a198ec6bdd185e1f3292b4a2942a6fe0f12e0c52a255d639"),
    ("gamescope", 11413232368, "afdf55f704881e2a4b31e7304057d26a3bb2d8df722c628876290428328595de",
     "cb3a827b5c0049fa30326e30b2e1046a1a73f40433636d8fbeb29cc9452ad5c4"),
]


def source_digest(component):
    directory = "tools/linuxfs/preload" if component == "runtime" else "tools/gamescope"
    digest = hashlib.sha256()
    for path in sorted((ROOT / directory).rglob("*")):
        if not path.is_file():
            continue
        selected = (path.suffix in (".c", ".h") and "tests" not in path.parts) if component == "runtime" else (
            path.suffix == ".patch" or path.name in ("build-in-arch.sh", "runtime-sonames.txt"))
        if selected:
            digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" +
                          path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def checked_archive(path, api, digest):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fetched = subprocess.run(["gh", "api", api + "/zip"], capture_output=True, check=True, timeout=120)
        if hashlib.sha256(fetched.stdout).hexdigest() != digest:
            raise RuntimeError("Downloaded artifact checksum mismatch: " + api)
        partial = path.with_suffix(".part")
        partial.write_bytes(fetched.stdout)
        partial.replace(path)
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise RuntimeError("Artifact checksum mismatch: " + str(path))
    return zipfile.ZipFile(path)


def stage():
    for component, _, _, expected in PIXEL_COMPONENTS:
        if source_digest(component) != expected:
            raise RuntimeError(f"{component} sources changed: rebuild its Linux CI artifact and update PIXEL_COMPONENTS")
    with checked_archive(CACHE, ARTIFACT, DIGEST) as z:
        apk_name = next(n for n in z.namelist() if n.endswith(".apk"))
        with zipfile.ZipFile(io.BytesIO(z.read(apk_name))) as apk:
            for name in apk.namelist():
                if name.endswith("/"):
                    continue
                if name.startswith(("assets/linuxfs/", "assets/droiddeck-esync/")):
                    destination = ROOT / "app/src/main" / name
                elif name in ("lib/arm64-v8a/libproot.so", "lib/arm64-v8a/libproot-loader.so"):
                    destination = ROOT / "app/src/main/jniLibs" / name.removeprefix("lib/")
                else:
                    continue
                destination = destination.resolve()
                if not destination.is_relative_to((ROOT / "app/src/main").resolve()):
                    raise RuntimeError("Invalid artifact path: " + name)
                # Only generated/ignored inputs; current checkout scripts are staged by Gradle.
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(apk.read(name))

    for component, artifact, digest, _ in PIXEL_COMPONENTS:
        cache = ROOT / ("build/pixel-components/" + component + ".zip")
        with checked_archive(cache, f"repos/AutonomousLife/PixelDeck/actions/artifacts/{artifact}", digest) as z:
            if component == "runtime":
                content, relative = z.read("libblsession.so"), "libblsession.so"
            else:
                from compression import zstd  # Python 3.14, no extra dependency.
                with tarfile.open(fileobj=io.BytesIO(zstd.decompress(z.read("gamescope.tzst")))) as tar:
                    content = tar.extractfile("usr/local/bin/gamescope").read()
                relative = "usr/local/bin/gamescope"
            destination = ROOT / "app/src/main/assets/linuxfs" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or destination.read_bytes() != content:
                destination.write_bytes(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="Install the built debug APK on this explicitly selected device")
    args = parser.parse_args()
    stage()
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or
               str(Path.home() / "AppData/Local/Android/Sdk"))
    env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    gradle = str(ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew"))
    subprocess.run([gradle, ":app:assembleDebug", "--console=plain"], cwd=ROOT, env=env, check=True)
    apk = ROOT / "app/build/outputs/apk/debug/app-debug.apk"
    print("APK:", apk, flush=True)
    if args.serial:
        adb = shutil.which("adb")
        if not adb:
            raise RuntimeError("adb not found")
        remote = "/data/local/tmp/pixeldeck-debug.apk"
        prefix = [adb, "-s", args.serial]
        subprocess.run(prefix + ["push", str(apk), remote], check=True, timeout=120)
        try:
            subprocess.run(prefix + ["shell", "pm", "install", "-r", remote], check=True, timeout=180)
        finally:
            subprocess.run(prefix + ["shell", "rm", "-f", remote], check=True, timeout=30)


if __name__ == "__main__":
    main()
