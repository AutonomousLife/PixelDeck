package com.droiddeck.launcher.gpu;

/** JNI name deliberately matches upstream's unmodified libdeviceinfo.so. */
public final class VulkanInfo {
    public static native String nativeQuery();
}
