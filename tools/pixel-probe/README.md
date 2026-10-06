# PixelDeck: first device experiment

This separate diagnostic APK tests the stock graphics driver and device-node access
under a normal app UID. It does not change DroidDeck, require root, initialize
custom Mali contexts, install a Linux environment, or prove PanVK/Proton support.

## Build and run from Windows

Prerequisites: JDK, Python, GitHub CLI authenticated for upstream Actions artifacts,
Android SDK platform 34 and build-tools 35.0.0, and ADB on PATH.

From the repository root:

```powershell
python tools/pixel-probe/probe.py
adb devices -l
python tools/pixel-probe/probe.py --no-build --serial YOUR_AUTHORIZED_DEVICE_SERIAL
```

The device must be unlocked and authorize this computer for USB debugging. The
runner installs `dev.pixeldeck.probe`, opens its green GLES test surface, captures
the result, and stops only the probe. The installed app remains available for reruns.

Artifacts are under `build/pixel-probe/` (gitignored):

- `pixeldeck-probe.apk`: signed diagnostic app.
- `device-report.json`: Vulkan capabilities, actual app UID, device-node open results,
  and GLES clear/readback result.
- `device-screen.png`: device screenshot at completion.
- `device-logcat.txt`: filtered diagnostic/crash log.
- `provenance.json`: source artifact and binary hashes.

The Vulkan query reuses upstream's unmodified `libdeviceinfo.so` from CI artifact
11390530317, commit `b44235c495fa6458aa438c9ba3be06562e5d1a3c`. The script verifies
GitHub's artifact SHA-256 before extracting it. Actions artifacts eventually expire;
the cached ZIP permits subsequent offline builds. If it expires before download,
build upstream's `deviceinfo` CMake target with the NDK or select a verified newer
artifact and update the pinned ID/hash. A local debug signing key is generated at
`build/pixel-probe/debug.jks`; preserve it for updates and never commit it.
The runner uses a file-based ADB install and keeps Android's verification enabled.

Target SDK 28 matches DroidDeck. The probe is debuggable, so device-node results
describe a debug app; release permissions and Mali context creation need separate
verification. An `open` success does not prove that kernel ioctls or memory
allocation work. A green screen proves stock GLES rendering, not Vulkan rendering.
The Vulkan query only creates an instance and queries device information.

## Next experiment

Record Android/kernel versions and the report before choosing the Linux graphics
route. PanVK-kbase v0.1.2 documents Pixel 7/Tensor G2 testing with DroidSpaces and
requires `/dev/mali0` plus a suitable DMA heap for fast X11 presentation:

https://github.com/funnymdzz/mesa/blob/main/docs/panvk-kbase.md

That environment's permissions do not establish unrooted DroidDeck compatibility.
The author documents possible container-triggered kernel panics. Do not run its
custom driver in a container or install a kernel patch until the exact phone/kernel
requirements have been reviewed. First milestone: native Linux `vulkaninfo`, then
`vkcube`; retain stdout, stderr and the exact driver package hash. If device access
blocks that route, investigate the system-driver Vulkan wrapper before considering
kernel changes.
