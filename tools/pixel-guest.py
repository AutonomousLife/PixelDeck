#!/usr/bin/env python3
"""Run a command directly inside PixelDeck's debug runtime, bypassing gamescope."""
import argparse
from pathlib import PurePosixPath
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--package", default="dev.pixeldeck.launcher")
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
if not args.command:
    parser.error("a guest command is required")
prefix = ["adb", "-s", args.serial]
apk = subprocess.check_output(prefix + ["shell", "pm", "path", args.package], text=True).strip()
if not apk.startswith("package:") or "\n" in apk:
    raise RuntimeError("Expected one installed debug APK")
native = str(PurePosixPath(apk.removeprefix("package:")).parent / "lib/arm64")
data = "/data/user/0/" + args.package
root = data + "/files/linuxfs"
command = [native + "/libproot.so", "--kill-on-exit", "-0", "-r", root, "-w", "/root",
           "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", data,
           "-b", data + "/cache/shm:/dev/shm", "/usr/bin/env", "-i", "HOME=/root", "USER=root",
           "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "GLIBC_TUNABLES=glibc.pthread.rseq=0",
           *args.command]
assignments = {"PROOT_LOADER": native + "/libproot-loader.so", "PROOT_TMP_DIR": data + "/cache"}
script = " ".join(k + "=" + shlex.quote(v) for k, v in assignments.items()) + " exec " + shlex.join(command)
remote = shlex.join(["run-as", args.package, "sh", "-c", script])
raise SystemExit(subprocess.call(prefix + ["shell", remote]))
