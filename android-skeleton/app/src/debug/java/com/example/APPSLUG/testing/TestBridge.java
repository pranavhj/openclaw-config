package com.example.APPSLUG.testing;

import android.app.Activity;
import android.view.View;
import android.widget.EditText;
import android.widget.TextView;

/**
 * High-level testing API for BeanShell scripts.
 * Pre-bound as 'bridge' in the script interpreter.
 *
 * Example:
 *   bridge.assertVisible("main_layout");
 *   bridge.clickById("btn_start");
 *   String text = bridge.getTextById("tv_result");
 */
public class TestBridge {

    private Activity mActivity;

    public TestBridge(Activity activity) {
        mActivity = activity;
    }

    /** Get the current activity's simple class name. */
    public String getActivityName() {
        Activity a = getActivity();
        return a != null ? a.getClass().getSimpleName() : null;
    }

    /** Find a view by its resource name (e.g. "btn_start"). */
    public View findById(String idName) {
        Activity a = getActivity();
        if (a == null) throw new RuntimeException("No active activity");
        int id = a.getResources().getIdentifier(idName, "id", a.getPackageName());
        if (id == 0) throw new RuntimeException("View not found: " + idName);
        View v = a.findViewById(id);
        if (v == null) throw new RuntimeException("View is null: " + idName);
        return v;
    }

    /** Get the text of a TextView/EditText by resource name. */
    public String getTextById(String idName) {
        View v = findById(idName);
        if (v instanceof TextView) {
            CharSequence text = ((TextView) v).getText();
            return text != null ? text.toString() : "";
        }
        throw new RuntimeException(idName + " is not a TextView");
    }

    /** Click a view by resource name. Runs on UI thread. */
    public void clickById(final String idName) {
        UiHelper.runOnUiThreadSync(getActivity(), new Runnable() {
            @Override
            public void run() {
                findById(idName).performClick();
            }
        });
    }

    /** Type text into an EditText by resource name. Runs on UI thread. */
    public void typeText(final String idName, final String text) {
        UiHelper.runOnUiThreadSync(getActivity(), new Runnable() {
            @Override
            public void run() {
                View v = findById(idName);
                if (v instanceof EditText) {
                    ((EditText) v).setText(text);
                } else {
                    throw new RuntimeException(idName + " is not an EditText");
                }
            }
        });
    }

    /** Assert a view is visible. Throws if not found or not VISIBLE. */
    public void assertVisible(String idName) {
        View v = findById(idName);
        if (v.getVisibility() != View.VISIBLE) {
            throw new RuntimeException(idName + " is not VISIBLE (visibility=" + v.getVisibility() + ")");
        }
    }

    /** Assert a TextView's text equals expected. */
    public void assertText(String idName, String expected) {
        String actual = getTextById(idName);
        if (!expected.equals(actual)) {
            throw new RuntimeException("assertText failed for " + idName
                    + ": expected=\"" + expected + "\" actual=\"" + actual + "\"");
        }
    }

    /** Assert a TextView's text contains the substring. */
    public void assertTextContains(String idName, String substring) {
        String actual = getTextById(idName);
        if (!actual.contains(substring)) {
            throw new RuntimeException("assertTextContains failed for " + idName
                    + ": \"" + actual + "\" does not contain \"" + substring + "\"");
        }
    }

    /** Press the back button. Runs on UI thread. */
    public void pressBack() {
        UiHelper.runOnUiThreadSync(getActivity(), new Runnable() {
            @Override
            public void run() {
                getActivity().onBackPressed();
            }
        });
    }

    private Activity getActivity() {
        // Refresh in case activity changed
        Activity current = TestServerInitProvider.getCurrentActivity();
        if (current != null) {
            mActivity = current;
        }
        return mActivity;
    }
}
