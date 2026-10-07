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
