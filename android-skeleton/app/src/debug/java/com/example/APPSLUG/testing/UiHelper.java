package com.example.APPSLUG.testing;

import android.app.Activity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Utility for running code on the UI thread synchronously from a worker thread,
 * and inspecting the view hierarchy.
 * Pre-bound as 'ui' in the script interpreter.
 */
public class UiHelper {

    private static final long UI_TIMEOUT_MS = 10000;

    /** Sleep for the given milliseconds. Convenience for scripts. */
    public void sleep(long ms) throws InterruptedException {
        Thread.sleep(ms);
    }

    /**
     * Run a Runnable on the UI thread and wait for completion.
     * Throws RuntimeException if the runnable throws or times out.
     */
    public static void runOnUiThreadSync(Activity activity, final Runnable runnable) {
        if (activity == null) throw new RuntimeException("No active activity");

        final CountDownLatch latch = new CountDownLatch(1);
        final AtomicReference<Throwable> error = new AtomicReference<>();

        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    runnable.run();
                } catch (Throwable t) {
                    error.set(t);
                } finally {
                    latch.countDown();
                }
            }
        });

        try {
            if (!latch.await(UI_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
                throw new RuntimeException("UI thread operation timed out after " + UI_TIMEOUT_MS + "ms");
            }
        } catch (InterruptedException e) {
            throw new RuntimeException("Interrupted waiting for UI thread", e);
        }

        Throwable t = error.get();
        if (t != null) {
            if (t instanceof RuntimeException) throw (RuntimeException) t;
            throw new RuntimeException("UI thread error", t);
        }
    }

    /**
     * Get a JSON summary of the view tree for the current activity.
     * Runs on the UI thread to safely access views.
     */
    public static JSONArray getViewTree(Activity activity) throws Exception {
        final JSONArray result = new JSONArray();
        final CountDownLatch latch = new CountDownLatch(1);
        final AtomicReference<Exception> error = new AtomicReference<>();

        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    View root = activity.getWindow().getDecorView().getRootView();
                    collectViews(root, result, 0);
                } catch (Exception e) {
                    error.set(e);
                } finally {
                    latch.countDown();
                }
            }
        });

        if (!latch.await(UI_TIMEOUT_MS, TimeUnit.MILLISECONDS)) {
            throw new RuntimeException("getViewTree timed out");
        }
        if (error.get() != null) throw error.get();
        return result;
    }

    private static void collectViews(View view, JSONArray arr, int depth) {
        try {
            JSONObject obj = new JSONObject();
            obj.put("class", view.getClass().getSimpleName());
            obj.put("depth", depth);
            obj.put("visible", view.getVisibility() == View.VISIBLE);

            // Resource ID name
            if (view.getId() != View.NO_ID) {
                try {
                    String idName = view.getResources().getResourceEntryName(view.getId());
                    obj.put("id", idName);
                } catch (Exception e) {
                    obj.put("id", "0x" + Integer.toHexString(view.getId()));
                }
            }

            // Text content for TextViews
            if (view instanceof TextView) {
                CharSequence text = ((TextView) view).getText();
                if (text != null && text.length() > 0) {
                    String textStr = text.toString();
                    if (textStr.length() > 100) textStr = textStr.substring(0, 100) + "...";
                    obj.put("text", textStr);
                }
            }

            arr.put(obj);

            // Recurse into children
            if (view instanceof ViewGroup) {
                ViewGroup group = (ViewGroup) view;
                for (int i = 0; i < group.getChildCount(); i++) {
                    collectViews(group.getChildAt(i), arr, depth + 1);
                }
            }
        } catch (Exception e) {
            // Skip this view on error
        }
    }
}
