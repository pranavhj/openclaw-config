package com.example.APPSLUG.testing;

import android.app.Activity;
import android.app.Application;
import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.util.Log;

/**
 * Auto-starts the debug test server when the app launches.
 * Uses the ContentProvider pattern (like Firebase) — no code changes needed in the app.
 * Registered in debug/AndroidManifest.xml so it only runs in debug builds.
 */
public class TestServerInitProvider extends ContentProvider
        implements Application.ActivityLifecycleCallbacks {

    private static final String TAG = "TestServer";
    private static Activity sCurrentActivity;
    private DebugTestServer mServer;

    public static Activity getCurrentActivity() {
        return sCurrentActivity;
    }

    @Override
    public boolean onCreate() {
        Application app = (Application) getContext().getApplicationContext();
        app.registerActivityLifecycleCallbacks(this);

        try {
            mServer = new DebugTestServer(app, 8973);
            mServer.start();
            Log.i(TAG, "Test server started on port 8973");
        } catch (Exception e) {
            Log.e(TAG, "Failed to start test server", e);
        }

        return true;
    }

    // --- ActivityLifecycleCallbacks ---

    @Override public void onActivityCreated(Activity activity, Bundle savedInstanceState) {}
    @Override public void onActivityStarted(Activity activity) {}

    @Override
    public void onActivityResumed(Activity activity) {
        sCurrentActivity = activity;
    }

    @Override
    public void onActivityPaused(Activity activity) {
        if (sCurrentActivity == activity) {
            sCurrentActivity = null;
        }
    }

    @Override public void onActivityStopped(Activity activity) {}
    @Override public void onActivitySaveInstanceState(Activity activity, Bundle outState) {}
    @Override public void onActivityDestroyed(Activity activity) {}

    // --- ContentProvider stubs (unused) ---

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs, String sortOrder) { return null; }
    @Override public String getType(Uri uri) { return null; }
    @Override public Uri insert(Uri uri, ContentValues values) { return null; }
    @Override public int delete(Uri uri, String selection, String[] selectionArgs) { return 0; }
    @Override public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) { return 0; }
}
