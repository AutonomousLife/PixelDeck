# PixelDeck: first device experiment

This separate diagnostic APK tests the stock graphics driver and device-node access
under a normal app UID. It does not change DroidDeck, require root, initialize
custom Mali contexts, install a Linux environment, or prove PanVK/Proton support.

## Build and run from Windows

Prerequisites: JDK, Python, Android SDK platform 34 and build-tools 35.0.0,
NDK 27.3.13750724, and ADB on PATH. No upstream binary or Actions artifact is needed.

From the repository root:

```powershell
python tools/pixel-probe/bootstrap_sdk.py  # Windows: install pinned NDK and CMake if missing
python tools/pixel-probe/probe.py
adb devices -l
python tools/pixel-probe/probe.py --no-build --serial YOUR_AUTHORIZED_DEVICE_SERIAL
python tools/pixel-probe/probe.py --no-build --no-install --native --serial YOUR_AUTHORIZED_DEVICE_SERIAL
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
- `native-report.json`: DMA-heap allocation, app-specific extensions, Vulkan AHB
  import, GPU clear/blit, presentation result and CPU pixel readback.
- `native-screen.png`: screenshot while the Vulkan swapchain is still live.
- `native-logcat.txt`: filtered native-test log.
- `provenance.json`: NDK version and locally compiled binary hashes.

Both JNI libraries are built directly from this checkout with the NDK. The basic
query uses upstream's `app/src/main/cpp/deviceinfo/vkinfo.c`; the native buffer test
uses `native_probe.c`. A local debug signing key is generated at
`build/pixel-probe/debug.jks`; preserve it for updates and never commit it.
The runner uses a file-based ADB install and keeps Android's verification enabled.

Target SDK 28 matches DroidDeck. The probe is debuggable, so device-node results
describe a debug app; release permissions and Mali context creation need separate
verification. An `open` success does not prove that kernel ioctls or memory
allocation work. A green screen proves stock GLES rendering, not Vulkan rendering.
The basic Vulkan query only creates an instance and queries device information.
The `--native` test additionally allocates 4096-byte buffers using the standard
DMA-heap ioctl through read-only heap handles, imports a gralloc AHardwareBuffer
into stock Vulkan, clears it magenta, blits to an Android swapchain, presents,
and verifies CPU readback equals RGBA `255,0,255,255`. It does not test Linux
dma-buf formats/modifiers, guest Vulkan, gamescope or Proton. Keep the phone
unlocked to verify the screenshot; a successful present call alone does not
establish that the display was awake.

## Full compositor check

After building the full app with `python tools/pixel-build.py`, run:

```powershell
python tools/pixel-probe/probe.py --compositor --serial YOUR_AUTHORIZED_DEVICE_SERIAL
```

This packages the locally built compositor into the isolated probe, verifies a
cyan SHM image against all 4096 GPU-readback pixels, presents it to the Android
surface, queries the actual ARGB8888 modifiers, and tests importing a system-heap
dma-buf. Import success alone does not verify rendering into the imported buffer.
Results use the `compositor-` prefix under `build/pixel-probe/`.

## Linux driver check

`tools/pixel-guest.py --serial SERIAL COMMAND...` runs a command in the debug
app's installed Linux environment without starting gamescope. It requires the
full app and a previously installed runtime. Pass a selected ICD explicitly;
the helper does not change the app's selected graphics driver.

The initial pinned release failed submission through the runtime DRM preload.
The fixed shim and Wayland-enabled PanVK build subsequently passed GPU readback
and a 600-frame Wayland cube run. See [the bring-up record](../../docs/development/pixel7pro-bringup.md)
for versions, cache-sync errors, and the separate Wayland driver build. Do not
interpret Vulkan enumeration as a rendering or Steam compatibility result.
