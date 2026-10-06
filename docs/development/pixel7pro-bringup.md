# Pixel 7 Pro: first checks, 2026-10-06

Status: read-only ADB preflight completed. Diagnostic APK built and signature
verified, but Android rejected installation with `INSTALL_FAILED_VERIFICATION_FAILURE`.
No app-UID graphics result, Linux rendering, Steam launch, or game compatibility
has been established. The phone was dozing during the install attempts; whether
that contributed to the verdict is unknown. A versioned APK signed with a unique
local debug key received the same verdict as the original public-test-key build.

## Observed device and stock driver

- Pixel 7 Pro (`cheetah`), Android 17, build `CP2A.260705.006`.
- Kernel `6.1.157-android14-11-gbd23337e42e7-ab14791245`.
- `ro.boot.flash.locked=1`; no `su` executable found on the shell PATH.
- `cmd gpu vkjson`: Mali-G710, Vulkan **1.4.343**.
- Geometry and tessellation shaders supported; BC texture compression unsupported.
- `cmd gpu vkprofiles`: Android Vulkan profile 2025 and Android 17 requirements supported.

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
The app-UID query remains necessary.

## Device nodes

`/dev/mali0` has mode `0666`. `/dev/dma_heap/system` and
`/dev/dma_heap/system-uncached` have mode `0444`. The ADB shell successfully
opened the system heap read-only; allocation and app SELinux access are untested.
Do not infer an unusable heap from the absence of write permissions alone.

The experimental PanVK-kbase source currently opens its selected DMA heap with
`O_RDWR`. A read-only heap open may be a small adaptation worth investigating,
but no driver patch or allocation test has been made:

https://github.com/funnymdzz/mesa/blob/main/src/panfrost/lib/kmod/kbase_kmod.c

## Next steps

1. Resolve the phone's explicit installation approval/verification issue while
   retaining Android's verifier. Keep the phone unlocked during the app test.
2. Run `python tools/pixel-probe/probe.py --no-build --serial DEVICE_SERIAL`.
3. Confirm app-UID Vulkan enumeration and stock GLES clear/readback.
4. Test actual compositor buffer allocation/import using the stock Android driver.
5. Choose and test the Linux-side Vulkan implementation separately. A working
   Android compositor does not provide a glibc Vulkan driver for the runtime.

Local raw results are under `build/pixel-probe/` and are intentionally not
committed; keep device serials and screenshots out of the public repository.
