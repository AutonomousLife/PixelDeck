"""Runs inside the PixelDeck guest: report Steam's Chromium GPU configuration over DevTools (read-only)."""
import json
import re
import runpy
from pathlib import Path

api = runpy.run_path("/usr/local/bin/droiddeck-steam-compat")
log = Path("/root/.local/share/Steam/logs/webhelper.txt").read_text(errors="replace")
port = int(re.findall(r"--remote-debugging-port=(\d+)", log)[-1])
version = api["http_get"](port, "/json/version")
browser = api["Page"](port, "/" + version["webSocketDebuggerUrl"].split("/", 3)[3])
out = {"browser": version.get("Browser")}
try:
    info = browser.call("SystemInfo.getInfo", timeout=20)
    gpu = info.get("gpu", {})
    out["featureStatus"] = gpu.get("featureStatus")
    out["driverBugWorkarounds"] = gpu.get("driverBugWorkarounds")
    out["devices"] = gpu.get("devices")
    aux = gpu.get("auxAttributes", {})
    out["aux"] = {k: aux.get(k) for k in ("glRenderer", "glVersion", "glImplementationParts", "displayType",
                                          "gpuCompositing", "skiaBackendType", "inProcessGpu",
                                          "passthroughCmdDecoder", "vulkanVersion", "visibilityCallbackCallCount")}
    out["commandLine"] = info.get("commandLine")
    try:
        out["browserCommandLine"] = browser.call("Browser.getBrowserCommandLine", timeout=10).get("arguments")
    except Exception as exc:
        out["browserCommandLineError"] = str(exc)
finally:
    browser.ws.close()
print(json.dumps(out, indent=1))
