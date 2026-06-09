# Android Knowledge Base

Canonical reference for Android development in this workspace. Read by the router when creating
new Android projects. Sub-sessions with complex build/deploy/troubleshooting needs should also
read this file — paths are inlined in each project's CLAUDE.md for zero-overhead startup.

---

## Cached paths

| What | Path |
|------|------|
| ADB | `/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe` |
| JAVA_HOME (JDK 17 Temurin) | `/c/Users/prana/jdk17/jdk-17.0.19+10` |
| Android SDK root | `/c/Users/prana/AppData/Local/Android/Sdk` |
| GitHub CLI | `/c/Program Files/GitHub CLI/gh.exe` |
| android-deploy script | `D:\MyData\Software\openclaw-config\bin\android-deploy.sh` |
| android-logs script | `D:\MyData\Software\openclaw-config\bin\android-logs.sh` |
| android-new script | `D:\MyData\Software\openclaw-config\bin\android-new.sh` |
| android-test script | `D:\MyData\Software\openclaw-config\bin\android-test.sh` |
| android-skeleton | `D:\MyData\Software\openclaw-config\android-skeleton\` |
| discord-send | `D:\MyData\Software\openclaw-config\bin\discord-send.py` |
| agent-smart | `D:\MyData\Software\openclaw-config\bin\agent-smart.py` |

---

## Device — OnePlus 7

- **Model:** OnePlus 7, Android 10, API 29
- **Tailscale IP (stable):** `100.122.101.27:5555` — use this always
- **Local IP (changes with DHCP):** `10.0.0.122:5555`
- **ADB mode:** TCP (legacy wireless — no native Wireless Debugging on Android 10)

```bash
ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"
"$ADB" connect 100.122.101.27:5555
"$ADB" devices
```

---

## Toolchain versions

| Component | Version |
|-----------|---------|
| AGP (Android Gradle Plugin) | 8.2.2 |
| Gradle wrapper | 8.2 |
| Java (build JDK) | 17 (Temurin) |
| Java source/target compat | 1.8 (in compileOptions) |
| minSdk | 24 |
| targetSdk / compileSdk | 34 |

Always export `JAVA_HOME` before running gradlew:
```bash
export JAVA_HOME="/c/Users/prana/jdk17/jdk-17.0.19+10"
./gradlew assembleDebug
```

---

## Debug keystore

Committed to each project root as `debug.keystore`. All projects share the same keystore.

```
storePassword: android
keyAlias:      androiddebugkey
keyPassword:   android
```

Regenerate if needed:
```bash
keytool -genkey -v -keystore debug.keystore -alias androiddebugkey \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass android -keypass android \
  -dname "CN=Android Debug,O=Android,C=US"
```

`app/build.gradle` signingConfig block:
```groovy
signingConfigs {
    debug {
        storeFile file("${rootProject.projectDir}/debug.keystore")
        storePassword 'android'
        keyAlias 'androiddebugkey'
        keyPassword 'android'
    }
}
```

---

## System scripts

### android-deploy.sh

```bash
# Local build + install
bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh \
  --project /c/Users/prana/AndroidStudioProjects/MyApp \
  --device 100.122.101.27:5555

# GitHub Actions artifact + install
bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh \
  --project /c/Users/prana/AndroidStudioProjects/MyApp \
  --device 100.122.101.27:5555 \
  --ci pranavhj/MyApp
```

- Auto-reads `applicationId` from `app/build.gradle` (handles Groovy and Kotlin DSL)
- Auto-connects ADB before install
- Handles signature mismatch (uninstall + reinstall — loses app data)
- Script must be run after `cd` to project dir is NOT required — `--project` handles it
- CI: downloads artifact named `app-debug` from latest successful run

### android-logs.sh

```bash
# Stream filtered logs (interactive)
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \
  --tag MyApp --device 100.122.101.27:5555

# Snapshot for Discord (non-blocking)
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \
  --tag MyApp --device 100.122.101.27:5555 --mode dump

# Crashes only
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \
  --tag MyApp --device 100.122.101.27:5555 --mode crash
```

Modes: `default` (app tag + crashes), `full` (unfiltered), `crash` (crashes only), `dump` (snapshot with -d)
**Use `dump` for Discord output** — streaming modes block indefinitely.

### android-new.sh

```bash
bash /d/MyData/Software/openclaw-config/bin/android-new.sh \
  --slug myapp \
  --dest /c/Users/prana/AndroidStudioProjects/MyApp
```

Copies `android-skeleton/`, replaces `APPSLUG` placeholder, renames package dir, runs `git init`.
After running: add `CLAUDE.md` from the router's Android template, then build to verify.

### android-test.sh (embedded test engine)

Debug builds embed a NanoHTTPD + BeanShell test server (port 8973). Auto-starts via ContentProvider.
Phone must be unlocked for UI operations. Full docs: `agents/android-test-engine.md`.

```bash
bash android-test.sh --device 100.122.101.27:5555 --ping           # health check
bash android-test.sh --device 100.122.101.27:5555 --inline 'return bridge.getActivityName();'
bash android-test.sh --device 100.122.101.27:5555 --screenshot /tmp/screen.png
bash android-test.sh --device 100.122.101.27:5555 --state          # view tree
```

Key gotchas: wake phone first (`input keyevent KEYCODE_WAKEUP` + swipe), use `ui.sleep()` after
clicks for async ops, check logcat tag `TestServer` to verify server started.

---

## Deploy modes: local vs CI

| | Local | CI (GitHub Actions) |
|---|---|---|
| Speed | Fast (~30s build) | Slow (2-5 min build + download) |
| Use when | Active development | Verifying Actions pipeline |
| Requires | JAVA_HOME, gradlew | gh CLI, repo with Actions workflow |
| Flag | (none) | `--ci <repo>` |

---

## Project source layout

```
<project>/
├── gradlew
├── build.gradle          # top-level: AGP version
├── settings.gradle       # rootProject.name, include ':app'
├── gradle.properties     # JVM args, AndroidX flags
├── debug.keystore        # committed, shared creds
└── app/
    ├── build.gradle      # applicationId, minSdk, dependencies
    ├── src/main/
    │   ├── AndroidManifest.xml
    │   ├── java/com/example/<slug>/
    │   │   └── MainActivity.java
    │   └── res/
    │       ├── layout/activity_main.xml
    │       ├── values/{strings,colors,themes}.xml
    │       └── mipmap-anydpi-v26/{ic_launcher,ic_launcher_round}.xml
    └── src/debug/            # debug-only test engine (not in release)
        ├── AndroidManifest.xml   # INTERNET permission + provider
        └── java/com/example/<slug>/testing/
            ├── DebugTestServer.java
            ├── ScriptExecutor.java
            ├── TestBridge.java
            ├── UiHelper.java
            ├── ScreenshotHelper.java
            └── TestServerInitProvider.java
```

---

## Templates

`app/build.gradle` template is in the skeleton: `android-skeleton/app/build.gradle`.
GitHub Actions workflow template: save `.github/workflows/build.yml` — uses `actions/checkout@v4`,
`actions/setup-java@v4` (java 17, temurin), `./gradlew assembleDebug`, upload artifact `app-debug`.

---

## Android detection heuristics

A project is Android if it has **any** of:
- `gradlew` in project root
- `app/build.gradle` in project root
- `app/src/main/AndroidManifest.xml`

---

## New project creation guide

```bash
# 1. Scaffold from skeleton
bash /d/MyData/Software/openclaw-config/bin/android-new.sh \
  --slug myapp \
  --dest /c/Users/prana/AndroidStudioProjects/MyApp

# 2. Add CLAUDE.md (use router's Android template, fill in slug/package/device)

# 3. Verify build
cd /c/Users/prana/AndroidStudioProjects/MyApp
export JAVA_HOME="/c/Users/prana/jdk17/jdk-17.0.19+10"
./gradlew assembleDebug

# 4. Deploy to device
bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh \
  --project /c/Users/prana/AndroidStudioProjects/MyApp \
  --device 100.122.101.27:5555

# 5. (Optional) Create GitHub repo and push
cd /c/Users/prana/AndroidStudioProjects/MyApp
"/c/Program Files/GitHub CLI/gh.exe" repo create pranavhj/MyApp --public --source=. --push
```

---

## Troubleshooting playbook

### Build failures

**`error: source release 17 requires target release 17`**
→ `compileOptions` is missing or set wrong. Use `VERSION_1_8` not `VERSION_17`.

**`Minimum supported Gradle version is X`**
→ Update `gradle-wrapper.properties` `distributionUrl` to the required version.

**`Could not resolve com.android.tools.build:gradle:X.Y.Z`**
→ AGP version not available. Check latest at https://developer.android.com/build/releases/gradle-plugin

**`JAVA_HOME is set to an invalid directory`**
→ `export JAVA_HOME="/c/Users/prana/jdk17/jdk-17.0.19+10"` before running gradlew.

**`Unsupported class file major version 61`**
→ Gradle daemon was started with wrong Java version. Run `./gradlew --stop` then retry.

### ADB failures

**`error: device offline`**
→ `adb disconnect 100.122.101.27:5555 && adb connect 100.122.101.27:5555`

**`adb: no devices/emulators found`**
→ Device not connected. Run `adb connect 100.122.101.27:5555` first.

**`INSTALL_FAILED_UPDATE_INCOMPATIBLE`** (signature mismatch)
→ `android-deploy.sh` handles this automatically. Manual: `adb uninstall <package>` then reinstall.

**`Connection refused` on adb connect**
→ Phone's ADB over WiFi disabled. Connect USB, run `adb tcpip 5555`, disconnect USB, retry.

### Logcat issues

**No output from logcat filter**
→ Check tag spelling — it must match `Log.d("TAG", ...)` exactly (case-sensitive).
→ Try `--mode full` first to confirm device is producing output.

**`error: closed` on logcat**
→ Device disconnected mid-stream. Reconnect and retry.

### Common runtime errors

**`NetworkOnMainThreadException`**
→ All network calls must run on a background thread. Use `AsyncTask`, `Thread`, or `ExecutorService`.

**`Permission denied` for INTERNET/camera/location**
→ Add `<uses-permission>` to `AndroidManifest.xml`. For dangerous permissions (camera, location),
also request at runtime via `ActivityCompat.requestPermissions()`.

**App crashes immediately on launch**
→ Check logcat `--mode crash`. Common causes: missing layout IDs, NPE in `onCreate`, missing
`<activity>` entry in manifest for MainActivity.
