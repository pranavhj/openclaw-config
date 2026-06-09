package com.example.APPSLUG.testing;

import android.app.Activity;
import android.app.Application;
import android.util.Log;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayInputStream;
import java.util.HashMap;
import java.util.Map;

import fi.iki.elonen.NanoHTTPD;

/**
 * Embedded HTTP server for remote testing. Runs on port 8973 in debug builds only.
 * Endpoints:
 *   GET  /ping       — health check
 *   POST /exec       — execute BeanShell script
 *   GET  /screenshot — capture current screen as PNG
 *   GET  /state      — current activity and view info
 */
public class DebugTestServer extends NanoHTTPD {

    private static final String TAG = "TestServer";
    private final Application mApp;
    private final ScriptExecutor mExecutor;

    public DebugTestServer(Application app, int port) {
        super(port);
        mApp = app;
        mExecutor = new ScriptExecutor(app);
    }

    @Override
    public Response serve(IHTTPSession session) {
        String uri = session.getUri();
        Method method = session.getMethod();

        try {
            if ("/ping".equals(uri) && Method.GET.equals(method)) {
                return handlePing();
            } else if ("/exec".equals(uri) && Method.POST.equals(method)) {
                return handleExec(session);
            } else if ("/screenshot".equals(uri) && Method.GET.equals(method)) {
                return handleScreenshot();
            } else if ("/state".equals(uri) && Method.GET.equals(method)) {
                return handleState();
            } else {
                JSONObject err = new JSONObject();
                err.put("error", "Not found: " + uri);
                return newFixedLengthResponse(Response.Status.NOT_FOUND,
                        "application/json", err.toString());
            }
        } catch (Exception e) {
            Log.e(TAG, "Error handling " + uri, e);
            try {
                JSONObject err = new JSONObject();
                err.put("error", e.getMessage());
                return newFixedLengthResponse(Response.Status.INTERNAL_ERROR,
                        "application/json", err.toString());
            } catch (Exception je) {
                return newFixedLengthResponse(Response.Status.INTERNAL_ERROR,
                        "text/plain", "Internal error");
            }
        }
    }

    private Response handlePing() throws Exception {
        JSONObject json = new JSONObject();
        json.put("status", "ok");
        json.put("package", mApp.getPackageName());
        Activity current = TestServerInitProvider.getCurrentActivity();
        if (current != null) {
            json.put("activity", current.getClass().getSimpleName());
        }
        return newFixedLengthResponse(Response.Status.OK,
                "application/json", json.toString());
    }

    private Response handleExec(IHTTPSession session) throws Exception {
        // Read POST body
        Map<String, String> bodyMap = new HashMap<>();
        session.parseBody(bodyMap);
        String script = bodyMap.get("postData");
        if (script == null || script.isEmpty()) {
            // Try form parameter
            Map<String, String> params = session.getParms();
            script = params.get("script");
        }

        if (script == null || script.isEmpty()) {
            JSONObject err = new JSONObject();
            err.put("error", "No script provided. POST raw body or form param 'script'.");
            return newFixedLengthResponse(Response.Status.BAD_REQUEST,
                    "application/json", err.toString());
        }

        JSONObject result = mExecutor.execute(script);
        Response.Status status = result.optBoolean("success", false)
                ? Response.Status.OK : Response.Status.INTERNAL_ERROR;
        return newFixedLengthResponse(status, "application/json", result.toString());
    }

    private Response handleScreenshot() throws Exception {
        Activity activity = TestServerInitProvider.getCurrentActivity();
        if (activity == null) {
            JSONObject err = new JSONObject();
            err.put("error", "No active activity");
            return newFixedLengthResponse(Response.Status.INTERNAL_ERROR,
                    "application/json", err.toString());
        }

        byte[] png = ScreenshotHelper.capture(activity);
        if (png == null) {
            JSONObject err = new JSONObject();
            err.put("error", "Screenshot capture failed");
            return newFixedLengthResponse(Response.Status.INTERNAL_ERROR,
                    "application/json", err.toString());
        }

        return newFixedLengthResponse(Response.Status.OK, "image/png",
                new ByteArrayInputStream(png), png.length);
    }

    private Response handleState() throws Exception {
        Activity activity = TestServerInitProvider.getCurrentActivity();
        JSONObject json = new JSONObject();

        if (activity == null) {
            json.put("activity", JSONObject.NULL);
            json.put("package", mApp.getPackageName());
        } else {
            json.put("activity", activity.getClass().getSimpleName());
            json.put("activity_class", activity.getClass().getName());
            json.put("package", mApp.getPackageName());
            json.put("title", activity.getTitle() != null ? activity.getTitle().toString() : "");

            // Get view tree summary via UiHelper (runs on UI thread)
            try {
                JSONArray views = UiHelper.getViewTree(activity);
                json.put("views", views);
            } catch (Exception e) {
                json.put("views_error", e.getMessage());
            }
        }

        return newFixedLengthResponse(Response.Status.OK,
                "application/json", json.toString());
    }
}
