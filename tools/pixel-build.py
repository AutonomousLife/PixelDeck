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

# Not resolve(): that maps a subst drive back to its target, and Java's toRealPath fails on any
# path whose parent folders the build account cannot list (AgentBox under C:\Users\Silver).
ROOT = Path(__file__).absolute().parent.parent
ARTIFACT = "repos/Droid-Deck/DroidDeck/actions/artifacts/11390530317"
DIGEST = "2400d77fcd27220325ddb69947592270361cb2813be8a49ec95844b176bceb9d"
CACHE = ROOT / "build/pixel-probe/upstream-ci.zip"

# Keep these cached: Actions artifacts expire. Source builds live in the matching workflows.
PIXEL_COMPONENTS = [
    # Runtime 1a03bcf, Gamescope f2fa3a0, audio bcc3cd1; digests detect stale native sources.
    ("runtime", 11517904388, "2392ecba5af2811d68fc602ea2173fc183826678d8a399f3c02cd7d7538f5413",
     "38fd919ad87d64c10b3bbaf0431ec80a6901ce95d2c7a9f730204768a2282bc2"),
    ("gamescope", 11518696743, "b71278529812fcb445be3abd9940ba038e384c24a0c09eaccc7e8792a08f5ec5",
     "448b234a7d7424401fdb8e9a9f30dc83cbcd41d92d7f2b70e9783384fab3f0e2"),
    ("audio", 11421664765, "11e6fd13e7dbb538f19149b1d8081576087ff0c418382df2605030cc86478bcf",
     "4925c6fc41bbf10f3b4c6bd6467cac57f79b237671c003e09fcb1ad50b820374"),
]


def source_digest(component):
    directories = {"runtime": ["tools/linuxfs/preload"], "gamescope": ["tools/gamescope"],
                   "audio": ["tools/pixel-audio", "tools/aaudio-sink"]}[component]
    digest = hashlib.sha256()
    for path in sorted(p for directory in directories for p in (ROOT / directory).rglob("*")):
        if not path.is_file():
            continue
        if component == "runtime":
            selected = path.suffix in (".c", ".h", ".map") and "tests" not in path.parts
        elif component == "audio":
            selected = path.suffix in (".c", ".h", ".sh", ".py")
        else:
            selected = path.suffix == ".patch" or path.name in ("build-in-arch.sh", "runtime-sonames.txt")
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
    # A new pinned APK must replace what an older one staged, or changed scripts never reach the build.
    stamp = ROOT / "build/pixel-probe/staged-digest"
    refresh = not stamp.exists() or stamp.read_text().strip() != DIGEST
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
                # Gradle restages checkout scripts at preBuild, so a refresh here cannot leave a stale copy.
                if refresh or not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(apk.read(name))

    for component, artifact, digest, _ in PIXEL_COMPONENTS:
        cache = ROOT / f"build/pixel-components/{component}-{artifact}.zip"
        with checked_archive(cache, f"repos/AutonomousLife/PixelDeck/actions/artifacts/{artifact}", digest) as z:
            if component == "runtime":
                content, relative = z.read("libblsession.so"), "libblsession.so"
            elif component == "gamescope":
                from compression import zstd  # Python 3.14, no extra dependency.
                with tarfile.open(fileobj=io.BytesIO(zstd.decompress(z.read("gamescope.tzst")))) as tar:
                    content = tar.extractfile("usr/local/bin/gamescope").read()
                relative = "usr/local/bin/gamescope"
            else:
                for name in z.namelist():
                    if name.startswith("lib/") and name.endswith(".so"):
                        destination = ROOT / "app/src/main/jniLibs/arm64-v8a" / Path(name).name
                        destination.write_bytes(z.read(name))
                (ROOT / "app/src/main/assets/pulseaudio.tzst").write_bytes(z.read("pulseaudio-complete.tzst"))
                continue
            destination = ROOT / "app/src/main/assets/linuxfs" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or destination.read_bytes() != content:
                destination.write_bytes(content)
    # Written last, so an interrupted run refreshes again next time.
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(DIGEST + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="Install the built debug APK on this explicitly selected device")
    args = parser.parse_args()
    sdk = Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or
               str(Path.home() / "AppData/Local/Android/Sdk"))
    env = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk))
    # Record source state before temporarily injecting the verified sink bundle.
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, check=True)
    env.setdefault("DROIDDECK_BUILD_TREE_STATE", "dirty" if status.stdout else "clean")
    gradle = str(ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew"))
    # The normal Linux build injects sinks into this base asset too; preserve its input contract.
    audio_asset = ROOT / "app/src/main/assets/pulseaudio.tzst"
    base_audio = audio_asset.read_bytes()
    try:
        stage()
        subprocess.run([gradle, ":app:assembleDebug", "--console=plain"], cwd=ROOT, env=env, check=True)
    finally:
        audio_asset.write_bytes(base_audio)
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
