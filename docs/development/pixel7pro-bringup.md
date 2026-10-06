# Pixel 7 Pro: first checks, 2026-10-06

Status: **stock GLES and Vulkan AHB import/render/readback/presentation passed**.
The diagnostic APK installed on a subsequent retry
with the phone awake. Earlier attempts received `INSTALL_FAILED_VERIFICATION_FAILURE`;
the exact reason for rejection and subsequent acceptance remains unknown.
Android verification stayed enabled. The full PixelDeck debug APK builds and
installs, and Linux runtime r9 is installed. Linux GPU rendering, Steam launch,
and game compatibility have not been established.

## Observed device and stock driver

- Pixel 7 Pro (`cheetah`), Android 17, build `CP2A.260705.006`.
- Kernel `6.1.157-android14-11-gbd23337e42e7-ab14791245`.
- `ro.boot.flash.locked=1`; no `su` executable found on the shell PATH.
- `cmd gpu vkjson`: Mali-G710, Vulkan **1.4.343**.
- Geometry and tessellation shaders supported; BC texture compression unsupported.
- `cmd gpu vkprofiles`: Android Vulkan profile 2025 and Android 17 requirements supported.

The debug app (target SDK 28) independently confirmed Mali-G710, Vulkan 1.4.343,
driver `v1.r54p3-00eac0.1848e3b066182d5bb5a345ab256f13ee`, conformance 1.4.5.0,
and 165 device extensions. Stock GLES 3.2 rendered a green surface and passed
pixel readback with no GL error, at 1080x2169. A subsequent native test imported
a 64x64 RGBA gralloc buffer into stock Vulkan, cleared it magenta, blitted it to
an Android swapchain, and successfully presented. CPU readback returned exactly
`255,0,255,255`. A live screenshot confirmed the magenta frame with the phone
unlocked. All tests ran under an ordinary debug app UID, without root.

The following extensions are advertised in the system GPU-service query:

| Extension | Advertised |
| --- | --- |
| VK_KHR_swapchain | yes |
| VK_KHR_external_memory_fd | yes |
| VK_EXT_external_memory_dma_buf | yes |
| VK_EXT_image_drm_format_modifier | yes |
| VK_KHR_image_format_list | yes |
| VK_KHR_external_semaphore_fd | yes |
| VK_ANDROID_external_memory_android_hardware_buffer | yes |
| VK_EXT_transform_feedback | yes |
| VK_EXT_robustness2 | yes |
| VK_KHR_dynamic_rendering | yes |

These cover the five extensions enabled by `waylandcomp/src/vk_present.c` plus
its optional external semaphore path. This is encouraging for testing the
compositor on the stock driver; extension advertisement does not prove allocation,
format/modifier compatibility, import, synchronization, or presentation.
The native app-UID test independently enumerated and enabled all five sharing
extensions, plus AHB external memory and foreign queue ownership, when creating
its device. This proves the AHB path, not arbitrary guest dma-buf import.

## Device nodes

`/dev/mali0` has mode `0666`; the debug app successfully opened it read/write.
`/dev/dma_heap/system` and `/dev/dma_heap/system-uncached` have mode `0444`.
The debug app successfully opened both heaps read-only, while read/write opens
failed with `EACCES`. Both heaps successfully allocated 4096-byte dma-bufs using
`DMA_HEAP_IOCTL_ALLOC` through the read-only descriptors. Custom Mali context creation was later confirmed by PanVK enumeration below.
Do not infer an unusable heap from the absence of write permissions alone.

The experimental PanVK-kbase source currently opens its selected DMA heap with
`O_RDWR`. The successful allocation test establishes that opening read-only is
worth adapting for this device. A scoped experimental preload made that change
for the pinned release test below:

https://github.com/funnymdzz/mesa/blob/main/src/panfrost/lib/kmod/kbase_kmod.c

## Full compositor and runtime

The compositor from the locally built full app was loaded into the isolated
probe and tested with stock Vulkan. A cyan SHM image rendered successfully and
all 4096 pixels survived GPU readback. Its ARGB8888 modifier query advertised
linear layout, and its exact `vkp_image_from_dmabuf` importer successfully
imported a 64 KiB system-heap allocation with a 256-byte row pitch. Import
success is separate from verifying guest rendering into that buffer.

A full PixelDeck session independently logged `compositor renders on Mali-G710
with the system Vulkan driver`, a working Wayland socket, and four linear
format/modifier pairs. Both native frame-generation engines reported available;
their operation has not been tested.

The full build completed on Windows. The regression tests in `DriverBundleTest`
and `DriverPairsTest` passed, including non-Adreno automatic selection returning
system Vulkan without unpacking Turnip. The next incremental APK build took
7 seconds after its initial dependency setup.

Windows CRLF checkout broke the staged Bash session scripts (`set: -\r: invalid
option`). `.gitattributes` and normalized Linux scripts fix this. The next session
reached gamescope, which failed to find a GPU through the runtime's Adreno ICD.
Direct glibc `vulkaninfo` executes correctly through proot but finds no device
with that ICD. `tools/pixel-guest.py` provides direct runtime commands without
starting gamescope, keeping this failure separate from display startup.

The kernel exposes no `pid` or `pid_for_children` namespace entries under
`/proc/self/ns` in either the shell or the proot guest. The currently documented
Pixel kbase panic fix targets **private PID namespaces**. This observation makes
that particular trigger less applicable to this device/run path; it does not
establish that all experimental PanVK ioctls are safe. The stock module hash is
unreadable without additional privilege. No kernel patch, flashing, reboot,
bootloader unlock, or device-wide permission/verification change was performed.
For one Steam test only, `activity_manager/max_phantom_processes` was raised
from its unset default to 64, then deleted to restore the original value.

## Linux PanVK experiment

The generic `kbase-v0.1.2` archive was pinned to Mesa commit
`4e5323ef35dc580a6140f8d433a6d13ae3724c07`, SHA-256
`c0e9f508a33f7b427df24a33e96ac7a1b3fde87d1e2e3ac47e964054071b05a3`.
Its library and ICD were staged only in PixelDeck's private data directory.
`heap_readonly.c` adapts opens of the two tested heap nodes to read-only for this
experiment; it does not change the returned dma-buf's read/write flags.
`vulkaninfo --summary` successfully enumerated Mali-G710 MC7 with PanVK API 1.4.352.
However, `KBASE_IOCTL_MEM_SYNC` returned `ENOSYS`, and the headless green clear
failed at `vkQueueSubmit` with `VK_ERROR_DEVICE_LOST` after a subqueue timeout.
The device remained connected after the failed submission. The failure was
subsequently traced to the runtime preload, rather than the kernel: see below.

The release includes X11 WSI only. `.github/workflows/pixel-panvk.yml` builds a
separate experimental artifact with Wayland and X11 from pinned upstream commit
`10acbfc4d9780c38d3896c95df2693ca88d8b28f`. That revision includes upstream's
userspace cache-maintenance path; our only Mesa source patch opens the allocation
heap read-only. The workflow also builds `linux_clear.c`. This artifact is not
installed or selected automatically by PixelDeck.

### Successful Linux GPU rendering

The release driver passed the same GPU clear/readback when run directly with the
installed glibc loader outside proot. Preloading libdrm explicitly then made it
pass inside proot too. The runtime globally preloads `libblsession.so`; its DRM
forwarder used `dlsym(RTLD_NEXT)`, which cannot find libdrm in a Vulkan ICD's local
`dlopen` scope. The missing function returned `ENOSYS`. A handle-based fallback
fixes this for all four DRM forwarders, retaining the existing Adreno behavior.
A regression check loads a fake libdrm locally and verifies each forwarded call;
`.github/workflows/pixel-runtime.yml` passed that check and built the ARM64 shim.

After installing the fixed shim, the Wayland-enabled PanVK build passed the
GPU clear/readback inside proot **without** the libdrm preload workaround:
Mali-G710 MC7, RGBA `0,255,0,255`. Driver SHA-256:
`b2300a77bb21048821da93b0441adedc2efd22fe268fe3d23190f9debf405ead`.
Runtime shim SHA-256:
`5c1d84bf93e2fe2696dc2ff4b1a4d52abfad2974b9fddf706e409208b7d447ce`.

The normal driver importer now accepts glibc PanVK packages, uses the generic
`libvulkan_driver.so` storage name, and still recognizes existing Turnip imports.
Its PanVK import and legacy-storage regression tests passed. The experimental
PanVK driver was selected only in the private PixelDeck debug app.

### Direct Wayland test

With gamescope bypassed, `vkcube --wsi wayland --c 600` selected Mali-G710 MC7,
created Vulkan swapchain images, and submitted 600 Wayland frames. PixelDeck's
session state recorded `firstFrame=true`. The current transport is **wl_shm**:
GPU rendering is followed by a CPU copy, not zero-copy dma-buf sharing. The
initial screenshot was obscured by Android's debug-app 16 KB compatibility
dialog, so visible cube verification remains pending user dismissal.

Gamescope's direct Wayland backend rejects kbase because it has no DRM primary
or render node. Patch `0114-vulkan-swapchain-without-drm-node.patch` permits
the Vulkan WSI backend to operate without a render node; the original DRM path
remains in use when one is available. The patched SDL backend then successfully
ran `vkcube --c 600` with PanVK. A 10-second compositor sample reported 346
frames (34.6 FPS) at 1280×720. This is a cube-test measurement on the current
CPU-copy transport, not a game-performance estimate. Gamescope binary SHA-256:
`569e396794334b2f51da1c69446b252df07b5097e162f88e3a7cece845b92b98`.

### Steam sign-in screen

The native ARM64 Steam client downloaded and installed. With PanVK selected,
the initial Zink OpenGL path repeatedly failed to create Steam's UI context.
Software OpenGL (`MESA_LOADER_DRIVER_OVERRIDE=swrast`,
`GALLIUM_DRIVER=llvmpipe`, `LIBGL_ALWAYS_SOFTWARE=1`) let the client reach
`READY` and render the Big Picture sign-in screen. A read-only Chromium
capture verified the actual rendered sign-in window behind Android's dialog.
No credentials were entered and no account or Steam game has been tested.

An earlier installed build sustained a Steam session for over two minutes with
child-process restrictions off. However, the exposed phone area remained black
while the guest Chromium capture showed sign-in. Steam logged
`AcquirePixmap: failed to create glx pixmap` / `GLXBadPixmap`. Disabling DRI3
did not fix it. A separate `-cef-disable-gpu` test removed those errors but still
showed black in both Big Picture and desktop Steam modes. Both temporary
experiments were reverted. Steam's **phone display path is not usable yet**;
`READY` and the guest screenshot do not establish successful phone presentation.

The first failed session was also killed by Android's phantom-process monitor
while updating Steam. Raising the cap temporarily separated that failure from
the graphics issue. After restoring the original unset cap, a fresh Big Picture
session reached `READY` again, but Android subsequently killed its proot tracer
while trimming phantom processes. The default process cap is therefore not a
stable Steam setup. The temporary cap was restored. To make normal Play work,
the project's existing Developer options prerequisite was then applied:
`adb shell settings put global settings_enable_monitor_phantom_procs false`.
This disables **Restrict child processes** and remains enabled for this working
test setup. Its original value was unset; restore that with
`adb shell settings delete global settings_enable_monitor_phantom_procs`.
The original cap remains unset. This change affects child-process monitoring
across the device, not just PixelDeck.
The app now applies the tested SDL/PanVK/software-OpenGL defaults when an
explicit PanVK import is selected; private environment overrides are unnecessary.
These defaults apply to all OpenGL child applications, including OpenGL games
and WineD3D. Vulkan applications still use PanVK. This is an experimental
working fallback, not hardware-accelerated OpenGL support for Steam.

Valve's optional `mangoapp` overlay threw on inaccessible `/sys/class/thermal`
and restarted six times before the runtime disabled it. PanVK now defaults this
overlay off; an explicit user setting still overrides that default. PixelDeck's
own display HUD remains available.

In the live Gamescope Xwayland display, a separate Zink `glxinfo -B` reported
accelerated Mali-G710 OpenGL 3.3 core/compatibility and GLES 3.1. Windowed
`glxgears` rendered 374 frames in 5 seconds. Thus windowed Zink works for this
test; the narrower Steam UI context failure still needs investigation.

### Android compatibility warning

The six bundled PulseAudio/dependency prebuilts have 4 KB LOAD alignment:
`libpulse`, `libpulseaudio`, `libpulsecommon-13.0`, `libpulsecore-13.0`,
`libsndfile` and `libltdl`. They need a proper rebuild, along with the matching
audio modules, to remove Android's debug-app 16 KB compatibility warning.
The newly compiled Wayland/device-info/main-hook/termux libraries already have
16 KB LOAD alignment; Android's extra “Unknown error” entries are misleading.
Both `max-page-size` and `common-page-size` linker flags now specify 16384
for native Android builds. This does not realign prebuilt libraries.

### Real Vulkan game

The pinned native ARM64 vkQuake 1.35.0 build with LibreQuake v0.09-beta lite data
ran through the same patched Gamescope/PanVK path at 1280×720. Its `demo1`
timedemo completed **4,527 frames in 107.5 seconds, 42.1 engine FPS**. Compositor
samples during the demo showed about **32–34 display FPS**. A GPU-readback PNG
verified a correctly textured 3D level and characters. The current transport
still copies GPU-rendered frames through SHM. The HUD now labels that counter
**Display fps**, keeping it separate from game timing and frame generation.

The engine selected PulseAudio, and the Android AAudio sink accepted its stereo
44.1 kHz stream. This verifies audio setup; audible quality still needs a human
check. Android's compatibility dialog obscures part of the phone presentation.
The phone must dismiss it before interaction can be checked.

The engine was built with optimization and debug shaders on Debian 13; this is
an early benchmark, not a final performance result. The reproducible build and
source/licenses are in `.github/workflows/pixel-vkquake.yml` and
[the successful game build](https://github.com/AutonomousLife/PixelDeck/actions/runs/37469820829).
This proves a native Vulkan game; Steam login and Proton/Windows compatibility
are separate outstanding checks.

### Copied XRGB presentation and aligned audio update

Gamescope treated internally created, sampled SHM XRGB textures as alpha-bearing.
XRGB's alpha byte is unused. Patch `0115-shm-xrgb-opaque-alpha.patch` forces alpha
to one for these opaque sampled textures, while preserving ARGB, imported dma-buf
handling, and identity components for storage images. The rebuilt Gamescope from
[run 37484454594](https://github.com/AutonomousLife/PixelDeck/actions/runs/37484454594)
now presents Steam's Big Picture sign-in screen on the actual phone. This replaces
the earlier black-output result. The software OpenGL fallback remains necessary;
the sign-in screen currently displays around 8–9 FPS. Login and Proton remain untested.

The original audio binaries exactly matched Bannerlator commit
`198893a07bfbc850d488d46160fdb734a5d411ac`. The pinned rebuild uses PulseAudio 13.0,
libtool 2.4.6, libsndfile 1.0.31 and Android NDK r27c, with both 16 KB linker flags.
The six libraries, matching loadable modules, and pactl pass ELF alignment and ABI
checks. All 22 libraries in the resulting APK have at least 16 KB LOAD alignment,
including the existing libffi. The new daemon and classic AAudio sink load on the
phone and accept vkQuake's stereo stream. See `tools/pixel-audio/README.md` for
artifact provenance and source/license locations.

Android retained an old compatibility dialog across the update, despite the
installed library hash matching the aligned binary. AOSP's AppWarnings checks
the new warning before dismissing an old instance, so a now-null warning can
leave that stale instance open. The Android `CLOSE_SYSTEM_DIALOGS` API dismissed
it without changing warning flags. Subsequent game and cube launches showed no
compatibility dialog.

The direct Wayland vkQuake timedemo also completed 4,527 frames in 89.4 seconds,
50.7 engine FPS. This bypasses Gamescope and is a separate performance result.
The compositor diagnostic additionally passed a second magenta upload into the
same SHM image after its initial cyan frame, verifying all pixels by GPU readback.

## Remaining steps

1. Fix stale Vulkan game frames through Gamescope and verify game input. A direct
   Wayland cube visibly rotates at 60 display FPS, but vkQuake through Gamescope
   still shows old startup frames despite the engine running. Disabling the
   Gamescope WSI layer did not fix the initial check; that override was reverted.
2. Sign in to the now-visible Steam client and test Proton/Windows games.
3. Fix Steam's Zink UI context and verify audible quality of the rebuilt audio stack.
4. Improve the current SHM presentation to dma-buf sharing and measure performance.

Repeat the current baseline with
`python tools/pixel-probe/probe.py --no-build --no-install --native --serial DEVICE_SERIAL` while the
phone is unlocked. The runner captures a report, screenshot and filtered log,
then stops its test activity. The installed diagnostic app remains available.

Local raw results are under `build/pixel-probe/` and are intentionally not
committed; keep device serials and screenshots out of the public repository.
