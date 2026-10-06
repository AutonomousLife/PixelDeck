package dev.pixeldeck.probe;

import android.app.Activity;
import android.opengl.GLES20;
import android.opengl.GLSurfaceView;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.system.Os;
import android.system.OsConstants;
import android.util.Log;
import com.droiddeck.launcher.gpu.VulkanInfo;
import java.io.File;
import java.io.FileDescriptor;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import javax.microedition.khronos.egl.EGLConfig;
import javax.microedition.khronos.opengles.GL10;
import org.json.JSONObject;

/** Tests the app UID, not adb shell/root. No custom driver or kernel ioctls. */
public final class ProbeActivity extends Activity implements GLSurfaceView.Renderer {
    private final JSONObject report = new JSONObject();
    private GLSurfaceView surface;
    private int width, height;
    private boolean captured;

    private void put(String key, Object value) {
        try { report.put(key, value); } catch (Exception e) { throw new RuntimeException(e); }
    }

    private void checkOpen(String path) {
        try {
            FileDescriptor fd = Os.open(path, OsConstants.O_RDWR | OsConstants.O_CLOEXEC, 0);
            Os.close(fd);
            put("open." + path, "ok (open only; driver context and allocation untested)");
        } catch (Exception e) { put("open." + path, e.toString()); }
    }

    private void save() {
        try {
            String text = report.toString(2);
            Files.write(new File(getFilesDir(), "report.json").toPath(), text.getBytes(StandardCharsets.UTF_8));
            for (String line : text.split("\n")) Log.i("PixelDeckProbe", line);
        } catch (Exception e) { Log.e("PixelDeckProbe", "Could not save report", e); }
    }

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        put("model", Build.MODEL);
        put("android", Build.VERSION.RELEASE);
        put("sdk", Build.VERSION.SDK_INT);
        put("fingerprint", Build.FINGERPRINT);
        put("uid", Process.myUid());
        put("target_sdk", getApplicationInfo().targetSdkVersion);
        put("debuggable", true);
        checkOpen("/dev/mali0");
        checkOpen("/dev/dma_heap/system");
        checkOpen("/dev/dma_heap/system-uncached");
        save();
        surface = new GLSurfaceView(this);
        surface.setEGLContextClientVersion(2);
        surface.setRenderer(this);
        surface.setRenderMode(GLSurfaceView.RENDERMODE_WHEN_DIRTY);
        setContentView(surface);
    }

    @Override public void onSurfaceCreated(GL10 unused, EGLConfig config) {
        put("gles_vendor", GLES20.glGetString(GLES20.GL_VENDOR));
        put("gles_renderer", GLES20.glGetString(GLES20.GL_RENDERER));
        put("gles_version", GLES20.glGetString(GLES20.GL_VERSION));
        try {
            System.loadLibrary("deviceinfo");
            String text = VulkanInfo.nativeQuery();
            JSONObject vk = new JSONObject();
            for (String line : text.split("\n")) {
                int eq = line.indexOf('=');
                if (eq > 0) vk.put(line.substring(0, eq), line.substring(eq + 1));
            }
            put("vulkan", vk);
        } catch (Throwable e) { put("vulkan_error", e.toString()); }
        save();
    }

    @Override public void onSurfaceChanged(GL10 unused, int w, int h) {
        width = w; height = h;
        GLES20.glViewport(0, 0, w, h);
        captured = false;
    }

    @Override public void onDrawFrame(GL10 unused) {
        GLES20.glDisable(GLES20.GL_SCISSOR_TEST);
        GLES20.glClearColor(0f, 1f, 0f, 1f);
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT);
        if (!captured && width > 0 && height > 0) {
            ByteBuffer pixel = ByteBuffer.allocateDirect(4);
            GLES20.glReadPixels(width / 2, height / 2, 1, 1, GLES20.GL_RGBA, GLES20.GL_UNSIGNED_BYTE, pixel);
            int error = GLES20.glGetError();
            boolean ok = error == GLES20.GL_NO_ERROR && (pixel.get(0) & 255) < 5
                && (pixel.get(1) & 255) > 250 && (pixel.get(2) & 255) < 5;
            put("gles_clear_readback", ok ? "pass" : "fail");
            put("gles_error", error);
            put("surface_size", width + "x" + height);
            put("status", ok && report.has("vulkan") ? "complete" : "failed");
            save();
            captured = true;
        }
    }

    @Override public void onPause() { surface.onPause(); super.onPause(); }
    @Override public void onResume() { super.onResume(); surface.onResume(); }
}
