# Pixel 7 Pro: first checks, 2026-10-06

Current status: **Steam's sign-in screen, native Vulkan game rendering, Windows
Vulkan and one game's Direct3D 9 / Direct3D 11 (feature level 10_1) renderers
are verified on the Pixel 7 Pro**. The
device-tested `19a5ac8` build automatically selects the tested WineD3D/Zink fallback
for PanVK game launches. Steam login has succeeded. Steam game launches, player input, audible quality and general
D3D11/12 compatibility still need verification. The sections below record the
bring-up sequence, including earlier failures and the fixes that supersede them.

Initial checks: **stock GLES and Vulkan AHB import/render/readback/presentation passed**.
The diagnostic APK installed on a subsequent retry
with the phone awake. Earlier attempts received `INSTALL_FAILED_VERIFICATION_FAILURE`;
the exact reason for rejection and subsequent acceptance remains unknown.
Android verification stayed enabled. The full PixelDeck debug APK builds and
installs, and Linux runtime r9 is installed. At that stage, Linux GPU rendering,
Steam launch and game compatibility had not been established.

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

### Standalone Linux OpenGL defaults

The Steam software-OpenGL workaround originally applied to every PanVK session,
including standalone Linux programs. On `486b06e`, a normal app-launched
`glxgears -info` session reported llvmpipe. Build `eb8c118` confines the workaround
to Steam/desktop sessions, where Steam can run; standalone programs retain the
existing hardware Zink defaults. The rebuilt APK was installed, and the same
command then reported `zink Vulkan 1.4(Mali-G710 MC7 (MESA_PANVK))`, OpenGL 3.3.
Two phone captures show different gear rotations. These checks establish driver
selection and presentation, not a general performance gain or OpenGL 4.x support.
The six portable PanVK launcher checks and the APK build passed. Linux-only
shell tests do not run in the Windows development environment. The complete
`test_game_environment.py` suite was subsequently staged with its exact launcher
sources in a separate guest test directory and run inside the Pixel's Linux
runtime: **35 tests passed**, including generated Proton wrappers, profile
precedence, literal argument handling, tool-selection migration, PanVK defaults
and audio-prefix setup. These tests use temporary fixtures and do not establish
a signed-in Steam game launch. Local before/after logs are in `build/panvk/linux-gl-before/` and
`build/panvk/linux-gl-after/`.

Repeat the standalone check, without graphics environment overrides:

```powershell
python tools/droiddeckctl --package dev.pixeldeck.launcher --serial DEVICE_SERIAL run /usr/bin/timeout -- 45 /usr/bin/glxgears -info
python tools/droiddeckctl --package dev.pixeldeck.launcher --serial DEVICE_SERIAL logs latest ./linux-gl-check
```

Inspect the renderer in `session.log` and verify rotating output on the phone.

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

On the installed `eb8c118` build, the user subsequently signed in directly on
the phone. Steam's connection log records a successful `OK` logon response and
completed processing at 19:55 on 2026-10-06. A phone capture shows the Steam
welcome overlay with library artwork. Account identifiers and login details are
not included here. The installed-game manifest check finds only the Proton
runtime, so an actual Steam game installation and launch remain unverified.

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
the sign-in screen displayed around 8–9 FPS. Login and Proton were untested at
that stage; later Proton checks are recorded below.

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

Gamescope also memoized uploaded SHM snapshots by buffer identity. Reusing a
triple-buffered client swapchain then cycled old startup images instead of
uploading new pixels. Patch `0116-refresh-reused-shm-buffers.patch` restricts that
memoization to live dma-buf imports. Copied SHM textures upload on every commit;
the commit's reference retains the texture through rendering and buffer release
ordering remains unchanged. The build from
[run 37486644346](https://github.com/AutonomousLife/PixelDeck/actions/runs/37486644346)
now shows vkQuake's textured 3D demo on the phone at about 33 display FPS. Earlier
benchmark rates measured the stale-image implementation and must not be treated
as final playable performance. A fresh timedemo on the clean `b3d290f` APK with
the corrected copy path completed **4,527 frames in 102.0 seconds, 44.4 engine
FPS** at 1280×720. On-screen compositor samples were about 33–35 FPS. Separate
phone captures show different 3D scenes as the demo advances; game input remains
untested. The correct copy path currently allocates/uploads
a texture per client commit; reusing safe staging resources is a later optimization.

### Windows Vulkan game check

ARM64 Proton Experimental `experimental-11.0-20260924-arm64` (Wine 11.0) ran
`cmd.exe` through the normal app-launched session and wrote a verified marker
file with exit status 0. Running the same check through `pixel-guest.py` failed
to make relocated Windows DLL sections executable. That helper runs under
Android's `runas_app` security context; the actual session reports
`untrusted_app_27`, which has the needed `execmod` permission. Use the normal
app session for Windows execution checks rather than diagnosing that helper's
mapping failure as a Proton failure.

The official [vkQuake 1.35.0 Windows x64 release](https://github.com/Novum/vkQuake/releases/tag/1.35.0)
ZIP SHA-256 is
`abe075a51535744427b0591418aa6333af3732cc7c30893eb1ecfdb9cd19fd67`.
Its executable was verified as PE machine `0x8664`. With the same free LibreQuake
data, it rendered changing 3D scenes at 1280×720 through Proton/FEX; compositor
samples during the demo were **33.5–35.5 display FPS**. The game's log identifies
Mali-G710 MC7 / PanVK Mesa `26.2.0-devel (git-10acbfc4d9)` and initializes WASAPI
stereo 44.1 kHz audio through PulseAudio. Audible quality and player input still
require a human check.

The initial Windows launch failed in SDL display enumeration after DXVK failed
to initialize. The successful test used per-process `WINEDLLOVERRIDES=dxgi=b`
and unset the Linux-only `SDL_VIDEODRIVER=x11` override. Built-in DXGI supplies
display discovery while vkQuake renders with Vulkan directly; this does not
establish working Direct3D translation. At that stage, these overrides were
confined to the test script. To repeat a script check without
scanning its enclosing game tree for FEX binaries, launch its ARM64 interpreter:
`droiddeckctl ... run /bin/bash -- /root/your-check.sh`.

The installed `486b06e` build was subsequently checked through the normal
`waitforexitandrun` game route with a fresh numeric prefix. This supplied no
`WINEDLLOVERRIDES`, `PROTON_USE_WINED3D`, or graphics-driver overrides. The app's
PanVK defaults selected WineD3D, and Windows vkQuake initialized on Mali-G710,
rendering its 3D scene at 1280×720. Steady compositor samples after startup were
**33.3–35.2 display FPS**. Game and Proton logs are saved locally under
`build/panvk/vulkan-default/`. This verifies that this Windows Vulkan game also
works with the installed launcher defaults; it is not a Steam library launch.

An app-launched follow-up with `DXVK_LOG_LEVEL=debug` identified the default
Direct3D initialization blocker. The installed DXVK build
`v3.1.1-27-g25ca63f17f34bdc` finds Mali-G710 MC7, then rejects it with
`Device does not support required feature 'geometryShader'`. The current PanVK
driver's Vulkan version does not establish support for every feature DXVK needs.
The Windows vkQuake result above bypasses DXVK, so it remains valid; Direct3D
through this DXVK build is not working.

### Direct3D 9 fallback check

The official [FTE Windows x64 build at c781d13](https://github.com/fte-team/fteqw/releases/tag/2025-09-27)
ran the same LibreQuake demo using its Direct3D 9 backend through Proton,
WineD3D and hardware Zink. Its release ZIP SHA-256 is
`7da75f5f6a64ee8f988507bccb0081d58e119947b3132d583273840c19cc3fa9`.
The game log reports `Direct3D9 renderer initialized`; Wine reports
`GL_RENDERER "zink Vulkan 1.4(Mali-G710 MC7 (MESA_PANVK))"`. Wine's emulated
`NVIDIA GeForce 8800 GTX` adapter name is not the physical GPU.
Separate phone captures show the demo advancing from the arena to a corridor,
at about 30 display FPS. FTE's `-noupdates` option avoids its first-run update
source prompt. This verifies one D3D9 game, not general D3D11/12 compatibility.

The test set `PROTON_USE_WINED3D=1`, restored
`MESA_LOADER_DRIVER_OVERRIDE=zink`, `GALLIUM_DRIVER=zink` and
`LIBGL_KOPPER_DRI2=true`, and removed `LIBGL_ALWAYS_SOFTWARE` and the Linux-only
`SDL_VIDEODRIVER` override. Steam's client still needs software OpenGL; the game
can use the accelerated Zink context instead.

The clean `19a5ac8` APK was then built and installed with this behavior in the
normal game launcher. A fresh numeric game prefix launched via
`waitforexitandrun` inherited the client's `llvmpipe` setting, then selected
WineD3D and hardware Zink automatically. FTE's D3D9 demo rendered on the phone;
steady compositor samples were **37.1–39.7 display FPS**. The test supplied no
graphics overrides. Only PanVK game launches receive these defaults; Steam's
client/probes and other drivers keep their existing settings, and explicit
shared or per-game profiles override the defaults. Targeted launch/profile
checks and the incremental APK build/install passed.

### Direct3D 11 API check at feature level 10_1

On the installed `486b06e` APK, the same official FTE x64 executable launched
with `vid_renderer d3d11` through the default PanVK game environment and a fresh
numeric prefix. The game log reports `Direct3D11 renderer initialized` and
`D3D11 Feature level: 10_1`; Proton logs show WineD3D, `d3d11.dll` and the Mali
Zink renderer. Two phone captures show different arena/corridor scenes. Steady
10-second compositor samples were 39.1 and 38.6 display FPS at 1280×720.
No scripted graphics overrides were supplied.

The pinned [FTE renderer source](https://github.com/fte-team/fteqw/blob/c781d13/engine/d3d/vid_d3d11.c)
requests several feature levels and accepts the level returned by device
creation. [Direct3D feature levels](https://learn.microsoft.com/en-us/windows/win32/direct3d11/overviews-direct3d-11-devices-downlevel-intro)
are distinct from the API version. This verifies a D3D11 API game using feature
level 10_1, not games requiring feature level 11_0 or Direct3D 12. Wine's NVIDIA
adapter name remains an emulated identity; its actual renderer is Mali-G710.

### Steam hardware UI follow-up

The installed `486b06e` build was retested after the copied-frame fixes. Hardware
Zink alone still failed to present a first Steam frame. With SDL3's documented
[`SDL_VIDEO_FORCE_EGL=1`](https://wiki.libsdl.org/SDL3/SDL_HINT_VIDEO_FORCE_EGL)
switch, the session reached `READY`, and Chromium's fresh GPU report identified
ANGLE OpenGL on Zink / Mali-G710 rather than llvmpipe. Chromium's own screenshot
showed the sign-in page, but the phone remained black at effectively zero display
FPS. Steam's native `CCompositorGLThread` still reported failure to acquire a GL
context for its transparent window and fell back to its system composer.
Disabling the Gamescope WSI layer did not repair that output. This separates
successful browser rendering from successful phone presentation; `READY` alone
is insufficient. All temporary graphics overrides and diagnostic preloads were
removed, and the working software-OpenGL client setup was restored. No hardware
UI defaults were promoted from these failed trials.

A later temporary preload enabled Zink only in Chromium's GPU/zygote children,
leaving the web helper's native compositor on software OpenGL. The fresh browser
GPU report identified Mali-G710, and the native compositor successfully reported
`Loaded GL 4.6` and an OpenGL output window. The phone still displayed black at
effectively zero display FPS. This rules out simply splitting the two renderers
as a sufficient fix; it does not establish the remaining texture/presentation
failure's root cause. The preload and debug environment were removed, and the
original Steam wrapper was verified byte for byte after the trial.

A corrected temporary SDL3 diagnostic subsequently forwarded calls through the
actual loaded SDL3 library rather than `RTLD_NEXT`. It read the configured
context attributes immediately before calling the real `SDL_GL_CreateContext`:
OpenGL **4.3**, core profile, no shared context. The real call returned null with
`EGL_BAD_MATCH`. SDL's [attribute implementation](https://github.com/libsdl-org/SDL/blob/release-3.2.28/src/video/SDL_video.c)
reads the requested major/minor/profile from its configuration for these queries.
An independent `glxinfo -B` session on the same installed Mali/Zink setup reports
maximum core and compatibility profiles of **3.3**, with hardware acceleration.
The driver cannot satisfy Steam's requested 4.3 context. This establishes a real
capability mismatch; the EGL switch alone cannot solve it. Temporary diagnostic
libraries and environment overrides were removed. Raw request logs are under
`build/panvk/steam-ui-sdl-request/`; capability logs are under
`build/panvk/linux-gl-capabilities/`.

### Windows game audio signal check

A subsequent FTE D3D11 session on `486b06e` supplied a playback stream to the
classic AAudio sink. A 12-second capture from the explicitly selected
`AAudioSink.monitor` contained 2,108,232 bytes: 11.951 seconds of signed 16-bit
stereo PCM at 44.1 kHz. Both channels contained nonzero audio; neither reached
the signed 16-bit clipping limits. This captured only the playback mix, with no
microphone source. Android's app-UID logs independently report a successful
MMAP AAudio stream open and start (`AAUDIO_OK`, low-latency mode), followed by
the started state. The game stream negotiated approximately 30 ms with
PulseAudio. That is a negotiated buffer value, not measured end-to-end latency.
The local recording and analysis are under `build/panvk/windows-audio/`.
This proves audio data reaches the playback sink; actual speaker volume,
distortion, synchronization and controller interaction still need human checks.

### Steam UI performance investigation

A repeatable 15-second library-scroll diagnostic, measured from Android
SurfaceFlinger presentation timestamps rather than JavaScript callbacks,
confirmed severe UI stutter: one software-rendered run averaged 17.9 displayed
FPS with a 133 ms 95th-percentile frame interval. Pinning the client to cores
4–7 and limiting llvmpipe to four workers did not improve subsequent runs;
both temporary overrides were removed. These sequential diagnostics are not a
controlled thermal benchmark or proof of stable performance. Steam's own
library low-performance and reduced-motion preferences were enabled and read
back successfully.

The next accelerated diagnostic lowered only Steam webhelper's exact SDL3
4.3 core-context request to a real 3.3 context. It did not override the reported
GL version, extensions, or feature support. EGL created the context, but the
webhelper repeatedly restarted. Using GLX and enabling Kopper in the helper
also created the context and reached Zink/PanVK, but the GPU queue timed out
and Zink reported `VK_ERROR_DEVICE_LOST`; the actual Steam output was black.
The experimental preload and environment file were removed and the software
renderer restored. Local evidence is under
`build/panvk/steam-context33-glx-logs/` and the scroll measurement JSON files.
Stable 60 displayed FPS in Steam remains unverified. The accelerated failure
now supplies a concrete GPU queue/synchronization case for driver work.
Repeating the GLX diagnostic with `PANVK_KBASE_USER_CACHE_SYNC=0` briefly
displayed Steam content, then reported CSF group fatal errors with exception
`0xc1` and another `VK_ERROR_DEVICE_LOST`. The scroll diagnostic's CDP call
timed out; its partial timestamp sample is not a valid completed benchmark.
This override was also removed. Its logs are saved separately under
`build/panvk/steam-context33-kernel-cache-logs/`.

A separately staged candidate built from Mesa fork revision
`5aa0bc44652a6a0d597c7ce63bb6b3aca2de8b45` passed GPU clear/readback and
created a real Zink GL 3.3 context in Steam. It still produced black output,
CEF restarts, CSF fatal exception `0xc1`, and device loss. Its uninstrumented
failure occurred around 4,097 queue submissions; enabling `sync,kbase_diag`
failed at submission 33 instead, so the evidence does not establish a 4,096
counter-wrap defect. The latter run reached fragment progress marker `0x350`;
that marker does not prove a FINISH_FRAGMENT instruction executed, because
kbase skips that instruction. Candidate diagnostic markers are otherwise
disabled by default. Logs are under `build/panvk/steam-candidate-default-logs/`
and `build/panvk/steam-candidate-sync-logs/`.

`PAN_USE_KRAID=all` aborted on the unsupported `load_pixel_coord` intrinsic.
A separate `-cef-disable-gpu` launch stayed usable but measured approximately
7.9 displayed FPS during the same scrolling diagnostic. It did not establish
an improvement. All diagnostic overrides and the modified guest launcher
were reverted; the candidate driver remains staged separately for further
investigation. The original installed driver and working Steam path remain
the baseline. No stable-60-FPS claim follows from these tests.

## Remaining steps

On the `19a5ac8` build, Steam's own `controller.txt` log identifies the
virtual Steam Deck controller at `/dev/hidraw16`, opens it, reserves XInput slot
0 and queues its UI mapping. The session's `pad.log` confirms the shared ring
at the PixelDeck package path opens successfully. This establishes controller
discovery, not a player-input or Steam Input game-mapping test.

The subsequent control review found that pausing the activity released the
on-screen pad but could preserve physical controller buttons/axes and guest
keyboard keys. Build `486b06e` adds the same controller/key release calls already
used by picture-in-picture. Its incremental APK build and installation passed;
the held-input/background/resume behavior still needs a physical-input check.

1. Verify game input. A direct
   Wayland cube visibly rotates at 60 display FPS; vkQuake now shows its 3D demo
   through Gamescope. Disabling the Gamescope WSI layer or using kernel cache
   synchronization did not fix the old memoization bug; those overrides were reverted.
2. With Steam now signed in, install a library game and test Steam game launches and
   Direct3D translation. One standalone Windows Vulkan demo is verified above.
3. Fix Steam's Zink UI context and verify audible quality of the rebuilt audio stack.
4. Improve the current SHM presentation to dma-buf sharing and measure performance.

Repeat the current baseline with
`python tools/pixel-probe/probe.py --no-build --no-install --native --serial DEVICE_SERIAL` while the
phone is unlocked. The runner captures a report, screenshot and filtered log,
then stops its test activity. The installed diagnostic app remains available.

Local raw results are under `build/pixel-probe/` and are intentionally not
committed; keep device serials and screenshots out of the public repository.


### CSF command address fix (2026-10-06)

The Steam GPU fault was traced to `uint32_t fn_addr` in
`csf/panvk_vX_cmd_draw.c`: the helper BO address is 64-bit, but a CALL
received only its low 32 bits. The patch preserves the full address with
`uint64_t`. The fault address `0xfffef000` matched that truncation.

Fixed driver build 37562778779 passed GPU clear/readback on the Pixel 7 Pro.
Steam hardware scrolling then measured 39.6, 34.1, and 32.0 displayed FPS
across separate 15-second runs, with no CSF fatal/timeout in the inspected
helper log. A paused session was excluded from measurements. These results
prove improvement, **not stable 60 FPS**.

The installed production APK at d1093b6 uses a driver metadata opt-in
(`pixelSteamGl33`) so older PanVK imports retain software fallback. The
native preload clears Steam's Kopper disable flag and changes only its
exact SDL3 4.3 core context request to real 3.3, scoped to steamwebhelper.
Driver `pixel-panvk-csf64` is selected separately from the original import.
Temporary SDL diagnostic preload/env overrides were removed. A normal
launch measured 34.5 displayed FPS (p95 50.1 ms, max 83.4 ms) with no
GPU fatal/timeout log. Driver import unit tests and APK build passed.

With the address fix installed, the kernel cache-sync override measured 33.5 FPS
(p95 50.1 ms); it did not improve the normal path and was removed. Android
thermal status and CPU/GPU cooling-device throttle levels were zero.

A 15-second Chromium trace on the fixed driver recorded 491 GPU buffer swaps:
`NativeViewGLSurfaceEGL:RealSwapBuffers` averaged 19.29 ms (max 69.56 ms);
renderer BeginMainFrame averaged 12.71 ms. Nested tracing totals overlap and
are not additive. A recognized `vblank_mode=0` override measured 34.7 displayed
FPS (p95 50.1 ms), so changing that swap-interval setting did not improve
performance; the override was removed. Stable 60 FPS remains unverified.

### Direct Chromium Vulkan comparison

Research confirmed ANGLE's Vulkan backend and the installed Steam client's
`-cef-use-vulkan` switch. The older launcher arguments `-cef-use-angle=vulkan`
did not select it: Chromium SystemInfo reported ANGLE_OPENGL. Temporary edits
to the guest launcher are replaced by SessionFiles at startup, so session 96
was excluded as a Vulkan comparison. A rebuilt launcher in session 97 did
report ANGLE_VULKAN and enabled Vulkan, rendering correctly on Mali-G710.

Actual displayed scrolling remained 34.6 FPS (p95 50.0 ms, max 116.7 ms).
The Vulkan trace measured Skia SwapBuffers at 20.8 ms average, while renderer
BeginMainFrame improved to 9.39 ms. One initial VK_ERROR_OUT_OF_DATE_KHR
triggered a GPU helper restart. With no frame-rate gain, the launcher change
was reverted and the tested OpenGL launcher APK reinstalled.

Editing Valve's helper wrapper triggered its integrity repair; repair was
allowed to finish. No updater-managed helper modification is retained.
Native simpleperf could not profile with the current perf_harden setting;
no device security property was changed.

### Presentation diagnostics and resolution comparison

A temporary locally scoped XCB timing preload measured 13,500 replies at
1,592 ms cumulative time, about 0.118 ms per reply; scrolling with it measured
34.0 FPS. Its initial RTLD_NEXT-only lookup failed and that startup was
excluded; resolving the actual libxcb handle fixed the timer.

An additional ppoll timer saw 78,800 calls requesting 20 ms, only 10 timing
out, and 26,972 ms cumulative wait time. Most wake early, so the driver is
not simply sleeping 20 ms at every completion. These cumulative counters
include startup and idle work and are not per-frame costs.

GPU clock samples during scrolling ranged 251–572 MHz in standard game mode.
Android's supported performance mode measured 33.2 FPS with a similar clock
range; standard mode was restored. No GPU sysfs value was written.

A clean 960x540 session measured 35.4 displayed FPS (p95 50.0 ms, max 83.3 ms),
compared with approximately 34.5 FPS at 1280x720. The smaller resolution was
not retained. All timing preload overrides were removed. The requested
smooth high-FPS Steam experience remains unachieved.

### DMA-buffer transport isolation (October 7)

The global `PANVK_KBASE_DRI3=1` diagnostic made Steam's Zink swapchains fail
(session 105). It was removed. A separate diagnostic constructor enabled it
only in Gamescope, retaining Steam/Xwayland SHM. That path rendered correctly:
native compositor counters reported 381 DMA-buffer frames and zero SHM redraws
in one 10-second interval. Actual 15-second scrolling measured 36.1 FPS versus
36.8 FPS in the restored normal session. No frame-rate improvement was shown,
so that diagnostic preload and environment file were removed.

The underlying transport limitation remains: stock Xwayland lacks its DRM/GBM
presentation path on kbase. Gamescope can export Android heap DMA-buffers to the
native Wayland compositor, but this does not make Steam's inner Xwayland
swapchains support DRI3. GPU completion waits must remain without cross-process
fences. Native compositor DMA-buffer import still copies/blits into Android's
swapchain; these counters do not claim direct SurfaceControl presentation.

For native profiling, `security.perf_harden` was temporarily set to zero in a
try/finally diagnostic and restored to its original value of one. Both
`cpu-clock` and `cpu-cycles` were unsupported by the SDK profiler, so no CPU
profile was collected. The restored property was verified after cleanup.

A Gamescope upload-ring candidate (native CI 37574863869, source efa1059)
reused its persistent transfer buffer, inserted a transfer-write barrier,
and submitted SHM uploads asynchronously. Exact upstream source patch and
capacity/fallback checks passed; native build and APK build passed. Steam
rendered correctly on the installed candidate, but actual scrolling was
36.6 FPS (p95 50.0 ms, max 83.3 ms), essentially unchanged from the 36.8 FPS
comparison. An earlier measurement before the library loaded was invalid.
The candidate was removed from the default source/build pins and the prior
APK restored. Stable high-FPS Steam remains unachieved.

Helper affinity diagnostics confirmed the original 0x7c mask changed to
0xf0 or 0xff within steamwebhelper itself. Four middle/fast cores measured
35.6 displayed FPS; all eight cores measured 34.7 FPS, both with p95 about
50 ms. Neither improved the normal fixed-driver path. The temporary preload
and environment file were removed; the standard session restarted READY.
An external taskset attempt was denied before any affinity mutation. Its
concurrent benchmark overlapped a later stop and is excluded.

### Cached readback candidate (October 7)

Driver source `d763b96`, native CI 37579564536 / artifact 11464700044,
keeps the CSF address fix and adds default-off `PANVK_KBASE_CACHED_WSI=1`.
The kbase CPU WSI path lacks a cached/coherent type, so the normal WSI selector
falls back to uncached/coherent readback. The opt-in selects cached staging
and invalidates its full mapped allocation after the existing GPU completion
fence, before backend CPU copying. Imported-host and DMA paths are excluded.
Source scope/order checks and native compilation passed.

A separately staged candidate rendered correct Steam pixels. The session log
confirmed its ICD path. Two enabled 15-second scrolling runs measured 43.8
and 42.2 displayed FPS, with p95 frame gaps 33.4 ms. No fatal/translation/device
loss was found in the inspected helper log. Disabling the flag on the same
binary measured 33.2 FPS, p95 50.0 ms, max 100.0 ms. This controlled comparison
supports a real gain. The enabled diagnostic is restored for further work;
production driver selection remains unchanged. Smooth high FPS remains unproven.

### Actual Android cadence and remaining X11 transport (October 7)

The cached-driver trace reduced Chromium's real EGL swap duration from about
19.3 to 13.8 ms average; renderer BeginMainFrame remained about 11.8 ms.
Combining cached readback with Gamescope-only DMA output measured 43.7 FPS,
with 432 native DMA frames and zero SHM redraws in one interval. It provided
no additional gain, so the DMA preload was removed.

SurfaceFlinger showed an actual 60 Hz app override and active display mode,
despite the session reporting its requested 120 Hz. CompositorHost voted
on its optional display layers but never on the output Surface itself.
The new API-guarded Surface.setFrameRate request covers initial attachment
and reattachment, preserves the user's frame cap, and was accepted: the
app override, render rate, and active mode all became 120 Hz. APK compilation
and an independent API/lifetime review passed. Scrolling measured 45.6 FPS
then 40.1 FPS, versus a fresh 40.6 FPS baseline; p95 gaps were about 41.7 ms.
This fixes the missing cadence request but does not establish smooth 60 FPS.

Direct ANGLE Vulkan combined with cached readback and the cadence fix measured
39.3 FPS. SystemInfo confirmed ANGLE_VULKAN; it was reverted. Mailbox mode on
the restored OpenGL path measured 42.1 FPS and provided no clear improvement.

A rootful Xwayland 24.1.13 experiment removed Gamescope's extra rendering stage.
It started through the native compositor's xdg_shell support, but Steam remained
black: its own window compositor requested GLSL 4.30 on the real GL 3.3 driver.
Captured vertex and fragment shaders used only basic GLSL 3.30-compatible
operations. A temporary shader compilation diagnostic passed that first hurdle,
but Steam then lost its X11 connection and exited. No displayed-FPS result from
that experiment is valid. The launcher and diagnostic preload were removed.

Further source inspection corrects an earlier transport assumption: Mesa's
X11 Vulkan WSI enables MIT-SHM only with EXT_external_memory_host. This PanVK
does not support host-memory import, so its CPU X11 path uses xcb_put_image
socket payloads instead. An opt-in staging-to-SysV-SHM copy can avoid those
payloads without claiming host-memory import or removing GPU completion/cache
waits; it requires a server reply after the SHM request before reusing pixels.

### X11 SHM transport and swapchain ownership (October 7)

Native CI 37606951483 / artifact 11474664576 compiled the default-off
`PANVK_KBASE_SHM_COPY=1` path. Checked attach, padded-stride limits, GPU fence /
invalidate ordering, and a geometry reply after ShmPutImage gate image reuse.
The candidate rendered correct Steam pixels. Scrolling measured 45.5 displayed
FPS enabled, then 42.1 and 43.0 disabled on the same binary with cached readback
retained. The result does not establish a substantial SHM transport improvement.
The phone reported thermal status zero during these comparisons.

Importantly, Gamescope's `flip: true` surfaces use Mesa Wayland WSI. The observed
new X11 SHM allocations were only 32x32 fallback surfaces, so X11 socket payloads
are not established as the main-frame bottleneck. The common cached-readback
patch also covers Wayland's CPU staging and remains the proven improvement.
New PanVK bundle metadata `pixelCachedWsi` lets the app enable it for Steam
without a diagnostic environment file; older bundles and Turnip remain opt-out.
Eight driver import/compatibility tests passed.

Session 19's black content screenshot invalidates its otherwise 42.3 FPS scroll
sample. Fresh sessions 20 and 21 showed correct pixels before and after scrolling;
session 21 also retained its content while idle. Source review found a separate
Gamescope ownership bug: destroying an older protocol swapchain can erase a
newer swapchain's content override when both share a Wayland surface. Patch 0117
checks ownership before clearing the dying resource's pointers. The exact pinned
3.16.29 source applies without fuzz and the lifecycle regression check passes.
The initial native build caught private-member access; the revised public API
returns ownership before clearing matching pointers. Actual changed C++ bodies
now compile in the regression check, which also rejects the original invalid
private access. Native CI 37611054218 / artifact 11478007257 passed.

The combined APK was built, its session scripts verified, and installed. The
selected driver was upgraded to the byte-identical tested cached library with
the prior library and metadata backed up. The diagnostic environment override
was removed. Session 22 confirmed the selected ICD and automatic cached-readback
flag, rendered correct Steam pixels, and measured 45.8 displayed FPS, p95 41.6 ms,
max 50.0 ms. This is a successful deployment and smoke check; stable 60 FPS and
the ownership bug's causal link to session 19's black output remain unproven.

### Native Wayland GPU buffer sharing (October 7)

The main Steam frame path previously used Wayland SHM through Gamescope's WSI
layer. Gamescope withheld its inner DMA-BUF global because kbase has no DRM
render node. The coordinated, default-off `PANVK_KBASE_WAYLAND_DMABUF=1` patches
advertise DMA-BUF v3 using real importable LINEAR RGB formats and select native
Wayland images in PanVK. X11 retains CPU WSI. Producer fence completion and the
SDL backend's composition completion remain in place before buffer reuse.

Gamescope CI 37612621554 / artifact 11478149893 passed and statically linked the
patched, checksum-pinned wlroots 0.20.2. PanVK CI 37612621186 / artifact
11478430840 passed; its library SHA256 is
`dd9773aa81272769bb89d3537978b840aca7c7ff0554b28bf9cb57a4c9b91b8c`.
Independent format, allocation, protocol and buffer-lifetime reviews passed.

Session 23 rendered correct Steam content and measured 53.0 and 50.9 displayed
FPS, with p95 frame gaps 33.3 ms. Session 24 disabled sharing on the same binary
with cached readback retained and measured 42.3 and 42.5 FPS, p95 41.7 ms.
Physical captures before/after scrolling were correct in both configurations.
Logs confirmed the inner DMA-BUF global, native producer chains and native GPU
frames at the Android compositor. Thermal status was zero during the comparison.

The tested library replaced the selected driver's bytes with a separate backup
of the previous cached driver. Bundle metadata `pixelWaylandDmabuf` enables the
flag automatically only for Steam and selected PanVK; old bundles and Turnip
remain opt-out. All eight driver-import tests passed. The APK and its session
assets were verified and installed; the diagnostic environment file was removed.
Session 25 used this automatic configuration, rendered correct pixels and
measured 51.4 FPS. It survived background suspension and Activity/Surface
recreation, then measured 50.2 FPS with correct pixels. Long frame gaps remain
(up to 266.5 ms in the resume sample); stable 60 FPS is not established.

This transport uses SHM when no suitable DMA-BUF global exists. An import failure
after DMA-BUF advertisement does not retry through SHM; the controlled Gamescope
global validates the actual import before accepting the buffer. The experiment
is scoped to the tested Pixel 7 Pro and SDL backend, not general Tensor support.

### Repeated XCB-query experiment (October 7)

The actual Steam helper mapped runtime r9's Gamescope WSI layer, SHA256
`47f52dabf07441062065580e2801a8c29792c1dfe2f0dc035f8636b560af5434`.
An opt-in patch reused current-frame geometry and cached an immutable X atom,
removing three synchronous replies without changing presentation/fence waits.
The native layer was built and staged from Gamescope CI 37615387781 / artifact
11478674395, with library and version compatibility checks passing.

Same-layer flag-off runs measured 47.2 and 50.5 displayed FPS; flag-on runs
measured 46.3 and 48.8. Physical Steam content remained correct. The first enabled
run included a 1,083.2 ms presentation gap. This establishes no improvement.
The patch and extra layer shipping changes were removed. The original r9 layer
was restored byte-for-byte, and the diagnostic flag was removed. Native GPU
sharing and automatic driver metadata remain enabled.

Final session 28 with the restored original layer and no diagnostic environment
file rendered correct pixels before/after scrolling and measured 54.1 displayed
FPS, p95 33.3 ms, max 50.0 ms. Its inspected logs contained no GPU translation
fault, device loss or failed import. The selected driver retained the tested
DMA-BUF library and automatic metadata. This is another successful short sample,
not proof of stable 60 FPS or absence of later stutters.

### Surface lifetime and Steam timing correction (October 7)

Gamescope retained raw Wayland surface pointers in resolved queues and held
commits after the surface was destroyed. Patch 0119 tags each commit with the
surface generation, retires its presentation feedback on destruction, and
checks that generation under the Wayland lock before accessing surface state.
The ASan regression extracts the actual patched functions: the original code
reproduces a heap use-after-free; the patched cases pass, including reused
addresses, queued and held feedback, client-first cleanup and buffer release.
This fixes a demonstrated lifetime bug; its causal link to the earlier phone
heap-corruption crash is not established by a backtrace.

Gamescope CI 37702781451 / artifact 11518696743 passed. The installed executable
matches the APK asset, SHA256
`ddb1fecdc27d5613d1992dd931790c5ac8a05c9552e3841da7655d03f727efa9`.

Steam's ANGLE EGL layer advertised sync-control timing while native Gamescope
presentation bypassed Xwayland's Present counters. An observational probe in
the actual CEF GPU process returned a real 119.86 Hz rate but frozen UST,
MSC 1 and SBC 0 across almost a second. The original Chromium trace scheduled
frames at 16,666 microseconds despite Android's 120 Hz output and RandR's
119.86 Hz mode.

The existing Steam GL constructor now sets Mesa's supported
`glx_extension_override=-GLX_OML_sync_control` only for `steamwebhelper` with
the verified PanVK Steam flag and native DMA-BUF option. An explicit user
override takes precedence. This withdraws unusable timing capabilities so CEF
uses the real RandR refresh; it does not invent timestamps or skip GPU waits.
Runtime CI 37704026605 / artifact 11517904388 passed the constructor scope and
override regression, libdrm forwarding check, and ARM64 build. Its installed
library matches the APK asset, SHA256
`9836be53b6fb8988d2d183e329ddd862bfcd79b31ebf52a1d40a85863ae0c667`.

Session 2026-10-07-06-steam used the installed APK with no diagnostic environment
file. SystemInfo confirmed ANGLE OpenGL on Zink/PanVK, zero GPU-process crashes,
and absence of both EGL sync-control capabilities. A fresh trace recorded
8,343-microsecond begin-frame intervals (119.86 Hz), with no SyncControl provider
calls. Correct physical Steam pixels were verified after scrolling. Two
15-second displayed-frame samples measured 50.3 and 51.3 FPS, p95 gaps 33.4 ms,
with maximum gaps about 183 ms. The inspected session log contained no GPU
translation fault, device loss, failed import or heap-corruption error.

The timing correction is proven; locked 60 or 120 displayed FPS is not. The
fresh trace still shows about 9 ms per renderer main frame and 9.4 ms average
wall time inside real swaps. Nested trace spans cannot be summed to claim a
single frame cost. Swap blocking needs to be distinguished from required GPU
completion before changing pacing or synchronization.

A recognized `vblank_mode=0` comparison on this installed DMA-BUF path measured
54.4 and 52.9 displayed FPS, p95 33.3 ms, with a maximum gap of 500 ms in the
second sample. Correct Steam pixels and the hardware renderer were verified.
Real swap wall time still averaged 9.0 ms in its fresh trace. This does not
establish that vsync causes the swap blocking, and the override was removed.

The subsequent normal-configuration restore, session 2026-10-07-08-steam,
measured 34.0 displayed FPS, p95 49.9 ms, max 125.0 ms, with correct pixels.
Hardware rendering and the 8,343-microsecond scheduling interval remained
active; Android reported thermal status zero, and process inspection found
only the current Steam session. Its fresh trace showed 16.7 ms average real
swap wall time but only 1.7 ms average thread CPU time, while renderer main
frames remained about 9.0 ms. The earlier 50–55 FPS samples are therefore not
a sustained performance guarantee. Presentation blocking varies and remains
the main unresolved target; the exact GPU/compositor dependency is unproven.

### Next steps for presentation blocking (October 8)

The open target is the unexplained wall time inside real swaps (about 9 to 17 ms)
while renderer main frames stay near 9 ms of CPU. Measure before changing pacing:

1. Split each real swap into its children in one trace: GPU submit, fence or
   completion wait, and the Wayland or X11 present call. Record which child carries
   the wall time. Thread CPU time (1.7 ms) already shows the swap is mostly waiting.
2. Repeat the same 15-second displayed-frame sample three times in the normal
   configuration. Report the spread, not a single number. The 34 to 55 FPS range
   shows that one sample is not enough.
3. Check whether the waits line up with compositor frame callbacks. If they do,
   the blocking is downstream of PixelDeck and belongs to the compositor path.
4. Only after 1 to 3 agree, test one change at a time. Keep the `vblank_mode=0`
   result as a comparison, not a fix, unless it reproduces with the same sampling.

Done when the swap wait is attributed to a specific child with repeated samples,
or the attribution is recorded as impossible with the trace that showed why.

### Benchmark correction and full-Steam present attribution (October 8)

**Tested build and configuration.** Installed APK `local dirty · codex/pixel-gpu-probe at 1a03bcf`,
runtime r9, Steam Big Picture at 1280x720 / 120 Hz, driver `pixel-panvk-csf64` with SHA256
`dd9773aa81272769bb89d3537978b840aca7c7ff0554b28bf9cb57a4c9b91b8c` (the DMA-BUF candidate),
no `files/pixeldeck-env` override, thermal status 0. Raw results are in `build/bench/` (not committed).

**Benchmark defects found and fixed.** The untracked `build/panvk/measure-steam-scroll.py` is
replaced by `tools/pixel-bench/steam_scroll.py` (tests: `tools/tests/test_steam_scroll_bench.py`).
- It counted frames over the guest helper's whole lifetime, including startup and teardown, not
  only while the page scrolled. The new tool measures only the scroll window, trimmed by 250 ms.
- Its sine-wave scroll slows below one pixel per frame near each turnaround, so the page stops
  changing for ~150-270 ms and no frame is presented. Those gaps landed ~150 ms after every
  turnaround (1.48, 4.17, 6.87, 9.50, 12.16 s into each run) and are the "158-267 ms stalls" of
  this and earlier reports. A constant-speed triangle scroll (240 px/s) removes them.
- Polling SurfaceFlinger through one adb process per poll took 0.3-0.8 s. This phone keeps only
  ~60 frames of history (about 1.1 s at 55 FPS), so slow polls could drop frames silently. Polling
  now runs in one on-device loop every ~100 ms, and a run is rejected if a poll does not overlap
  the previous one. Two runs were correctly rejected this way before the change.
- A guest error with exit status 0 used to count as success. The tool now also rejects runs when
  focus or the awake state is lost, when the scroll moves less than 200 px, or when fewer than 60
  frames appear. Each run records Chromium's requestAnimationFrame cadence, the Mali clock, the app
  build, session, every installed driver's hash, the env override file and thermal status.

**Corrected baseline** (fresh session 2026-10-08-03-steam, constant-speed scroll, 3 valid runs):
54.5, 53.4 and 54.0 displayed FPS; median gap 16.67 ms; p95 33.4 ms; p99 41.7 ms; worst 58, 50
and 67 ms; 17-20 gaps over 34 ms per 14.5 s. Chromium's requestAnimationFrame median is 16.7 ms,
so the renderer runs at 60 Hz, not 120. The Mali clock (`cur_freq`) had a median of 471-510 MHz
during runs, with a highest sample of 701 MHz; the frequency table itself is not readable from adb.

**Full-Steam present attribution.** The observation-only `LD_AUDIT` library
(`build/panvk/libpixel-swap-poll.so`, SHA256 605afe0b...) ran in session 2026-10-08-02-steam.
Across 12 report windows of 240 presents in Steam's GPU process:
- Zink's present thread: `vkQueuePresentKHR` median 12.7 ms per present (11.1-13.6 ms).
- Inside it, `ppoll` at driver offset `0x65b668` took a median 10.7 ms per present (85 %), over
  ~46 calls per present. Every call returned ready after ~0.25 ms and none timed out: the driver
  wakes repeatedly while waiting for GPU work to complete.
- `vkQueueSubmit` cost 0.27 ms; ANGLE's `eglSwapBuffers` on the GPU main thread 9.9 ms median;
  `vkAcquireNextImageKHR` 3.2 ms median.
The offset cannot be named: the CI driver is stripped (`.dynsym` only). With the audit loaded,
two runs measured 55.6 and 56.0 FPS under the old sine scroll, without the turnaround gaps; that
comparison predates the scroll fix and is not evidence that the audit changes timing.

**Conclusion.** A present waits about 11 ms for GPU completion while the GPU runs at a median of
roughly 400-510 MHz. Per-frame waiting, not shader throughput, caps the pipeline: an earlier 960x540 run
did not help either. 120 Hz needs a present under 8.3 ms. The next step is a driver build that
names the waiting site, then a GPU-side wait for incoming semaphores in the kbase present path.
Driver builds run in CI (`pixel-panvk.yml`); downloading the artifact needs `gh` authentication.

**Session restored.** `files/pixeldeck-env` was removed and the session restarted READY
(2026-10-08-03-steam). `droiddeckctl stop` reported `ARTIFACT_TIMEOUT` on both restarts although
the session stopped; that is an open reliability defect.

### Session stop reported a false failure (October 8)

**Problem.** `droiddeckctl stop` returned `ARTIFACT_TIMEOUT` on every restart although the session
stopped in about 6 s. `events.jsonl` showed artifact collection finishing 117 s (session 02) and
195 s (session 03) after `session.stopped`, while the CLI waited 90 s for stopping and collection
together. Collection redacts ~27 MB of Steam logs line by line with 16 regular expressions; the
redactor managed 2.3 MB/s on the PC and roughly 0.14-0.23 MB/s on the phone after the session ends.

**Change.** `LogRedactor.redact` now runs each pattern only when the partly redacted line contains
something that pattern cannot match without, checked in the same order as before. The device's own
addresses and account names stay unguarded. On the PC, 27.4 MB of scrubbed Steam logs (295,784
lines) went from 11.9 s to 3.4 s (3.5x) with byte-identical output. `LogRedactorTest` (8) and the
new `LogRedactorGuardTest` (5) pass. `droiddeckctl stop` now waits for artifacts separately
(`--artifact-timeout`, default 180 s), and `logs` waits 180 s.

**Verification limits.** The CLI change was exercised on the phone: on the old app, collection still
outlasted 180 s (stop took 190 s), so the app-side speed-up is the fix that matters. It is built and
unit-tested but not installed, because the installed app's signing key is not available here.

### Session reliability defects found during sustained testing (October 8)

**Retry starts a paused session (fixed in source, not yet installed).** "Try again" and the agent
start finish the ended screen and open a new `SessionActivity`. Android stops the old activity after
the new one has started, so the old one's hidden report reached `SessionService` after the new one's
visible report, and the starting session was suspended ("Steam is paused" over "Starting Steam").
Reproduced twice (sessions 05 and 06). `VisibilityOwner` now lets only the screen shown last report
hidden; `VisibilityOwnerTest` (4) covers retry, rotation and release.

**Gamescope dies intermittently (open).** Sessions 04 and 05 ended with `GUEST_EXIT` status 1 and
`gamescopereaper: Parent of gamescopereaper was killed`. Session 04 died after ~6.75 min, at the end
of a 300 s scroll, with 490 `create_swapchain: Surface already had a gamescope_swapchain!` warnings
(session 03: 36). Session 05 died 10 s after READY with 8 warnings, right after Steam's usual Proton
`explorer.exe` created a surface; sessions 01-03 and 06 ran the same `explorer.exe` and survived.
Android's crash buffer was empty and no low-memory kill was logged. Next step: a Gamescope CI build
that reports its exit signal and the surface/swapchain owner on that warning.

**Agent start after a failed session does nothing (open).** With the phase FAILED, `droiddeckctl
start` launched `AgentStartActivity` (06:48, 06:49, 06:51) but logcat shows no `SessionActivity`
start and no error. The recovery latch it waits on was already released. Not reproduced since; the
on-screen "Try again" works.

**Sustained-run harness.** A single 300 s DevTools evaluation was closed by Steam ("devtools closed
the connection"); the benchmark rejected it. Sustained runs should use repeated 30 s segments.

**Unit tests.** 271 JVM tests on Windows: the same 28 fail on a clean worktree at 8605c30 and with
these changes (symlink privilege, POSIX permissions and similar host limits), so none are new.

### Current app deployment and recovery work (October 8)

The owner's debug key is available from the main account and matches the installed certificate
(`46ccacc7d0050caba9eb011614854dce4f54cda1184ea8a04cf460dfaad2c332`). The current app at
`93115c3` built successfully and installed as an update without uninstalling or clearing data.
Session 07 reached READY without a suspended start. Correct Steam pixels were inspected after
three valid corrected scroll samples: 54.8, 56.1 and 57.2 displayed FPS, p95 33.3 ms. Maximum
gaps were 117, 50 and 67 ms. These are short samples, not stable 60 or 120 FPS. The generated
release manifest excludes both agent control components; the bundled AndroidX profile installer
still has its own DUMP-protected receiver.

The last failure in session 06 is more specific than the reaper message: its session log ends
with `malloc(): smallbin double linked list corrupted`. The existing surface lifetime and
swapchain ownership patches therefore do not establish that all native heap defects are fixed.

AgentStartActivity handled only onCreate, although the earlier failed starts were delivered to
an existing top activity. It now handles onNewIntent too, and ignores recovery callbacks from
an older request or a destroyed activity. Four Robolectric lifecycle cases pass; a negative
control reproduces dropped retries and a destroyed activity launching a session.

The service removed foreground status while its independent log collector was still running.
Session 07's collection marker appeared roughly 44 minutes after stopping, around a later app
reopening. That correlation does not prove the historical process was frozen, but the lifecycle
allowed it. The service now retains foreground status until all its collections complete,
without allowing an old completion to stop a new running session or unfinished guest teardown.
Three foreground-service lifecycle regressions pass. The notification reports "Finishing
session logs" during this work. Build `1e4cc7c` installed without clearing data. Session 10
reached READY, stopped normally, and collected its artifacts about 46 seconds after guest
teardown without reopening the app. The foreground service was gone after collection.
This is one successful cycle, not sustained lifecycle verification.

Opt-in Mesa timings now distinguish throttle, internal submit, separate blit, final completion
fence, CPU cache invalidation and backend present. `PANVK_KBASE_PRESENT_TIMING=1` enables
per-thread batches of 240 presents; it is off by default and changes no synchronization. The
extracted-code regression checks forwarding, errors, errno, counters and zero disabled clock
calls, and its negative control fails as expected. Native CI run `37874841197` passed.
Its driver SHA-256 is `aa70f6243b5b1d8efdef4e304d264b17ddb58f1c8762e4bab2500ff986883958`;
the phone experiment uses a separate `pixel-panvk-present-timing` directory.

Session 11's first valid scroll sample measured 51.17 displayed FPS, p95 33.35 ms, maximum
141.64 ms; thermal status was 1, unlike the earlier status-0 samples. Initial batches of
240 presents put average final-fence wait at 6.8–8.1 ms and backend present at 1.6–2.3 ms.
Internal submit averaged only 6–9 microseconds. This directly contradicts the earlier
hypothesis that most present latency lived inside the internal submit: in this driver
and workload it lives primarily in the final fence wait. On the native DMA-BUF path
the wait protects the receiving process's GPU consumption; CPU fallback also needs
completion before readback. It cannot simply be removed. Timings establish attribution,
not a performance gain.

### Input release and control CLI follow-up (October 8)

`PadBridge.releaseAll()` previously cleared only the physical/touch pad state. Synthetic
Steam/QAM holds and delayed Guide–A chord callbacks remained active when the drawer,
keyboard or ended screen took input. It now clears all synthetic holds and increments
the callback generation, using the same reset as stop. Three Robolectric regressions
cover held buttons, a cancelled chord and an old tap callback interfering with a new tap.
All three fail with the old release method and pass with the fix. Build `0b56bef`
installed without clearing data; session 13 reached READY. Physical-controller and
on-device menu-transition verification remain open.

The CLI's artifact wait now rejects a replacement session instead of following its
state and either timing out or reporting the wrong session's collection as success.
Three Python regressions cover original completion, replacement and timeout.
Session 12 on the regular driver remained READY until an intentional stop roughly
26 minutes after READY and completed collection. Its final valid scroll sample was
50.82 displayed FPS, p95 33.35 ms, maximum 116.63 ms at thermal status 0. A successful
run of this length does not prove the intermittent native heap corruption is fixed.

### Asynchronous presentation prerequisites (October 8)

`take_dmabuf()` imports the native buffer through `vkp_image_from_dmabuf()`; it does
not turn that transport into a CPU copy. PanVK's kbase implementation explicitly
does not attach per-buffer GPU fences to exported BOs. Its final WSI wait currently
provides the producer/consumer ordering. The compositor's AHardwareBuffer layer path
has DMA-BUF sync-file handling, but that does not establish synchronization for the
ordinary Vulkan compositor path.

`tools/pixel-probe/dmabuf_sync_probe.py` ran in the phone's app-owned guest context.
The heap is read-only to apps, so it opens `/dev/dma_heap/system` with `O_RDONLY`,
then allocates a private 4 KiB buffer. Export, zero-time polling and re-import passed
for READ, WRITE and READ|WRITE fences. Every exported empty-work fence was signaled;
all descriptors are closed on success or error. This proves kernel ioctl support,
not GPU-job completion or an FPS improvement.

An implementation that publishes before GPU completion must export a fence tied
to all relevant submitted kbase queue targets, transfer it with the buffer, and
make the actual receiving Vulkan queue wait before sampling. Preserve the current
blocking path whenever fence creation/import fails, and keep buffer release tied
to consumer completion. Merely disabling `wait_present_before_queue` would
introduce an unsynchronized image race.

Further consumer-side inspection found `vk_present.c` already imports sync-file fences
into a temporary Vulkan semaphore for destination-buffer reuse. Its CPU fallback had
two defects: poll errors/error events were accepted as successful completion, and EINTR
restarted the full 100 ms timeout. It now requires POLLIN without error/hangup/invalid
events and uses one monotonic deadline across interruptions. The extracted actual
function passes signaled, timeout, poll-error, error-event and repeated-EINTR cases,
with descriptor closure checked; substituting the previous error policy fails. This
check is included in APK CI. Native Android compilation passes. This corrects fallback
synchronization and does not establish an FPS improvement or producer-fence export.

The AHardwareBuffer zero-copy fallback had the same false-success policy when
sync-file export failed. It now checks the borrowed DMA-BUF descriptor against a
single monotonic deadline, rejects invalid/error events, and presents only after
confirmed writer completion. The extracted helper and old-policy negative control
pass locally, and Android native compilation passes. Session 15 reached READY with
this fix in the APK labeled `046d5ba dirty`; its source was committed as `86f99de`.
This is startup verification, not proof of sustained performance improvement.
Later in the same session, a valid 15-second scroll sample measured 51.72 displayed
FPS, p95 33.34 ms and maximum 58.45 ms at thermal status 0, with the regular driver
and no environment override. Session 15 remained READY. The result remains below
stable 60 FPS and does not establish a gain from the fallback repair.

### KCPU fence cancellation constraint (October 8)

Read-only inspection of Google's GPU module at commit
[`5a8eb10d6878d2394555c14626cdf86293afbe56`](https://android.googlesource.com/kernel/google-modules/gpu/+/5a8eb10d6878d2394555c14626cdf86293afbe56)
found that successful KCPU queue deletion drains commands and synchronously
retires its workers, but skips unfinished CQS waits and executes ordinary
`FENCE_SIGNAL` without setting a cancellation error. Deleting an unfinished,
published producer request can therefore report successful completion prematurely.
The timeout path explicitly sets `-ETIMEDOUT`; poll readiness alone does not prove
successful GPU completion. BO retention does not resolve this signaling defect.

The inspected public branch is `android-gs-pantah-6.1-android15-qpr2`. The phone
reports kernel `6.1.157-android14-11-gbd23337e42e7-ab14791245`; an exact shipping
GPU-module source match is not established. No direct KCPU producer exporter was
implemented or enabled. Such a path needs an error-capable fence or a proven
termination/consumer-cancellation contract before destructive retirement.

An alternative under source review is to retain the real completion wait and
cache maintenance, but defer them and Wayland publication to a worker. This could
let the producer thread continue while publication still waits for completion.
Wayland currently has no such worker; acquisition, per-image fence reuse, copied
presentation data, asynchronous errors and destruction joins must be handled
before trying it. No performance benefit has been measured for that alternative.

`tools/pixel-probe/panvk-kcpu-fence-status.patch` is an isolated prerequisite,
not part of the production Mesa patch series. It checks sync-file status after
readiness so an errored fence takes the existing CSF notification fallback.
`check-kcpu-fence-status.py` compiles the extracted patched function: 15 local
cases pass and the pinned old-function negative control fails. The caller still
accepts only actual queue seqno completion, and KCPU synchronization remains
opt-in. Full Mesa compilation and device validation of this patch remain open.

### Native prebuilt freshness repair (October 8)

The local build previously checked only the separately replaced ARM64 runtime,
Gamescope and audio sources. Cached upstream x86/i386 runtime shims could silently
remain older than this checkout. The cached APK records upstream source revision
`b44235c495fa6458aa438c9ba3be06562e5d1a3c`; comparing its native input baseline
confirmed that this fork's x86 preloads were stale. Checkout scripts already stage
through Gradle and are excluded from the new native guard.

`pixel-runtime.yml` now also builds ARM64 fakeinput and x86/i386 preloads using
the existing Bullseye/glibc 2.31 build recipe. CI run `37880546577` passed, including
the timing and local-libdrm forwarding checks. Native artifact `11593949311` has
archive SHA-256 `150ac357e3a86afeb2455209304233a2d723891d20584cdc08df2104f6ea77a3`
and input digest `4df061aa716d7057af79dcdea0201454eeb6f1f05220a320a5d179c4922082f2`.
The source manifest and all output checksums were verified before pinning.

The local builder rejects changed cached native inputs before downloading or
staging, verifies upstream source provenance and the replacement source manifest,
and stages only the eight expected native outputs. Nine regression tests pass,
covering changed/added/deleted inputs, source metadata, replacement bytes and
ignored arbitrary archive paths. All eight rebuilt libraries match the packaged
APK. It installed without clearing data as `5f2ccb6 dirty`; session 16 reached
READY, and guest hashes of ARM64 fakeinput plus x86_64/i386 runtime libraries
match the verified artifact. The artifact pin is committed as `12030d4`.
Three valid regular-driver scroll samples in session 16 measured 53.58, 55.44
and 58.09 displayed FPS; p95 gaps were 33.35, 33.34 and 25.14 ms, with maxima
50.04, 50.02 and 50.02 ms. Thermal status was 0 in all three. This overlaps earlier
production variation and does not prove an FPS gain or stable 60 FPS. Private
raw measurements are retained under `build/bench/steam-scroll-rebuilt-native-session16-*.json`.

