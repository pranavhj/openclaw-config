# Android Test Engine — Reference

Embedded BeanShell scripting engine for remote testing of Android apps.
Debug-only — zero release footprint. All code in `app/src/debug/`.

---

## Quick reference

```bash
# Ping — verify test server is running
bash /d/MyData/Software/openclaw-config/bin/android-test.sh \
  --device 100.122.101.27:5555 --ping

# Inline BeanShell script
bash /d/MyData/Software/openclaw-config/bin/android-test.sh \
  --device 100.122.101.27:5555 --inline 'return bridge.getActivityName();'

# Script from file
bash /d/MyData/Software/openclaw-config/bin/android-test.sh \
  --device 100.122.101.27:5555 --script test.bsh

# Screenshot
bash /d/MyData/Software/openclaw-config/bin/android-test.sh \
  --device 100.122.101.27:5555 --screenshot /tmp/screen.png

# Activity state + view tree
bash /d/MyData/Software/openclaw-config/bin/android-test.sh \
  --device 100.122.101.27:5555 --state
```

---

## Architecture

NanoHTTPD server (port 8973) + BeanShell interpreter, auto-started via
`TestServerInitProvider` (ContentProvider pattern — like Firebase, no app code changes).

**Endpoints:**
- `GET /ping` — `{"status":"ok","package":"...","activity":"..."}`
- `POST /exec` — BeanShell script in body → `{"success":true,"result":"...","elapsed_ms":N}`
- `GET /screenshot` — PNG bytes of current screen
- `GET /state` — activity info + view tree JSON

**Dependencies (debug-only):**
- `org.nanohttpd:nanohttpd:2.3.1` (~48KB)
- `org.apache-extras.beanshell:bsh:2.0b6` (~389KB)

**30s timeout** on script execution. Scripts that exceed this are killed.

---

## Pre-bound script variables

| Variable | Type | Description |
|----------|------|-------------|
| `activity` | Activity | Current foreground activity (null when phone locked) |
| `app` | Application | Application instance (always available) |
| `context` | Context | Current Activity or Application fallback |
| `bridge` | TestBridge | High-level testing API (see below) |
| `ui` | UiHelper | Sleep + UI thread sync |

---

## TestBridge API

| Method | Description |
|--------|-------------|
| `bridge.getActivityName()` | Current activity's simple class name |
| `bridge.findById("view_id")` | Find View by resource name |
| `bridge.getTextById("tv_id")` | Get text from TextView/EditText |
| `bridge.clickById("btn_id")` | Click a view (runs on UI thread) |
| `bridge.typeText("et_id", "text")` | Set EditText content |
| `bridge.assertVisible("view_id")` | Assert view is VISIBLE |
| `bridge.assertText("tv_id", "expected")` | Assert exact text match |
| `bridge.assertTextContains("tv_id", "sub")` | Assert text contains substring |
| `bridge.pressBack()` | Press back button |

---

## Operating procedures

### Phone must be unlocked

UI operations (bridge, screenshot, state) require the phone to be unlocked and the app
in foreground. When the screen locks, `onActivityPaused` fires and `activity` becomes null.

Ping and pure-compute scripts (no UI access) still work when locked.

### Wake + unlock via ADB

```bash
ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"
# Wake screen
"$ADB" -s 100.122.101.27:5555 shell input keyevent KEYCODE_WAKEUP
sleep 1
# Swipe up to unlock (no PIN/pattern assumed)
"$ADB" -s 100.122.101.27:5555 shell input swipe 500 1500 500 500
sleep 1
```

### Launch / bring app to foreground

```bash
"$ADB" -s 100.122.101.27:5555 shell am start -n com.example.SLUG/.MainActivity
```

### Force-stop and relaunch (clean restart)

```bash
"$ADB" -s 100.122.101.27:5555 shell am force-stop com.example.SLUG
sleep 2
"$ADB" -s 100.122.101.27:5555 shell am start -n com.example.SLUG/.MainActivity
```

### Recommended test sequence (from cold start)

```bash
# 1. Deploy
bash android-deploy.sh --project <path> --device 100.122.101.27:5555

# 2. Wake + unlock phone
"$ADB" -s 100.122.101.27:5555 shell input keyevent KEYCODE_WAKEUP
sleep 1
"$ADB" -s 100.122.101.27:5555 shell input swipe 500 1500 500 500
sleep 2

# 3. Verify test server
bash android-test.sh --device 100.122.101.27:5555 --ping
# → {"status":"ok","package":"com.example.SLUG","activity":"MainActivity"}

# 4. Run tests
bash android-test.sh --device 100.122.101.27:5555 --inline 'return bridge.getActivityName();'
```

---

## BeanShell script examples

```java
// Read a TextView's text
return bridge.getTextById("positionDisplay");
// → "0"

// Click a button and check result (wait for async)
String before = bridge.getTextById("positionDisplay");
bridge.clickById("btnUp");
ui.sleep(2000);  // wait for async network response
String after = bridge.getTextById("positionDisplay");
return "before=" + before + " after=" + after;
// → "before=0 after=500"

// Type into an EditText and click Send
bridge.typeText("commandText", "getenc");
bridge.clickById("Send");
ui.sleep(1000);
return bridge.getTextById("LogViewer");

// Navigate: press back, check activity changed
bridge.pressBack();
ui.sleep(500);
return bridge.getActivityName();

// Assert view state
bridge.assertVisible("main_layout");
bridge.assertText("calibrationStatus", "4 positions");
bridge.assertTextContains("positionDisplay", "0");

// Access Android APIs directly
import android.os.Build;
return "model=" + Build.MODEL + " sdk=" + Build.VERSION.SDK_INT;

// Get all view IDs on screen (useful for discovery)
import android.view.View;
import android.view.ViewGroup;
StringBuilder sb = new StringBuilder();
void listIds(View v, String indent) {
    if (v.getId() != View.NO_ID) {
        try { sb.append(indent + v.getResources().getResourceEntryName(v.getId())
              + " (" + v.getClass().getSimpleName() + ")\n"); }
        catch (Exception e) {}
    }
    if (v instanceof ViewGroup) {
        ViewGroup g = (ViewGroup) v;
        for (int i = 0; i < g.getChildCount(); i++) listIds(g.getChildAt(i), indent + "  ");
    }
}
listIds(activity.getWindow().getDecorView(), "");
return sb.toString();
```

---

## Troubleshooting

**`curl: (52) Empty reply from server`** or connection refused on first ping after deploy
→ App hasn't fully launched yet. Run `am start -n <package>/.MainActivity`, wait 2s, retry.

**`"error":"No active activity"`** on bridge/screenshot/state calls
→ Phone screen is locked or app is in background. Wake + unlock first (see above).
→ Ping still works when locked — use it to verify server is running before unlocking.

**`"error":"No script provided"`** on /exec
→ curl must send `Content-Type: text/plain`. `android-test.sh` handles this automatically.
→ Manual curl: `curl -X POST -H "Content-Type: text/plain" --data-binary "return 1+1;" http://127.0.0.1:8973/exec`

**BeanShell parse error — `+` becomes space**
→ Using `Content-Type: application/x-www-form-urlencoded` (curl default with `-d`). Use `text/plain`.

**Button click works but value doesn't change**
→ The click fires the real handler (including async network calls). Use `ui.sleep(2000)` to wait
for async responses before reading the result. Check logcat to confirm the action was sent.

**Server started twice in logcat**
→ Normal after force-stop + relaunch. Each app process starts its own test server instance.

**Port conflict — only one test-enabled app at a time**
→ All debug apps share port 8973. If two are running, only one binds successfully.
→ Fix: `adb shell am force-stop <other.package>`, wait 3s, then relaunch target app.
→ Check logcat `TestServer` — look for "Test server started" (success) vs bind errors.

**Verify test server is running** via logcat:
```bash
bash android-logs.sh --tag TestServer --device 100.122.101.27:5555 --mode default --dump
# Look for: "Test server started on port 8973"
```
