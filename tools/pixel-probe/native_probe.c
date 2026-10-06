/* Ordinary app-UID stock Vulkan / gralloc test. No private Mali ioctls. */
#define VK_USE_PLATFORM_ANDROID_KHR
#include <vulkan/vulkan.h>
#include <jni.h>
#include <android/native_window_jni.h>
#include <android/hardware_buffer.h>
#include <linux/dma-heap.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>

#define LINE(...) do { if (used < sizeof(out)) { int n = snprintf(out + used, sizeof(out) - used, __VA_ARGS__); if (n > 0) used += (size_t)n; } } while (0)
#define CHECK(call) do { VkResult r = (call); if (r != VK_SUCCESS) { LINE("error=%s: %d\n", #call, r); goto done; } } while (0)

JNIEXPORT jstring JNICALL
Java_dev_pixeldeck_probe_NativeProbeActivity_nativeTest(JNIEnv *env, jclass cls, jobject surface, jstring frame_path) {
    char out[8192] = {0};
    size_t used = 0;
    const char *heaps[] = {"/dev/dma_heap/system", "/dev/dma_heap/system-uncached"};
    for (size_t i = 0; i < 2; ++i) {
        int heap = open(heaps[i], O_RDONLY | O_CLOEXEC);
        if (heap < 0) { LINE("heap.%s=open failed: %s\n", heaps[i], strerror(errno)); continue; }
        struct dma_heap_allocation_data a = {.len = 4096, .fd_flags = O_RDWR | O_CLOEXEC};
        if (ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &a) < 0) {
            LINE("heap.%s=allocate failed: %s\n", heaps[i], strerror(errno));
        } else {
            /* Allocation is the permission question; don't CPU-map uncached memory unnecessarily. */
            LINE("heap.%s=allocate pass (4096 bytes, read-only heap fd)\n", heaps[i]);
            close((int)a.fd);
        }
        close(heap);
    }

    ANativeWindow *window = ANativeWindow_fromSurface(env, surface);
    VkInstance instance = VK_NULL_HANDLE;
    VkSurfaceKHR surf = VK_NULL_HANDLE;
    VkDevice dev = VK_NULL_HANDLE;
    VkSwapchainKHR swap = VK_NULL_HANDLE;
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkSemaphore acquired = VK_NULL_HANDLE, rendered = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    AHardwareBuffer *ahb = NULL;
    VkImage *swap_images = NULL;
    int submitted = 0;
    if (!window) { LINE("error=no Android window\n"); goto done; }
    const char *instance_exts[] = {VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_ANDROID_SURFACE_EXTENSION_NAME};
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "PixelDeck probe", .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &app,
        .enabledExtensionCount = 2, .ppEnabledExtensionNames = instance_exts};
    CHECK(vkCreateInstance(&ici, NULL, &instance));
    VkAndroidSurfaceCreateInfoKHR sci = {.sType = VK_STRUCTURE_TYPE_ANDROID_SURFACE_CREATE_INFO_KHR, .window = window};
    CHECK(vkCreateAndroidSurfaceKHR(instance, &sci, NULL, &surf));
    uint32_t count = 1;
    VkPhysicalDevice gpu;
    VkResult listed = vkEnumeratePhysicalDevices(instance, &count, &gpu);
    if (!count || (listed != VK_SUCCESS && listed != VK_INCOMPLETE)) { LINE("error=no GPU\n"); goto done; }
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(gpu, &properties);
    LINE("device=%s\n", properties.deviceName);
    uint32_t nex = 0;
    CHECK(vkEnumerateDeviceExtensionProperties(gpu, NULL, &nex, NULL));
    if (nex > 512) { LINE("error=too many extensions\n"); goto done; }
    VkExtensionProperties exts[512];
    CHECK(vkEnumerateDeviceExtensionProperties(gpu, NULL, &nex, exts));
    const char *required[] = {VK_KHR_SWAPCHAIN_EXTENSION_NAME, VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
        VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME, VK_EXT_IMAGE_DRM_FORMAT_MODIFIER_EXTENSION_NAME,
        VK_KHR_IMAGE_FORMAT_LIST_EXTENSION_NAME, VK_ANDROID_EXTERNAL_MEMORY_ANDROID_HARDWARE_BUFFER_EXTENSION_NAME,
        VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME};
    for (size_t e = 0; e < sizeof(required) / sizeof(*required); e++) {
        int found = 0;
        for (uint32_t j = 0; j < nex; j++) if (!strcmp(required[e], exts[j].extensionName)) found = 1;
        LINE("ext.%s=%s\n", required[e], found ? "yes" : "no");
        if (!found) { LINE("error=missing extension %s\n", required[e]); goto done; }
    }
    uint32_t nq = 0, family = UINT32_MAX;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &nq, NULL);
    if (nq > 32) { LINE("error=too many queues\n"); goto done; }
    VkQueueFamilyProperties queues[32];
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &nq, queues);
    for (uint32_t j = 0; j < nq; j++) {
        VkBool32 present = 0;
        CHECK(vkGetPhysicalDeviceSurfaceSupportKHR(gpu, j, surf, &present));
        if (present && (queues[j].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { family = j; break; }
    }
    if (family == UINT32_MAX) { LINE("error=no graphics/present queue\n"); goto done; }
    float priority = 1;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = family,
        .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci,
        .enabledExtensionCount = sizeof(required) / sizeof(*required), .ppEnabledExtensionNames = required};
    CHECK(vkCreateDevice(gpu, &dci, NULL, &dev));
    VkQueue queue;
    vkGetDeviceQueue(dev, family, 0, &queue);
    VkSurfaceCapabilitiesKHR caps;
    CHECK(vkGetPhysicalDeviceSurfaceCapabilitiesKHR(gpu, surf, &caps));
    if (!(caps.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT)) { LINE("error=swapchain cannot receive transfer\n"); goto done; }
    uint32_t nf = 0;
    CHECK(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu, surf, &nf, NULL));
    if (!nf || nf > 128) { LINE("error=invalid surface format count\n"); goto done; }
    VkSurfaceFormatKHR formats[128];
    CHECK(vkGetPhysicalDeviceSurfaceFormatsKHR(gpu, surf, &nf, formats));
    VkSurfaceFormatKHR format = formats[0];
    for (uint32_t j = 0; j < nf; j++) if (formats[j].format == VK_FORMAT_R8G8B8A8_UNORM) { format = formats[j]; break; }
    VkExtent2D extent = caps.currentExtent;
    if (extent.width == UINT32_MAX) {
        extent.width = (uint32_t)ANativeWindow_getWidth(window);
        extent.height = (uint32_t)ANativeWindow_getHeight(window);
        if (extent.width < caps.minImageExtent.width) extent.width = caps.minImageExtent.width;
        if (extent.width > caps.maxImageExtent.width) extent.width = caps.maxImageExtent.width;
        if (extent.height < caps.minImageExtent.height) extent.height = caps.minImageExtent.height;
        if (extent.height > caps.maxImageExtent.height) extent.height = caps.maxImageExtent.height;
    }
    uint32_t images = caps.minImageCount + 1;
    if (caps.maxImageCount && images > caps.maxImageCount) images = caps.maxImageCount;
    VkCompositeAlphaFlagBitsKHR alpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    if (!(caps.supportedCompositeAlpha & alpha)) alpha = (VkCompositeAlphaFlagBitsKHR)(caps.supportedCompositeAlpha & -caps.supportedCompositeAlpha);
    VkSwapchainCreateInfoKHR swapci = {.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR, .surface = surf,
        .minImageCount = images, .imageFormat = format.format, .imageColorSpace = format.colorSpace, .imageExtent = extent,
        .imageArrayLayers = 1, .imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT, .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .preTransform = caps.currentTransform, .compositeAlpha = alpha, .presentMode = VK_PRESENT_MODE_FIFO_KHR, .clipped = VK_TRUE};
    CHECK(vkCreateSwapchainKHR(dev, &swapci, NULL, &swap));
    CHECK(vkGetSwapchainImagesKHR(dev, swap, &images, NULL));
    swap_images = calloc(images, sizeof(*swap_images));
    if (!swap_images) { LINE("error=out of memory\n"); goto done; }
    CHECK(vkGetSwapchainImagesKHR(dev, swap, &images, swap_images));

    AHardwareBuffer_Desc desc = {.width = 64, .height = 64, .layers = 1, .format = AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM,
        .usage = AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE | AHARDWAREBUFFER_USAGE_GPU_COLOR_OUTPUT | AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN};
    int ar = AHardwareBuffer_allocate(&desc, &ahb);
    if (ar) { LINE("error=AHardwareBuffer_allocate: %d\n", ar); goto done; }
    PFN_vkGetAndroidHardwareBufferPropertiesANDROID get_ahb = (PFN_vkGetAndroidHardwareBufferPropertiesANDROID)vkGetDeviceProcAddr(dev, "vkGetAndroidHardwareBufferPropertiesANDROID");
    if (!get_ahb) { LINE("error=no AHB property function\n"); goto done; }
    VkAndroidHardwareBufferFormatPropertiesANDROID fp = {.sType = VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_FORMAT_PROPERTIES_ANDROID};
    VkAndroidHardwareBufferPropertiesANDROID hp = {.sType = VK_STRUCTURE_TYPE_ANDROID_HARDWARE_BUFFER_PROPERTIES_ANDROID, .pNext = &fp};
    CHECK(get_ahb(dev, ahb, &hp));
    LINE("ahb_format=%d\nahb_format_features=0x%x\n", fp.format, fp.formatFeatures);
    if (fp.format != VK_FORMAT_R8G8B8A8_UNORM || !(fp.formatFeatures & VK_FORMAT_FEATURE_BLIT_SRC_BIT)) {
        LINE("error=AHB RGBA blit unsupported\n"); goto done;
    }
    VkExternalMemoryImageCreateInfo external = {.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO,
        .handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_ANDROID_HARDWARE_BUFFER_BIT_ANDROID};
    VkImageCreateInfo imci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .pNext = &external, .imageType = VK_IMAGE_TYPE_2D,
        .format = fp.format, .extent = {64, 64, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
        VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    CHECK(vkCreateImage(dev, &imci, NULL, &image));
    uint32_t mt = 0;
    while (mt < 32 && !(hp.memoryTypeBits & (1u << mt))) mt++;
    if (mt == 32) { LINE("error=no AHB memory type\n"); goto done; }
    VkImportAndroidHardwareBufferInfoANDROID import = {.sType = VK_STRUCTURE_TYPE_IMPORT_ANDROID_HARDWARE_BUFFER_INFO_ANDROID, .buffer = ahb};
    VkMemoryDedicatedAllocateInfo dedicated = {.sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO, .pNext = &import, .image = image};
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .pNext = &dedicated,
        .allocationSize = hp.allocationSize, .memoryTypeIndex = mt};
    CHECK(vkAllocateMemory(dev, &ai, NULL, &memory));
    CHECK(vkBindImageMemory(dev, image, memory, 0));
    LINE("ahb_import=pass\n");
    VkCommandPoolCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
    CHECK(vkCreateCommandPool(dev, &pci, NULL, &pool));
    VkCommandBufferAllocateInfo cai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = pool,
        .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer cmd;
    CHECK(vkAllocateCommandBuffers(dev, &cai, &cmd));
    VkSemaphoreCreateInfo semci = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
    CHECK(vkCreateSemaphore(dev, &semci, NULL, &acquired));
    CHECK(vkCreateSemaphore(dev, &semci, NULL, &rendered));
    VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    CHECK(vkCreateFence(dev, &fci, NULL, &fence));
    uint32_t index;
    CHECK(vkAcquireNextImageKHR(dev, swap, 5000000000ULL, acquired, VK_NULL_HANDLE, &index));
    VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    CHECK(vkBeginCommandBuffer(cmd, &bi));
    VkImageSubresourceRange range = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .levelCount = 1, .layerCount = 1};
    VkImageMemoryBarrier barriers[2] = {
        {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
         .srcQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT, .dstQueueFamilyIndex = family,
         .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .image = image, .subresourceRange = range},
        {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
         .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
         .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .image = swap_images[index], .subresourceRange = range}};
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 2, barriers);
    VkClearColorValue magenta = {.float32 = {1, 0, 1, 1}};
    vkCmdClearColorImage(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &magenta, 1, &range);
    barriers[0].oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barriers[0].newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barriers[0].srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barriers[0].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    barriers[0].srcQueueFamilyIndex = barriers[0].dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, barriers);
    VkImageBlit blit = {.srcSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .srcOffsets = {{0, 0, 0}, {64, 64, 1}}, .dstSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1},
        .dstOffsets = {{0, 0, 0}, {(int32_t)extent.width, (int32_t)extent.height, 1}}};
    vkCmdBlitImage(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, swap_images[index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &blit, VK_FILTER_NEAREST);
    barriers[0].oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    barriers[0].newLayout = VK_IMAGE_LAYOUT_GENERAL;
    barriers[0].srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    barriers[0].dstAccessMask = 0;
    barriers[0].srcQueueFamilyIndex = family;
    barriers[0].dstQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT;
    barriers[1].oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barriers[1].newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    barriers[1].srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barriers[1].dstAccessMask = 0;
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, NULL, 0, NULL, 2, barriers);
    CHECK(vkEndCommandBuffer(cmd));
    VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .waitSemaphoreCount = 1, .pWaitSemaphores = &acquired,
        .pWaitDstStageMask = &wait_stage, .commandBufferCount = 1, .pCommandBuffers = &cmd, .signalSemaphoreCount = 1, .pSignalSemaphores = &rendered};
    CHECK(vkQueueSubmit(queue, 1, &submit, fence));
    submitted = 1;
    CHECK(vkWaitForFences(dev, 1, &fence, VK_TRUE, 5000000000ULL));
    VkPresentInfoKHR present = {.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR, .waitSemaphoreCount = 1, .pWaitSemaphores = &rendered,
        .swapchainCount = 1, .pSwapchains = &swap, .pImageIndices = &index};
    CHECK(vkQueuePresentKHR(queue, &present));
    CHECK(vkQueueWaitIdle(queue));
    LINE("vulkan_present=pass\n");
    void *pixels = NULL;
    ar = AHardwareBuffer_lock(ahb, AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN, -1, NULL, &pixels);
    if (ar || !pixels) { LINE("error=AHardwareBuffer_lock: %d\n", ar); goto done; }
    AHardwareBuffer_describe(ahb, &desc);
    unsigned char *rgba = (unsigned char *)pixels + (32 * desc.stride + 32) * 4;
    LINE("ahb_center_rgba=%u,%u,%u,%u\n", rgba[0], rgba[1], rgba[2], rgba[3]);
    LINE("ahb_readback=%s\n", rgba[0] == 255 && rgba[1] == 0 && rgba[2] == 255 && rgba[3] == 255 ? "pass" : "fail");
    AHardwareBuffer_unlock(ahb, NULL);
    /* Host captures while the live swapchain still owns its displayed frame. */
    const char *path = (*env)->GetStringUTFChars(env, frame_path, NULL);
    if (path) {
        FILE *ready = fopen(path, "w");
        if (ready) { fputs(out, ready); fclose(ready); }
        (*env)->ReleaseStringUTFChars(env, frame_path, path);
    }
    usleep(3000000);
done:
    if (dev) {
        if (submitted) vkDeviceWaitIdle(dev);
        if (fence) vkDestroyFence(dev, fence, NULL);
        if (rendered) vkDestroySemaphore(dev, rendered, NULL);
        if (acquired) vkDestroySemaphore(dev, acquired, NULL);
        if (pool) vkDestroyCommandPool(dev, pool, NULL);
        if (image) vkDestroyImage(dev, image, NULL);
        if (memory) vkFreeMemory(dev, memory, NULL);
        if (swap) vkDestroySwapchainKHR(dev, swap, NULL);
        vkDestroyDevice(dev, NULL);
    }
    if (ahb) AHardwareBuffer_release(ahb);
    free(swap_images);
    if (surf) vkDestroySurfaceKHR(instance, surf, NULL);
    if (instance) vkDestroyInstance(instance, NULL);
    if (window) ANativeWindow_release(window);
    return (*env)->NewStringUTF(env, out);
}

/* Exercise the actual built compositor backend, in isolation from its Wayland thread.
 * dlopen deliberately skips JNI_OnLoad: callbacks have no Java listener in this test. */
JNIEXPORT jstring JNICALL
Java_dev_pixeldeck_probe_NativeProbeActivity_nativeCompositorTest(JNIEnv *env, jclass cls, jobject surface, jstring frame_path) {
    char out[8192] = {0};
    size_t used = 0;
    void *lib = dlopen("libdroiddeckwayland.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib) { LINE("error=compositor dlopen: %s\n", dlerror()); return (*env)->NewStringUTF(env, out); }
    struct vkp_image;
    struct draw { struct vkp_image *img; float sx, sy, sw, sh; int dx, dy, dw, dh, blend; };
#define LOAD(ret, name, args) ret (*name) args = (ret (*) args)dlsym(lib, #name); \
    if (!name) { LINE("error=missing compositor function %s\n", #name); goto end; }
    LOAD(void, vk_present_set_driver, (const char *, const char *, const char *));
    LOAD(void, vk_present_set_window, (ANativeWindow *));
    LOAD(int, vkp_apply_window_request, (void));
    LOAD(int, vkp_ready, (void));
    LOAD(const char *, vkp_gpu_name, (void));
    LOAD(struct vkp_image *, vkp_image_create_shm, (int, int));
    LOAD(void, vkp_image_upload_shm, (struct vkp_image *, const void *, int));
    LOAD(int, vkp_image_readback, (struct vkp_image *, uint32_t *, int));
    LOAD(int, vkp_render, (int, int, const struct draw *, int));
    LOAD(void, vkp_image_destroy, (struct vkp_image *));
    LOAD(int, vkp_dmabuf_modifiers, (uint32_t, uint64_t *, int));
    LOAD(struct vkp_image *, vkp_image_from_dmabuf, (int, uint32_t, uint64_t, int, int, uint32_t, uint32_t));
    vk_present_set_driver(NULL, NULL, NULL);
    vk_present_set_window(ANativeWindow_fromSurface(env, surface));
    vkp_apply_window_request();
    if (vkp_ready()) { LINE("error=compositor device initialization failed\n"); goto detach; }
    LINE("device=%s\n", vkp_gpu_name());
    struct vkp_image *image = vkp_image_create_shm(64, 64);
    if (!image) { LINE("error=compositor shm image failed\n"); goto detach; }
    uint32_t pixels[64 * 64], readback[64 * 64];
    for (size_t i = 0; i < 64 * 64; i++) pixels[i] = 0xff00ffff; /* cyan, BGRA */
    vkp_image_upload_shm(image, pixels, 64 * 4);
    struct draw d = {.img = image, .sw = 64, .sh = 64, .dw = 64, .dh = 64};
    int r = vkp_render(64, 64, &d, 1);
    LINE("compositor_present=%s\n", r == 0 ? "pass" : "fail");
    r = vkp_image_readback(image, readback, 64 * 64);
    int matched = r == 0;
    if (matched) for (size_t i = 0; i < 64 * 64; i++) if (pixels[i] != readback[i]) { matched = 0; break; }
    LINE("compositor_readback=%s\n", matched ? "pass" : "fail");
    LINE("compositor_center_bgra=0x%08x\n", r == 0 ? readback[32 * 64 + 32] : 0);
    vkp_image_destroy(image);
    uint32_t fourcc = 0x34325241; /* DRM_FORMAT_ARGB8888 */
    uint64_t mods[32];
    int nm = vkp_dmabuf_modifiers(fourcc, mods, 32);
    LINE("compositor_argb_modifier_count=%d\n", nm);
    int linear = 0;
    for (int j = 0; j < nm && j < 32; j++) { LINE("compositor_modifier.%d=0x%llx\n", j, (unsigned long long)mods[j]); if (mods[j] == 0) linear = 1; }
    /* The compositor's exact importer, from an ordinary linear system heap allocation. */
    if (linear) {
        int h = open("/dev/dma_heap/system", O_RDONLY | O_CLOEXEC);
        struct dma_heap_allocation_data a = {.len = 65536, .fd_flags = O_RDWR | O_CLOEXEC};
        if (h >= 0 && ioctl(h, DMA_HEAP_IOCTL_ALLOC, &a) == 0) {
            struct vkp_image *imported = vkp_image_from_dmabuf((int)a.fd, fourcc, 0, 64, 64, 256, 0);
            LINE("compositor_linear_dmabuf_import=%s\n", imported ? "pass" : "fail");
            if (imported) vkp_image_destroy(imported);
            close((int)a.fd);
        } else { LINE("compositor_linear_dmabuf_import=heap allocation failed: %s\n", strerror(errno)); }
        if (h >= 0) close(h);
    } else { LINE("compositor_linear_dmabuf_import=not advertised\n"); }
    const char *path = (*env)->GetStringUTFChars(env, frame_path, NULL);
    if (path) {
        FILE *ready = fopen(path, "w");
        if (ready) { fputs(out, ready); fclose(ready); }
        (*env)->ReleaseStringUTFChars(env, frame_path, path);
    }
    usleep(3000000);
detach:
    vk_present_set_window(NULL);
    vkp_apply_window_request();
end:
    /* Backend globals live until process exit; do not dlclose underneath them. */
    return (*env)->NewStringUTF(env, out);
}
