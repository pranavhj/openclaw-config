package com.example.APPSLUG.testing;

import android.app.Activity;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.view.View;

import java.io.ByteArrayOutputStream;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Captures the current screen as a PNG byte array.
 * Uses View.draw() which works without root or special permissions.
 */
public class ScreenshotHelper {

    private static final long TIMEOUT_MS = 10000;

    /**
     * Capture the current activity's root view as a PNG.
     * Must be called from a background thread — internally posts to UI thread.
     *
     * @return PNG bytes, or null on failure
     */
    public static byte[] capture(Activity activity) {
        if (activity == null) return null;

        final AtomicReference<byte[]> result = new AtomicReference<>();
        final CountDownLatch latch = new CountDownLatch(1);

        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    View root = activity.getWindow().getDecorView().getRootView();
                    Bitmap bitmap = Bitmap.createBitmap(
                            root.getWidth(), root.getHeight(), Bitmap.Config.ARGB_8888);
                    Canvas canvas = new Canvas(bitmap);
                    root.draw(canvas);

                    ByteArrayOutputStream stream = new ByteArrayOutputStream();
                    bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream);
                    bitmap.recycle();

                    result.set(stream.toByteArray());
                } catch (Exception e) {
                    result.set(null);
                } finally {
                    latch.countDown();
                }
            }
        });

        try {
            if (!latch.await(TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
                return null;
            }
        } catch (InterruptedException e) {
            return null;
        }

        return result.get();
    }
}
