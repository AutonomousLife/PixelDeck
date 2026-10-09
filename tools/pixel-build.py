#!/usr/bin/env python3
"""Incrementally build PixelDeck on Windows; stage unchanged Linux prebuilts once."""
import argparse
import hashlib
import io
import json
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

# The verified upstream APK's META-INF/version-control-info.textproto names this revision.
# Digests come from its Git blobs, not this checkout. These are the native/cache inputs
# used by build.yml that we still take from that APK. Checkout scripts are restaged by
# Gradle; arm64 libblsession and Gamescope are replaced by PIXEL_COMPONENTS below.
UPSTREAM_SOURCE_COMMIT = "b44235c495fa6458aa438c9ba3be06562e5d1a3c"
UPSTREAM_NATIVE_INPUTS = [
    ("x86 preloads (and arm64 fakeinput)", ["app/src/main/cpp/fakeinput_steam.cpp",
      "tools/linuxfs/preload/*.c", "tools/linuxfs/preload/*.h", "tools/linuxfs/preload/*.map",
      "tools/linuxfs/build-x86-preloads.sh", "tools/linuxfs/fex/*"],
     "d8b9a7e000f1cd86da200f7205c20662a79b7f8cf2d71601949a4b80c9174d0f"),
    ("clipboard/fastpath", ["tools/linuxfs/clipboard/*.c", "tools/proot/fastpath/*.c"],
     "7daff3625719d2d09961fbd9b2a2e653b92e67a402de420622cb19f94c8b8ede"),
    ("graphics runtime dependencies", ["tools/gamescope/release.env", "tools/wlroots/release.env"],
     "60283908856cc1859efefaa9962aa548f4b1803d889ff7037b04259013654f12"),
    ("uruntime", ["tools/linuxfs/uruntime.env", "tools/linuxfs/licenses/*"],
     "831be2133a78e59bdc7c6139f46b6f3ac200c020d196f26568c78851eb8191bf"),
    ("mangoapp", ["tools/mangoapp/*"],
     "573712a80f89b42edeafcedd2b3faf60d6eb4ba987f1cbfb8738ddfe1bd71775"),
]
# (artifact ID, archive SHA-256, native input digest). Pin only after the extended
# pixel-runtime workflow has produced and verified these binaries; None fails closed.
NATIVE_COMPONENT = (11593949311,
    "150ac357e3a86afeb2455209304233a2d723891d20584cdc08df2104f6ea77a3",
    "4df061aa716d7057af79dcdea0201454eeb6f1f05220a320a5d179c4922082f2")
NATIVE_INPUT_PATTERNS = tuple(UPSTREAM_NATIVE_INPUTS[0][1])
NATIVE_INPUT_GROUP = UPSTREAM_NATIVE_INPUTS[0][0]

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


def input_digest(patterns):
    digest = hashlib.sha256()
    paths = {path for pattern in patterns for path in ROOT.glob(pattern) if path.is_file()}
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" +
                      path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def source_digest(component):
    if component == "native":
        return input_digest(NATIVE_INPUT_PATTERNS)
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
    if NATIVE_COMPONENT is not None:
        _, _, expected = NATIVE_COMPONENT
        if source_digest("native") != expected:
            raise RuntimeError("native sources changed: rebuild pixel-runtime.yml and repin NATIVE_COMPONENT")
    for component, patterns, expected in UPSTREAM_NATIVE_INPUTS:
        if component == NATIVE_INPUT_GROUP and NATIVE_COMPONENT is not None:
            continue  # Every binary from this group is replaced by the verified native artifact.
        if input_digest(patterns) != expected:
            raise RuntimeError(
                f"{component} inputs differ from upstream APK source {UPSTREAM_SOURCE_COMMIT}: "
                "rebuild the affected Linux prebuilts in CI and pin their verified artifacts "
                "before building locally; updating a digest alone does not rebuild binaries")
    for component, _, _, expected in PIXEL_COMPONENTS:
        if source_digest(component) != expected:
            raise RuntimeError(f"{component} sources changed: rebuild its Linux CI artifact and update PIXEL_COMPONENTS")
    # A new pinned APK must replace what an older one staged, or changed scripts never reach the build.
    stamp = ROOT / "build/pixel-probe/staged-digest"
    refresh = not stamp.exists() or stamp.read_text().strip() != DIGEST
    with checked_archive(CACHE, ARTIFACT, DIGEST) as z:
        apk_name = next(n for n in z.namelist() if n.endswith(".apk"))
        with zipfile.ZipFile(io.BytesIO(z.read(apk_name))) as apk:
            try:
                provenance = apk.read("META-INF/version-control-info.textproto").decode("utf-8")
            except (KeyError, UnicodeDecodeError) as error:
                raise RuntimeError("Pinned upstream APK has no readable source revision") from error
            if f'revision: "{UPSTREAM_SOURCE_COMMIT}"' not in provenance:
                raise RuntimeError("Pinned upstream APK source revision changed: verify and repin "
                                   "UPSTREAM_SOURCE_COMMIT and UPSTREAM_NATIVE_INPUTS")
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
    if NATIVE_COMPONENT is not None:
        artifact, digest, expected = NATIVE_COMPONENT
        cache = ROOT / f"build/pixel-components/native-{artifact}.zip"
        with checked_archive(cache, f"repos/AutonomousLife/PixelDeck/actions/artifacts/{artifact}", digest) as z:
            if json.loads(z.read("source.json"))["sourceDigest"] != expected:
                raise RuntimeError("Native artifact source digest disagrees with NATIVE_COMPONENT")
            # Only these outputs are authoritative; never extract arbitrary archive paths.
            for relative in ("libfakeinput.so", "x86_64/libblsession.so", "x86_64/libfakeinput.so",
                             "x86_64/libfaultreport.so", "x86_64/libthunkaudit.so",
                             "x86_64/libvulkan-thunk.so", "i386/libblsession.so", "i386/libfakeinput.so"):
                destination = ROOT / "app/src/main/assets/linuxfs" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                content = z.read(relative)
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
