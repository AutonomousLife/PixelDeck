#!/usr/bin/env python3
"""Build/run app-UID GPU probes directly from source with the Android SDK/NDK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import zipfile

SOURCE = Path(__file__).resolve().parent
ROOT = SOURCE.parent.parent
BUILD = ROOT / "build" / "pixel-probe"
PACKAGE = "dev.pixeldeck.probe"


def run(*args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, timeout=180)


def build(sdk, compositor=False):
    tools = sdk / "build-tools" / "35.0.0"
    android = sdk / "platforms" / "android-34" / "android.jar"
    java = shutil.which("java")
    javac = shutil.which("javac")
    if not java or not javac or not android.is_file() or not tools.is_dir():
        raise RuntimeError("Need JDK and Android SDK platform 34 / build-tools 35.0.0")
    BUILD.mkdir(parents=True, exist_ok=True)
    exe = ".exe" if os.name == "nt" else ""
    host = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
    clang = sdk / "ndk/27.3.13750724/toolchains/llvm/prebuilt" / host / "bin" / ("clang" + exe)
    if not clang.is_file():
        raise RuntimeError("Need Android NDK 27.3.13750724 (Windows: run bootstrap_sdk.py)")
    common = [clang, "--target=aarch64-linux-android26", "-shared", "-fPIC", "-O2", "-Wall",
              "-Wextra", "-Wno-unused-parameter", "-Wl,-z,max-page-size=16384"]
    run(*common, ROOT / "app/src/main/cpp/deviceinfo/vkinfo.c", "-o", BUILD / "libdeviceinfo.so", "-ldl")
    run(*common, SOURCE / "native_probe.c", "-o", BUILD / "libpixelprobe.so", "-lvulkan", "-landroid")
    classes = BUILD / "classes"
    classes.mkdir(exist_ok=True)
    run(javac, "--release", "8", "-classpath", android, "-d", classes,
        *sorted(SOURCE.glob("*.java")))
    run(java, "-cp", tools / "lib" / "d8.jar", "com.android.tools.r8.D8",
        "--lib", android, "--min-api", "26", "--output", BUILD, *sorted(classes.rglob("*.class")))
    unsigned = BUILD / "unsigned.apk"
    run(tools / ("aapt2" + exe), "link", "-o", unsigned, "--manifest",
        SOURCE / "AndroidManifest.xml", "-I", android)
    with zipfile.ZipFile(unsigned, "a") as apk:
        for library in ("libdeviceinfo.so", "libpixelprobe.so"):
            apk.write(BUILD / library, "lib/arm64-v8a/" + library)
        if compositor:
            full = ROOT / "app/build/outputs/apk/debug/app-debug.apk"
            if not full.is_file():
                raise RuntimeError("Build the full app first: python tools/pixel-build.py")
            with zipfile.ZipFile(full) as compiled:
                for n in ("libdroiddeckwayland.so", "libwayland-server.so", "libc++_shared.so", "libffi.so"):
                    path = "lib/arm64-v8a/" + n
                    apk.writestr(path, compiled.read(path))
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
        "ndk": "27.3.13750724", "native_source": "tools/pixel-probe/native_probe.c",
        "libraries": {n: hashlib.sha256((BUILD / n).read_bytes()).hexdigest()
                      for n in ("libdeviceinfo.so", "libpixelprobe.so")},
    }, indent=2), encoding="utf-8")
    return output


def device_test(apk, serial, native=False, no_install=False, compositor=False):
    adb = shutil.which("adb")
    if not adb:
        raise RuntimeError("adb not found")
    prefix = [adb, "-s", serial]
    state = subprocess.run(prefix + ["get-state"], capture_output=True, text=True, timeout=15)
    if state.returncode or state.stdout.strip() != "device":
        raise RuntimeError("Device unavailable/unauthorized: " + state.stderr.strip())
    remote_apk = "/data/local/tmp/pixeldeck-probe.apk"
    if not no_install:
        run(*prefix, "push", apk, remote_apk)
        try:
            run(*prefix, "shell", "pm", "install", "-r", remote_apk)
        finally:
            run(*prefix, "shell", "rm", "-f", remote_apk)
    report_file = "report-native.json" if native else "report.json"
    artifact_prefix = "compositor" if compositor else "native" if native else "device"
    activity = ".NativeProbeActivity" if native else ".ProbeActivity"
    run(*prefix, "shell", "am", "force-stop", PACKAGE)
    # Remove only the probe's previous report so stale success cannot pass a new run.
    run(*prefix, "shell", "run-as", PACKAGE, "rm", "-f", "files/" + report_file, "files/frame-ready.txt")
    run(*prefix, "shell", "am", "start", "-W", "-n", PACKAGE + "/" + activity,
        "--ez", "compositor", "true" if compositor else "false")
    try:
        captured = False
        for _ in range(150):
            if native and not captured:
                ready = subprocess.run(prefix + ["shell", "run-as", PACKAGE, "cat", "files/frame-ready.txt"],
                                       capture_output=True, text=True, timeout=10)
                if "vulkan_present=pass" in ready.stdout or "compositor_present=pass" in ready.stdout:
                    screenshot = subprocess.run(prefix + ["exec-out", "screencap", "-p"],
                                                capture_output=True, check=True, timeout=15)
                    (BUILD / (artifact_prefix + "-screen.png")).write_bytes(screenshot.stdout)
                    captured = True
            result = subprocess.run(prefix + ["shell", "run-as", PACKAGE, "cat", "files/" + report_file],
                                    capture_output=True, text=True, timeout=10)
            try:
                report = json.loads(result.stdout)
            except json.JSONDecodeError:
                report = {}
            if report.get("status") in ("complete", "failed"):
                (BUILD / (artifact_prefix + "-report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
                if not captured:
                    screenshot = subprocess.run(prefix + ["exec-out", "screencap", "-p"],
                                                capture_output=True, check=True, timeout=15)
                    (BUILD / (artifact_prefix + "-screen.png")).write_bytes(screenshot.stdout)
                print(json.dumps(report, indent=2))
                if report["status"] != "complete" or "error" in report or "error" in report.get("vulkan", {}):
                    raise RuntimeError("Probe reported a GPU failure; see " + artifact_prefix + "-report.json")
                return
            time.sleep(0.2)
        raise RuntimeError("Probe timed out; unlock the device and inspect PixelDeckProbe logcat")
    finally:
        logs = subprocess.run(prefix + ["logcat", "-d", "-s", "PixelDeckProbe:I", "AndroidRuntime:E", "*:S"],
                              capture_output=True, text=True, timeout=15)
        (BUILD / (artifact_prefix + "-logcat.txt")).write_text(logs.stdout, encoding="utf-8")
        subprocess.run(prefix + ["shell", "am", "force-stop", PACKAGE], check=False, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=Path(os.environ.get("ANDROID_HOME") or
        os.environ.get("ANDROID_SDK_ROOT") or str(Path.home() / "AppData/Local/Android/Sdk")))
    parser.add_argument("--serial", help="Install/run on this explicitly selected ADB device")
    parser.add_argument("--no-build", action="store_true", help="Run the existing built APK")
    parser.add_argument("--native", action="store_true", help="Test Vulkan AHB import/presentation and DMA-heap allocation")
    parser.add_argument("--compositor", action="store_true", help="Test the locally built full-app compositor on stock Vulkan")
    parser.add_argument("--no-install", action="store_true", help="Run the already-installed probe")
    args = parser.parse_args()
    apk = BUILD / "pixeldeck-probe.apk" if args.no_build else build(args.sdk, args.compositor)
    if args.serial:
        device_test(apk, args.serial, args.native or args.compositor, args.no_install, args.compositor)
    print("Artifacts:", BUILD)


if __name__ == "__main__":
    main()
