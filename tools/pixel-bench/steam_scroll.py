#!/usr/bin/env python3
"""Measure displayed Steam Big Picture frames on the phone while the guest scrolls a page.

Displayed frames come from SurfaceFlinger's per-layer present timestamps for the session's
SurfaceView, polled often enough that its ~128-frame history cannot overflow unnoticed. Only
frames presented while the scroll is running count. A run is rejected (exit 1, "valid": false)
when the guest reports an error, Steam loses focus or the screen sleeps, frames may have been
lost between polls, or too few frames were seen. Chromium's own requestAnimationFrame cadence
is recorded beside the displayed rate so producer and display can be compared.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

PACKAGE = "dev.pixeldeck.launcher"
PENDING = 9223372036854775807  # SurfaceFlinger's "fence not signalled yet"
HERE = Path(__file__).absolute().parent
GUEST_SCRIPT = HERE / "steam_scroll_guest.py"
EDGE_TRIM_NS = 250_000_000  # skip the first and last 250 ms of the scroll


def parse_latency(text):
    """SurfaceFlinger --latency: first line is the refresh period, then desired/actual/ready rows."""
    lines = text.split()
    period = int(lines[0]) if lines and lines[0].isdigit() else None
    rows = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 3 and all(p.isdigit() for p in parts):
            desired, actual, ready = map(int, parts)
            if 0 < actual < PENDING:
                rows.append((desired, actual, ready))
    return period, rows


class PresentLog:
    """Accumulates present timestamps across polls and detects possible history overflow."""

    def __init__(self):
        self.frames = {}  # actual present ns -> (desired, ready)
        self.possible_loss = False
        self.polls = 0

    def add(self, rows):
        self.polls += 1
        if not rows:
            return
        seen = set(self.frames)
        newest_seen = max(seen) if seen else None
        oldest_in_dump = min(r[1] for r in rows)
        # SurfaceFlinger keeps only the newest frames (about 60 on this device). With polls well
        # inside that history, every dump overlaps what was already seen; one that starts after
        # everything seen so far means frames between the two polls may have been dropped.
        if newest_seen is not None and oldest_in_dump > newest_seen:
            self.possible_loss = True
        for desired, actual, ready in rows:
            self.frames[actual] = (desired, ready)


def percentile(sorted_values, q):
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(len(sorted_values) * q))]


def frame_stats(presents, start_ns, end_ns, ready_by_present=None):
    """Displayed-frame statistics for presents inside [start_ns, end_ns]."""
    inside = sorted(p for p in presents if start_ns <= p <= end_ns)
    seconds = (end_ns - start_ns) / 1e9
    gaps = sorted((b - a) / 1e6 for a, b in zip(inside, inside[1:]))
    stats = {
        "windowSeconds": round(seconds, 3),
        "presentedFrames": len(inside),
        "fps": round(len(inside) / seconds, 2) if seconds > 0 else None,
        "gapP50Ms": percentile(gaps, 0.5),
        "gapP95Ms": percentile(gaps, 0.95),
        "gapP99Ms": percentile(gaps, 0.99),
        "gapMaxMs": gaps[-1] if gaps else None,
        "gapsOver20Ms": sum(g > 20 for g in gaps),
        "gapsOver34Ms": sum(g > 34 for g in gaps),
        "gapsOver50Ms": sum(g > 50 for g in gaps),
        "gapsOver100Ms": sum(g > 100 for g in gaps),
        # Edge gaps: time from the window start to the first present and from the last to the end.
        "edgeGapsMs": [round((inside[0] - start_ns) / 1e6, 2), round((end_ns - inside[-1]) / 1e6, 2)] if inside else None,
    }
    if ready_by_present:
        # Time from the buffer becoming ready (acquire fence) to SurfaceFlinger presenting it.
        lat = sorted((p - ready_by_present[p]) / 1e6 for p in inside if ready_by_present.get(p, 0) > 0)
        stats["readyToPresentP50Ms"] = percentile(lat, 0.5)
        stats["readyToPresentP95Ms"] = percentile(lat, 0.95)
    for key, value in list(stats.items()):
        if isinstance(value, float):
            stats[key] = round(value, 2)
    return stats


def gpu_summary(samples):
    """Mali clock samples taken while the guest ran (includes its ~1-2 s startup)."""
    if not samples:
        return None
    ordered = sorted(samples)
    return {"samples": len(ordered), "min": ordered[0], "p50": percentile(ordered, 0.5),
            "p90": percentile(ordered, 0.9), "max": ordered[-1]}


def validity(result, min_frames=60):
    """Reasons the run must be rejected; empty when valid."""
    reasons = []
    guest = result.get("guest") or {}
    if result.get("guestExit") != 0 or "error" in guest:
        reasons.append("guest scroll failed: " + str(guest.get("error", f"exit {result.get('guestExit')}")))
    if result.get("focusLost"):
        reasons.append("Steam lost Android focus or the screen left the awake state during the run")
    if result.get("possibleLoss"):
        reasons.append("SurfaceFlinger history may have overflowed between polls")
    stats = result.get("stats") or {}
    if (stats.get("presentedFrames") or 0) < min_frames:
        reasons.append(f"only {stats.get('presentedFrames')} frames presented in the window")
    if (stats.get("windowSeconds") or 0) < 5:
        reasons.append("measurement window shorter than 5 s")
    return reasons


class Device:
    def __init__(self, adb, serial):
        self.prefix = [adb, "-s", serial]

    def shell(self, command, timeout=30):
        return subprocess.run(self.prefix + ["shell", command], capture_output=True, text=True,
                              timeout=timeout, check=True).stdout

    def run_as(self, *argv, timeout=60):
        return self.shell(shlex.join(["run-as", PACKAGE, *argv]), timeout=timeout)

    def foreground_ok(self):
        focus = self.shell("dumpsys window | grep -m1 mCurrentFocus")
        awake = self.shell("dumpsys power | grep -m1 mWakefulness=")
        return PACKAGE in focus and "SessionActivity" in focus and "Awake" in awake

    def session_layer(self):
        layers = self.shell("dumpsys SurfaceFlinger --list")
        for line in layers.splitlines():
            m = re.match(r"RequestedLayerState\{(.*?) parentId=", line.strip())
            name = m.group(1) if m else line.strip()
            if PACKAGE in name and name.startswith(tuple("0123456789abcdef")) and "SurfaceView[" in name and "(BLAST)" in name:
                return name
        raise RuntimeError("the session SurfaceView layer is not on screen")

    def latency(self, layer):
        """SurfaceFlinger rows plus the Mali clock in kHz (None if unreadable), in one adb call."""
        text = self.shell(shlex.join(["dumpsys", "SurfaceFlinger", "--latency", layer])
                          + "; echo GPUFREQ $(cat /sys/class/misc/mali0/device/cur_freq 2>/dev/null)")
        body, _, tail = text.rpartition("GPUFREQ")
        freq = tail.split()[0] if tail.split() else ""
        period, rows = parse_latency(body)
        return period, rows, int(freq) if freq.isdigit() else None


class StreamingPoller:
    """One device-side loop dumps the layer's history every ~100 ms and streams it back.

    Spawning an adb process per poll took 0.3-0.8 s on this phone, long enough for SurfaceFlinger's
    ~60-frame history to roll over between polls. The loop also self-terminates after max_seconds.
    """

    def __init__(self, device, layer, max_seconds, interval=0.1):
        loops = int(max_seconds / interval) + 1
        script = (f"i=0; while [ $i -lt {loops} ]; do echo PDBEGIN; "
                  f"dumpsys SurfaceFlinger --latency {shlex.quote(layer)}; "
                  f"echo GPUFREQ $(cat /sys/class/misc/mali0/device/cur_freq 2>/dev/null); echo PDEND; "
                  f"sleep {interval}; i=$((i+1)); done")
        self.log = PresentLog()
        self.gpu_khz = []
        self.proc = subprocess.Popen(device.prefix + ["shell", script], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True)
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self):
        block = []
        for line in self.proc.stdout:
            if line.startswith("PDBEGIN"):
                block = []
            elif line.startswith("PDEND"):
                body, _, tail = "".join(block).rpartition("GPUFREQ")
                _, rows = parse_latency(body)
                self.log.add(rows)
                if tail.split() and tail.split()[0].isdigit():
                    self.gpu_khz.append(int(tail.split()[0]))
            else:
                block.append(line)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.thread.join(timeout=10)


def identity(device, root):
    """What exactly was measured: app build, session, driver bytes, overrides, thermal state."""
    info = {}
    try:
        state = json.loads(subprocess.run([sys.executable, str(root / "tools/droiddeckctl"), "--package", PACKAGE,
                                           "--serial", device.prefix[2], "state"], capture_output=True, text=True,
                                          timeout=60, env=dict(os.environ, ADB=device.prefix[0])).stdout)
        session = state.get("session") or {}
        info.update(appBuild=state.get("build"), runtime=(state.get("runtime") or {}).get("version"),
                    session=session.get("id"), phase=session.get("phase"), output=session.get("output"),
                    refreshHz=session.get("refreshHz"))
        log_dir = session.get("logDir")
        if log_dir:
            text = device.shell(f"grep -m1 -o 'BL_VK_DRIVER=[^ ]*' {shlex.quote(log_dir)}/session.log || true")
            icd = text.strip().removeprefix("BL_VK_DRIVER=").rstrip(")")
            if icd:
                lib = str(Path(icd).parent.as_posix()) + "/libvulkan_driver.so"
                rel = lib.split(f"/{PACKAGE}/", 1)[-1]
                info["driver"] = rel
                info["driverSha256"] = device.run_as("sha256sum", rel).split()[0]
    except Exception as exc:
        info["identityError"] = str(exc)
    # Every installed Linux driver by content, so a run names the exact bytes even when the
    # session log has not recorded its selection yet.
    hashes = device.run_as("sh", "-c", "sha256sum files/linux_vulkan_drivers/*/libvulkan_driver.so 2>/dev/null || true")
    info["installedDrivers"] = {line.split()[1].split("/")[2]: line.split()[0]
                                for line in hashes.splitlines() if len(line.split()) == 2}
    info["envOverrideFile"] = device.run_as("sh", "-c", "test -e files/pixeldeck-env && cat files/pixeldeck-env || echo absent").strip()
    thermal = device.shell("dumpsys thermalservice | grep -m1 'Thermal Status'").strip()
    info["thermal"] = thermal
    return info


def run(args):
    root = HERE.parent.parent
    device = Device(args.adb, args.serial)
    if not device.foreground_ok():
        raise SystemExit("Steam is not the focused, awake Android window; run rejected before scrolling")
    layer = device.session_layer()
    period, _, _ = device.latency(layer)

    dest = "files/linuxfs/root/pixeldeck-steam-scroll.py"
    temp = "/data/local/tmp/pixeldeck-steam-scroll.py"
    subprocess.run(device.prefix + ["push", str(GUEST_SCRIPT), temp], check=True, capture_output=True)
    device.run_as("cp", temp, dest)
    device.shell(f"rm -f {temp}")
    if device.run_as("sha256sum", dest).split()[0] != hashlib.sha256(GUEST_SCRIPT.read_bytes()).hexdigest():
        raise SystemExit("guest benchmark script did not arrive intact")

    focus_lost = threading.Event()
    done = threading.Event()

    def watch_focus():
        while not done.is_set():
            if not device.foreground_ok():
                focus_lost.set()
            done.wait(1.0)

    watcher = threading.Thread(target=watch_focus, daemon=True)
    poller = StreamingPoller(device, layer, max_seconds=args.seconds + 60)
    guest = subprocess.Popen([sys.executable, str(root / "tools/pixel-guest.py"), "--serial", args.serial,
                              "/usr/bin/python3", "/root/pixeldeck-steam-scroll.py", str(args.seconds)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    watcher.start()
    ready_by_present = {}
    try:
        out, err = guest.communicate(timeout=args.seconds + 40)
    except subprocess.TimeoutExpired:
        guest.kill()
        out, err = guest.communicate(timeout=15)
    time.sleep(0.5)  # let the poller catch the frames presented right before the scroll ended
    poller.stop()
    log, gpu_khz = poller.log, poller.gpu_khz
    done.set()
    watcher.join(timeout=5)
    if not device.foreground_ok():
        focus_lost.set()

    guest_result = {}
    for line in reversed(out.splitlines()):
        try:
            guest_result = json.loads(line)
            break
        except ValueError:
            continue
    for present, (_, ready) in log.frames.items():
        ready_by_present[present] = ready
    result = {"label": args.label, "layer": layer, "refreshPeriodNs": period, "guestExit": guest.returncode,
              "guest": guest_result, "focusLost": focus_lost.is_set(), "possibleLoss": log.possible_loss,
              "latencyPolls": log.polls, "gpuFreqKhz": gpu_summary(gpu_khz)}
    if "error" not in guest_result and guest_result.get("endMonotonicNs"):
        end = guest_result["endMonotonicNs"] - EDGE_TRIM_NS
        start = guest_result["endMonotonicNs"] - int(guest_result["durationMs"] * 1e6) + EDGE_TRIM_NS
        result["stats"] = frame_stats(log.frames, start, end, ready_by_present)
        # Raw rows inside the window (desired, actual present, ready), kept as evidence.
        result["frames"] = [[log.frames[p][0], p, log.frames[p][1]] for p in sorted(log.frames) if start <= p <= end]
    if err.strip():
        result["guestStderr"] = err.strip()[-2000:]
    result["identity"] = identity(device, root)
    result["rejected"] = validity(result)
    result["valid"] = not result["rejected"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"), required=os.environ.get("ANDROID_SERIAL") is None)
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    parser.add_argument("--label", default="sample")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--out-dir", default="build/bench")
    args = parser.parse_args()
    result = run(args)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"steam-scroll-{args.label}.json"
    path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    print("wrote", path, file=sys.stderr)
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
