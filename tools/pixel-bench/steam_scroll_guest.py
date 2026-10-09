"""Runs inside the PixelDeck guest: scroll Steam Big Picture's largest scrollable element for a fixed time.

Prints one JSON object. Exit status 1 means the run is invalid (no Steam page, nothing to scroll,
the scroll did not move). The host measures presentation; this only drives the page and reports
Chromium's own requestAnimationFrame cadence plus a CLOCK_MONOTONIC window for the host to trim to.
"""
import json
import re
import runpy
import sys
import time
from pathlib import Path

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0

SCROLL_JS = """new Promise(resolve => {
  const candidates = [document.scrollingElement, ...document.querySelectorAll('*')]
    .filter(e => e && e.clientHeight > 200 && e.scrollHeight > e.clientHeight + 200);
  const el = candidates.sort((a, b) => b.clientWidth * b.clientHeight - a.clientWidth * a.clientHeight)[0];
  if (!el) { resolve({error: 'no scrollable content on the Big Picture page'}); return; }
  const range = Math.min(1000, el.scrollHeight - el.clientHeight);
  // Constant speed, instant reversal (triangle wave). A sine wave slows below one pixel per frame
  // near each turnaround, so the page legitimately stops changing for ~150-270 ms and no frame is
  // presented; that showed up as false "stalls". At SPEED px/s every frame moves several pixels.
  const SPEED = 240, period = 2 * range / SPEED * 1000;
  const old = el.scrollTop, start = performance.now();
  let last = start, gaps = [], slow = [], lo = Infinity, hi = -Infinity;
  function frame(t) {
    if (gaps.length && t - last > 34 && slow.length < 40) slow.push([Math.round(last - start), Math.round(t - last)]);
    gaps.push(t - last); last = t;
    const phase = ((t - start) % period) / period;
    el.scrollTop = (phase < 0.5 ? phase * 2 : 2 - phase * 2) * range;
    lo = Math.min(lo, el.scrollTop); hi = Math.max(hi, el.scrollTop);
    if (t - start < DURATION_MS) { requestAnimationFrame(frame); return; }
    el.scrollTop = old;
    gaps.shift();  // the first value is the wait for the first frame, not a frame interval
    gaps.sort((a, b) => a - b);
    const pick = q => gaps.length ? gaps[Math.min(gaps.length - 1, Math.floor(gaps.length * q))] : null;
    resolve({
      target: {tag: el.tagName, className: String(el.className).slice(0, 80),
               scrollHeight: el.scrollHeight, clientHeight: el.clientHeight},
      scrolledPx: hi - lo, speedPxPerSecond: SPEED, durationMs: last - start, rafFrames: gaps.length,
      rafP50Ms: pick(0.5), rafP95Ms: pick(0.95), rafP99Ms: pick(0.99),
      rafMaxMs: gaps.length ? gaps[gaps.length - 1] : null,
      rafSlow: slow,  // [ms since start, interval ms] for intervals over 34 ms
    });
  }
  requestAnimationFrame(frame);
})"""


def main():
    api = runpy.run_path("/usr/local/bin/droiddeck-steam-compat")
    log = Path("/root/.local/share/Steam/logs/webhelper.txt").read_text(errors="replace")
    ports = re.findall(r"--remote-debugging-port=(\d+)", log)
    if not ports:
        return {"error": "Steam web helper has no remote debugging port"}
    port = int(ports[-1])
    target = next((t for t in api["http_get"](port, "/json/list") if t.get("title") == "Steam Big Picture Mode"), None)
    if target is None:
        return {"error": "Steam Big Picture Mode page is not open"}
    page = api["Page"](port, "/" + target["webSocketDebuggerUrl"].split("/", 3)[3])
    try:
        js = SCROLL_JS.replace("DURATION_MS", str(int(SECONDS * 1000)))
        result = page.evaluate(js, timeout=SECONDS + 15)
        result["endMonotonicNs"] = time.monotonic_ns()
    finally:
        page.ws.close()
    if "error" not in result and result.get("scrolledPx", 0) < 200:
        result["error"] = f"scroll barely moved ({result.get('scrolledPx')} px)"
    return result


if __name__ == "__main__":
    try:
        out = main()
    except Exception as exc:  # report, never pretend success
        out = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out), flush=True)
    sys.exit(1 if "error" in out else 0)
