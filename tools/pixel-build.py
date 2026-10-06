#!/usr/bin/env python3
"""Incrementally build PixelDeck on Windows; stage unchanged Linux prebuilts once."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT = "repos/Droid-Deck/DroidDeck/actions/artifacts/11390530317"
DIGEST = "2400d77fcd27220325ddb69947592270361cb2813be8a49ec95844b176bceb9d"
CACHE = ROOT / "build/pixel-probe/upstream-ci.zip"


def stage():
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        fetched = subprocess.run(["gh", "api", ARTIFACT + "/zip"], capture_output=True, check=True, timeout=120)
        CACHE.write_bytes(fetched.stdout)
    with CACHE.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != DIGEST:
            raise RuntimeError("Upstream artifact checksum mismatch")
    with zipfile.ZipFile(CACHE) as z:
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
