package dev.pixeldeck.probe;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.os.Process;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.WindowManager;
import android.util.Log;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;

public final class NativeProbeActivity extends Activity implements SurfaceHolder.Callback {
    private boolean started;
    public static native String nativeTest(Surface surface, String frameReadyPath);
    public static native String nativeCompositorTest(Surface surface, String frameReadyPath);

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        SurfaceView view = new SurfaceView(this);
        view.getHolder().addCallback(this);
        setContentView(view);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        if (started) return;
        started = true;
        Surface surface = holder.getSurface();
        new Thread(() -> {
            JSONObject report = new JSONObject();
            try {
                report.put("model", Build.MODEL);
                report.put("android", Build.VERSION.RELEASE);
                report.put("uid", Process.myUid());
                System.loadLibrary("pixelprobe");
                String readyPath = new File(getFilesDir(), "frame-ready.txt").getPath();
                boolean compositor = getIntent().getBooleanExtra("compositor", false);
                String result = compositor ? nativeCompositorTest(surface, readyPath) : nativeTest(surface, readyPath);
                for (String line : result.split("\n")) {
                    int eq = line.indexOf('=');
                    if (eq > 0) report.put(line.substring(0, eq), line.substring(eq + 1));
                }
                boolean ok = compositor ? "pass".equals(report.optString("compositor_present"))
                    && "pass".equals(report.optString("compositor_readback"))
                    : "pass".equals(report.optString("vulkan_present")) && "pass".equals(report.optString("ahb_readback"));
                report.put("status", ok ? "complete" : "failed");
            } catch (Throwable e) {
                try { report.put("error", e.toString()); report.put("status", "failed"); }
                catch (Exception ignored) { }
            }
            try {
                String text = report.toString(2);
                Files.write(new File(getFilesDir(), "report-native.json").toPath(), text.getBytes(StandardCharsets.UTF_8));
                for (String line : text.split("\n")) Log.i("PixelDeckProbe", line);
            } catch (Exception e) { Log.e("PixelDeckProbe", "Could not save native report", e); }
        }, "PixelDeck-Vulkan-probe").start();
    }

    @Override public void surfaceChanged(SurfaceHolder h, int format, int width, int height) { }
    @Override public void surfaceDestroyed(SurfaceHolder h) { }
}
