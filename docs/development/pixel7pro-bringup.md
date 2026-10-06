# Pixel 7 Pro: first checks, 2026-10-06

Status: **diagnostic APK installed and app-UID probe passed** on a subsequent retry
with the phone awake. Earlier attempts received `INSTALL_FAILED_VERIFICATION_FAILURE`;
the exact reason for rejection and subsequent acceptance remains unknown.
Android verification stayed enabled. Linux rendering, Steam launch, and game
compatibility have not been established.

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
pixel readback with no GL error, at 1080x2169. This is a GLES rendering test and
Vulkan enumeration test; it does not prove a Vulkan render or buffer import.

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
The reused JNI query does not enumerate these sharing extensions individually;
their table above comes from the system GPU-service query. App-UID buffer-sharing
tests remain necessary.

## Device nodes

`/dev/mali0` has mode `0666`; the debug app successfully opened it read/write.
`/dev/dma_heap/system` and `/dev/dma_heap/system-uncached` have mode `0444`.
The debug app successfully opened both heaps read-only, while read/write opens
failed with `EACCES`. Heap allocation and Mali context creation are untested.
Do not infer an unusable heap from the absence of write permissions alone.

The experimental PanVK-kbase source currently opens its selected DMA heap with
`O_RDWR`. A read-only heap open may be a small adaptation worth investigating,
but no driver patch or allocation test has been made:

https://github.com/funnymdzz/mesa/blob/main/src/panfrost/lib/kmod/kbase_kmod.c

## Next steps

1. Test actual compositor buffer allocation/import using the stock Android driver.
2. Confirm DMA-heap allocation through a read-only FD before changing PanVK's heap
   open mode; the current `O_RDWR` open would be denied for this debug app.
3. Choose and test the Linux-side Vulkan implementation separately. A working
   Android compositor does not provide a glibc Vulkan driver for the runtime.

Repeat the current baseline with
`python tools/pixel-probe/probe.py --no-build --serial DEVICE_SERIAL` while the
phone is unlocked. The runner captures a report, screenshot and filtered log,
then stops its test activity. The installed diagnostic app remains available.

Local raw results are under `build/pixel-probe/` and are intentionally not
committed; keep device serials and screenshots out of the public repository.
