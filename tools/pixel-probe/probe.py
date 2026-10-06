#!/usr/bin/env python3
"""Build/run an app-UID GPU probe using the installed SDK and upstream JNI binary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import io
import zipfile

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parent.parent
BUILD = ROOT / "build" / "pixel-probe"
PACKAGE = "dev.pixeldeck.probe"
ARTIFACT = "repos/Droid-Deck/DroidDeck/actions/artifacts/11390530317"
ARTIFACT_SHA256 = "2400d77fcd27220325ddb69947592270361cb2813be8a49ec95844b176bceb9d"


def run(*args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, timeout=180)


def build(sdk):
    tools = sdk / "build-tools" / "35.0.0"
    android = sdk / "platforms" / "android-34" / "android.jar"
    java = shutil.which("java")
    javac = shutil.which("javac")
    if not java or not javac or not android.is_file() or not tools.is_dir():
        raise RuntimeError("Need JDK and Android SDK platform 34 / build-tools 35.0.0")
    BUILD.mkdir(parents=True, exist_ok=True)
    official = BUILD / "upstream-ci.zip"
    if not official.exists():
        archive = subprocess.run(["gh", "api", ARTIFACT + "/zip"], capture_output=True, check=True, timeout=120)
        official.write_bytes(archive.stdout)
    actual = hashlib.sha256(official.read_bytes()).hexdigest()
    if actual != ARTIFACT_SHA256:
        raise RuntimeError("Upstream CI artifact checksum mismatch; remove cached ZIP and retry")
    classes = BUILD / "classes"
    classes.mkdir(exist_ok=True)
    run(javac, "--release", "8", "-classpath", android, "-d", classes,
        SOURCE / "VulkanInfo.java", SOURCE / "ProbeActivity.java")
    run(java, "-cp", tools / "lib" / "d8.jar", "com.android.tools.r8.D8",
        "--lib", android, "--min-api", "26", "--output", BUILD, *sorted(classes.rglob("*.class")))
    unsigned = BUILD / "unsigned.apk"
    exe = ".exe" if os.name == "nt" else ""
    run(tools / ("aapt2" + exe), "link", "-o", unsigned, "--manifest",
        SOURCE / "AndroidManifest.xml", "-I", android)
    with zipfile.ZipFile(official) as archive:
        apk_name = next(n for n in archive.namelist() if n.endswith(".apk"))
        with zipfile.ZipFile(io.BytesIO(archive.read(apk_name))) as upstream:
            native = upstream.read("lib/arm64-v8a/libdeviceinfo.so")
    with zipfile.ZipFile(unsigned, "a") as apk:
        apk.writestr("lib/arm64-v8a/libdeviceinfo.so", native)
        apk.write(BUILD / "classes.dex", "classes.dex")
    aligned = BUILD / "aligned.apk"
    output = BUILD / "pixeldeck-probe.apk"
    run(tools / ("zipalign" + exe), "-f", "-p", "4", unsigned, aligned)
    key = BUILD / "debug.jks"
    if not key.exists():
        run(Path(java).with_name("keytool" + exe), "-genkeypair", "-alias", "androiddebugkey",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "3650", "-keystore", key,
            "-storetype", "JKS", "-storepass", "android", "-keypass", "android",
            "-dname", "CN=PixelDeck local debug,O=PixelDeck,C=US")
    run(java, "-jar", tools / "lib" / "apksigner.jar", "sign", "--ks",
        key, "--ks-key-alias", "androiddebugkey", "--ks-pass",
        "pass:android", "--out", output, aligned)
    run(java, "-jar", tools / "lib" / "apksigner.jar", "verify", output)
    (BUILD / "provenance.json").write_text(json.dumps({
        "artifact": "https://api.github.com/" + ARTIFACT, "artifact_sha256": actual,
        "libdeviceinfo_sha256": hashlib.sha256(native).hexdigest(),
    }, indent=2), encoding="utf-8")
    return output


def device_test(apk, serial):
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("adb not found")
    prefix = [adb, "-s", serial]
    state = subprocess.run(prefix + ["get-state"], capture_output=True, text=True, timeout=15)
    if state.returncode or state.stdout.strip() != "device":
        raise RuntimeError("Device unavailable/unauthorized: " + state.stderr.strip())
    remote_apk = "/data/local/tmp/pixeldeck-probe.apk"
    run(*prefix, "push", apk, remote_apk)
    try:
        run(*prefix, "shell", "pm", "install", "-r", remote_apk)
    finally:
        run(*prefix, "shell", "rm", "-f", remote_apk)
    run(*prefix, "shell", "am", "force-stop", PACKAGE)
    # Remove only the probe's previous report so stale success cannot pass a new run.
    run(*prefix, "shell", "run-as", PACKAGE, "rm", "-f", "files/report.json")
    run(*prefix, "shell", "am", "start", "-W", "-n", PACKAGE + "/.ProbeActivity")
    try:
        for _ in range(30):
            result = subprocess.run(prefix + ["shell", "run-as", PACKAGE, "cat", "files/report.json"],
                                    capture_output=True, text=True, timeout=10)
            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError:
                report = {}
            if report.get("status") in ("complete", "failed"):
                (BUILD / "device-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                screenshot = subprocess.run(prefix + ["exec-out", "screencap", "-p"],
                                            capture_output=True, check=True, timeout=15)
                (BUILD / "device-screen.png").write_bytes(screenshot.stdout)
                print(json.dumps(report, indent=2))
                if report["status"] != "complete" or "error" in report.get("vulkan", {}):
                    raise RuntimeError("Probe reported a GPU failure; see device-report.json")
                return
            time.sleep(1)
        raise RuntimeError("Probe timed out; unlock the device and inspect PixelDeckProbe logcat")
    finally:
        logs = subprocess.run(prefix + ["logcat", "-d", "-s", "PixelDeckProbe:I", "AndroidRuntime:E", "*:S"],
                              capture_output=True, text=True, timeout=15)
        (BUILD / "device-logcat.txt").write_text(logs.stdout, encoding="utf-8")
        subprocess.run(prefix + ["shell", "am", "force-stop", PACKAGE], check=False, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_HOME") or
        os.environ.get("ANDROID_SDK_ROOT") or str(Path.home() / "AppData/Local/Android/Sdk")))
    parser.add_argument("--serial", help="Install/run on this explicitly selected ADB device")
    parser.add_argument("--no-build", action="store_true", help="Run the existing built APK")
    args = parser.parse_args()
    apk = BUILD / "pixeldeck-probe.apk" if args.no_build else build(args.sdk)
    if args.serial:
        device_test(apk, args.serial)
    print("Artifacts:", BUILD)


if __name__ == "__main__":
    main()
