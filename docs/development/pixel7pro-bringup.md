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

The first failed session was also killed by Android's phantom-process monitor
while updating Steam. Raising the cap temporarily separated that failure from
the graphics issue. After restoring the original unset cap, a fresh Big Picture
session reached `READY` again, but Android subsequently killed its proot tracer
while trimming phantom processes. The default process cap is therefore not a
stable Steam setup. It has been restored; no process-monitor bypass is left on.
The app now applies the tested SDL/PanVK/software-OpenGL defaults when an
explicit PanVK import is selected; private environment overrides are unnecessary.
These defaults apply to all OpenGL child applications, including OpenGL games
and WineD3D. Vulkan applications still use PanVK. This is an experimental
working fallback, not hardware-accelerated OpenGL support for Steam.

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

## Remaining steps

1. Verify the cube visibly after the Android compatibility dialog is dismissed.
2. Run a real Vulkan game; Steam login and Proton/Windows games remain untested.
3. Fix Steam's Zink UI context and rebuild the audio prebuilts with 16 KB alignment.
4. Improve the current SHM presentation to dma-buf sharing and measure performance.

Repeat the current baseline with
`python tools/pixel-probe/probe.py --no-build --no-install --native --serial DEVICE_SERIAL` while the
phone is unlocked. The runner captures a report, screenshot and filtered log,
then stops its test activity. The installed diagnostic app remains available.

Local raw results are under `build/pixel-probe/` and are intentionally not
committed; keep device serials and screenshots out of the public repository.
