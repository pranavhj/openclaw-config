package com.example.APPSLUG.testing;

import android.app.Activity;
import android.app.Application;
import android.util.Log;

import org.json.JSONObject;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import bsh.Interpreter;

/**
 * BeanShell script executor. Pre-binds app objects so scripts can access
 * activity, context, app, bridge (TestBridge), and ui (UiHelper) directly.
 */
public class ScriptExecutor {

    private static final String TAG = "TestServer";
    private static final long TIMEOUT_MS = 30000; // 30 second timeout
    private final Application mApp;
    private final ExecutorService mExecutor = Executors.newSingleThreadExecutor();

    public ScriptExecutor(Application app) {
        mApp = app;
    }

    public JSONObject execute(final String script) {
        JSONObject result = new JSONObject();
        long startTime = System.currentTimeMillis();

        Future<Object> future = mExecutor.submit(new Callable<Object>() {
            @Override
            public Object call() throws Exception {
                Interpreter interpreter = new Interpreter();

                // Pre-bind objects
                Activity activity = TestServerInitProvider.getCurrentActivity();
                interpreter.set("app", mApp);
                interpreter.set("context", activity != null ? activity : mApp);
                interpreter.set("activity", activity);

                TestBridge bridge = new TestBridge(activity);
                interpreter.set("bridge", bridge);

                UiHelper ui = new UiHelper();
                interpreter.set("ui", ui);

                return interpreter.eval(script);
            }
        });

        try {
            Object evalResult = future.get(TIMEOUT_MS, TimeUnit.MILLISECONDS);
            long elapsed = System.currentTimeMillis() - startTime;

            result.put("success", true);
            result.put("result", evalResult != null ? evalResult.toString() : null);
            result.put("elapsed_ms", elapsed);
        } catch (TimeoutException e) {
            future.cancel(true);
            try {
                result.put("success", false);
                result.put("error", "Script timed out after " + TIMEOUT_MS + "ms");
                result.put("elapsed_ms", TIMEOUT_MS);
            } catch (Exception je) {
                Log.e(TAG, "JSON error", je);
            }
        } catch (Exception e) {
            long elapsed = System.currentTimeMillis() - startTime;
            try {
                Throwable cause = e.getCause() != null ? e.getCause() : e;
                StringWriter sw = new StringWriter();
                cause.printStackTrace(new PrintWriter(sw));

                result.put("success", false);
                result.put("error", cause.getMessage());
                result.put("stacktrace", sw.toString());
                result.put("elapsed_ms", elapsed);
            } catch (Exception je) {
                Log.e(TAG, "JSON error", je);
            }
        }

        return result;
    }
}
