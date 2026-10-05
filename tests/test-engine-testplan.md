# Test Engine — Verification Test Plan

## Phase 1: Minimum Vertical

### P1.1 Skeleton file structure
- [ ] `android-skeleton/app/src/debug/AndroidManifest.xml` exists
- [ ] `android-skeleton/app/src/debug/java/com/example/APPSLUG/testing/DebugTestServer.java` exists
- [ ] `android-skeleton/app/src/debug/java/com/example/APPSLUG/testing/ScriptExecutor.java` exists
- [ ] `android-skeleton/app/src/debug/java/com/example/APPSLUG/testing/TestServerInitProvider.java` exists
- [ ] All `.java` files contain `package com.example.APPSLUG.testing;`
- [ ] `AndroidManifest.xml` contains INTERNET permission
- [ ] `AndroidManifest.xml` contains ContentProvider with `testserver` authority

### P1.2 build.gradle dependencies
- [ ] `debugImplementation 'org.apache-extras.beanshell:bsh:2.0b6'` present
- [ ] `debugImplementation 'org.nanohttpd:nanohttpd:2.3.1'` present

### P1.3 android-new.sh changes
- [ ] Source set rename loop includes `debug`
- [ ] Scaffold a project: `android-new.sh --slug testproj --dest /tmp/testproj`
- [ ] Verify `app/src/debug/java/com/example/testproj/testing/` exists (APPSLUG renamed)
- [ ] Verify `app/src/debug/java/com/example/APPSLUG/` does NOT exist
- [ ] Verify all `.java` files have `package com.example.testproj.testing;`
- [ ] Verify `AndroidManifest.xml` still has INTERNET and provider

### P1.4 android-test.sh script
- [ ] `--help` / no args prints usage and exits 1
- [ ] `--device` is required (exits 1 without it)
- [ ] `--ping` sends GET to /ping
- [ ] `--inline <code>` sends POST to /exec
- [ ] ADB port forward command is correct

### P1.5 Existing test suite
- [ ] `run-android-tests.sh` still passes all 177 existing tests
- [ ] New skeleton debug tests (SD1-SD11) all pass
- [ ] New scaffolding tests (N30-N32) all pass

### P1.6 Compile check
- [ ] Scaffold project builds with `./gradlew assembleDebug` (requires device/emulator or just compile check)
- [ ] Java files have no syntax errors (javac compile check)

## Phase 2: TestBridge + Screenshot + State

### P2.1 New files
- [ ] `TestBridge.java` exists and compiles
- [ ] `UiHelper.java` exists and compiles
- [ ] `ScreenshotHelper.java` exists and compiles

### P2.2 android-test.sh extensions
- [ ] `--screenshot <out.png>` sends GET to /screenshot
- [ ] `--state` sends GET to /state
- [ ] `--script <file>` reads file and sends POST to /exec
- [ ] `--script` with nonexistent file exits 1 with error message

### P2.3 DebugTestServer endpoints
- [ ] `/screenshot` endpoint exists in DebugTestServer.java
- [ ] `/state` endpoint exists in DebugTestServer.java
- [ ] All endpoints return proper Content-Type headers

## Phase 3: Integration + Documentation

### P3.1 Router + CLAUDE.md
- [ ] Router has test tool invoke rows
- [ ] Router backup synced
- [ ] agents/android.md has test engine section
- [ ] CLAUDE.md template in android-new.sh has Quick invoke entries for test commands

### P3.2 Full test suite
- [ ] All existing 177 tests pass
- [ ] All new tests pass
- [ ] Total test count increased appropriately

## Device tests (manual — after deploy to real device)

### DT.1 Basic connectivity
- [ ] Deploy app to device via android-deploy.sh
- [ ] `android-test.sh --ping` returns {"status":"ok",...}
- [ ] `android-test.sh --inline 'return 1+1'` returns {"success":true,"result":"2",...}

### DT.2 App interaction
- [ ] `--inline 'return bridge.getActivityName()'` returns activity name
- [ ] `--inline 'return bridge.getTextById("...")'` returns view text
- [ ] `--screenshot /tmp/test.png` saves valid PNG file
- [ ] `--state` returns JSON with activity info

### DT.3 Error handling
- [ ] Invalid script returns {"success":false,"error":"..."}
- [ ] Server not running → curl fails, script exits non-zero
