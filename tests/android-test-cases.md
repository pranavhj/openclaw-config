# Android Test Cases

Tracks all test cases for the Android-aware openclaw implementation.
Run automated tests: `bash tests/run-android-tests.sh`

**Status codes:** `PASS` | `FAIL` | `PENDING` | `MANUAL` | `SKIP`

Last run: 2026-06-07 — 143 PASS, 0 FAIL (automated); live device: D9/D11/D12/D13/D19/L9/N30/N31 PASS

---

## S — android-skeleton/ structure

| ID | Test | Status | Notes |
|----|------|--------|-------|
| S1 | All required files exist (gradlew, gradlew.bat, gradle-wrapper.jar, gradle-wrapper.properties, build.gradle, settings.gradle, gradle.properties, app/build.gradle, AndroidManifest.xml, MainActivity.java, layout/activity_main.xml, values/strings.xml, values/colors.xml, values/themes.xml, drawable/ic_launcher_background.xml, drawable/ic_launcher_foreground.xml, mipmap-anydpi-v26/ic_launcher.xml, mipmap-anydpi-v26/ic_launcher_round.xml, debug.keystore, .gitignore) | PASS | |
| S2 | gradle-wrapper.properties distributionUrl = gradle-8.2-bin.zip | PASS | |
| S3 | Top-level build.gradle has AGP version 8.2.2 | PASS | |
| S4 | app/build.gradle has namespace, applicationId, minSdk 24, targetSdk 34, debug keystore block | PENDING | |
| S5 | app/build.gradle still has APPSLUG placeholder (not pre-replaced) | PASS | |
| S6 | settings.gradle has rootProject.name = "APPSLUG" | PASS | |
| S7 | strings.xml has app_name = APPSLUG | PASS | |
| S8 | themes.xml has Theme.APPSLUG | PASS | |
| S9 | Adaptive icons exist as XML (no binary PNGs) — mipmap-anydpi-v26/ has ic_launcher.xml and ic_launcher_round.xml | PENDING | |
| S10 | .gitignore excludes build/, .gradle/, local.properties | PENDING | |
| S11 | debug.keystore is non-empty binary | PASS | |
| S12 | gradle-wrapper.jar is non-empty binary | PASS | |

---

## N — android-new.sh

### Argument handling
| ID | Test | Status | Notes |
|----|------|--------|-------|
| N1 | No args → usage message, exits non-zero | PASS | |
| N2 | --slug only (missing --dest) → usage, exits non-zero | PASS | |
| N3 | --dest only (missing --slug) → usage, exits non-zero | PASS | |
| N4 | --dest pointing to existing path → error, exits non-zero | PASS | |
| N5 | Unknown flag → "Unknown arg" error, exits non-zero | PASS | |

### Scaffolding
| ID | Test | Status | Notes |
|----|------|--------|-------|
| N6 | After run, skeleton copied to dest | PASS | |
| N7 | APPSLUG replaced in app/build.gradle → applicationId "com.example.sensorapp" | PASS | |
| N8 | APPSLUG replaced in settings.gradle → rootProject.name = "sensorapp" | PASS | |
| N9 | APPSLUG replaced in AndroidManifest.xml → Theme.sensorapp | PASS | |
| N10 | APPSLUG replaced in MainActivity.java → package com.example.sensorapp | PASS | |
| N11 | APPSLUG replaced in strings.xml → app_name = sensorapp | PASS | |
| N12 | Java package directory renamed APPSLUG → sensorapp | PASS | |
| N13 | Old APPSLUG/ package dir is gone | PASS | |
| N14 | gradle-wrapper.jar NOT modified (binary excluded) — non-empty, byte count matches original | PASS | |
| N15 | debug.keystore NOT modified (binary excluded) | PASS | |
| N16 | git init ran; git log shows one initial commit | PASS | |
| N17 | local.properties created with sdk.dir=C\:\\Users\\prana\\AppData\\Local\\Android\\Sdk | PASS | Bug #2 fix |

### CLAUDE.md generation
| ID | Test | Status | Notes |
|----|------|--------|-------|
| N18 | CLAUDE.md generated at dest root | PASS | |
| N19 | Default --app-tag: first letter of slug capitalized (sensorapp → Sensorapp) | PASS | |
| N20 | Custom --app-tag SensorApp: CLAUDE.md header and --tag use SensorApp | PASS | |
| N21 | Default --github-repo: pranavhj/sensorapp in CLAUDE.md | PASS | |
| N22 | Custom --github-repo pranavhj/SensorApp: used in deploy-ci and Project section | PASS | |
| N23 | Package in CLAUDE.md = com.example.sensorapp | PASS | |
| N24 | deploy quick invoke --project path = --dest value (no placeholder) | PASS | |
| N25 | logs-dump quick invoke uses --mode default --dump | PASS | |
| N26 | logs-crash quick invoke uses --mode crash --dump | PASS | Bug #1 fix |
| N27 | logs quick invoke has NO --dump flag (streaming) | PASS | |
| N28 | CLAUDE.md has all 6 quick invoke entries: build, deploy, deploy-ci, logs-dump, logs-crash, logs, adb-connect | PASS | |
| N29 | CLAUDE.md has pointer to agents/android.md | PASS | |

### Build verification
| ID | Test | Status | Notes |
|----|------|--------|-------|
| N30 | ./gradlew assembleDebug on scaffolded project succeeds (JAVA_HOME set, local.properties present) | PASS | ~30s build; n30app slug |
| N31 | APK produced at app/build/outputs/apk/debug/app-debug.apk | PASS | Confirmed after N30 |

---

## D — android-deploy.sh

### Argument handling
| ID | Test | Status | Notes |
|----|------|--------|-------|
| D1 | No args → usage, exits non-zero | PASS | |
| D2 | Missing --device → usage, exits non-zero | PASS | |
| D3 | Missing --project → usage, exits non-zero | PASS | |
| D4 | --project path with no app/build.gradle → "not found" error, exits non-zero | PASS | |
| D5 | Unknown flag → "Unknown arg", exits non-zero | PASS | |

### Package detection
| ID | Test | Status | Notes |
|----|------|--------|-------|
| D6 | Reads Groovy DSL: applicationId "com.example.foo" → PACKAGE=com.example.foo | PASS | |
| D7 | Reads Kotlin DSL: applicationId = "com.example.foo" → PACKAGE=com.example.foo | PASS | |
| D8 | build.gradle with no applicationId line → error, exits non-zero | PASS | |

### Local build path (requires device)
| ID | Test | Status | Notes |
|----|------|--------|-------|
| D9 | adb connect called before build | PASS | Line 59 (connect) < line 87 (gradlew) |
| D10 | Unreachable device → "not reachable" error, exits non-zero | MANUAL | Disconnect device to test |
| D11 | Build failure (bad JAVA_HOME) → "Build failed.", exits non-zero | PASS | Confirmed exit 1 |
| D12 | Successful build → APK at app/build/outputs/apk/debug/app-debug.apk | PASS | Bug #4 fix (exit code); live install confirmed |
| D13 | adb install -r called with -s <device> flag | PASS | Script line 98 + live output confirmed |
| D14 | Signature mismatch → uninstall then reinstall | MANUAL | Requires prior install with different key |

### CI path (requires GitHub Actions run)
| ID | Test | Status | Notes |
|----|------|--------|-------|
| D15 | gh run list called with --status success --limit 1 | MANUAL | |
| D16 | No successful runs → "no successful runs found", exits non-zero | MANUAL | |
| D17 | Artifact downloaded to /tmp/android-deploy-<package>/ | MANUAL | |
| D18 | Temp dir cleaned up after install | MANUAL | |
| D19 | /tmp/ on Windows Git Bash resolves to writable path | PASS | echo /tmp |

---

## L — android-logs.sh

### Argument handling
| ID | Test | Status | Notes |
|----|------|--------|-------|
| L1 | No args → usage, exits non-zero | PASS | |
| L2 | Missing --tag → usage, exits non-zero | PASS | |
| L3 | Missing --device → usage, exits non-zero | PASS | |
| L4 | Unknown flag → "Unknown arg", exits non-zero | PASS | |

### Mode behaviour (requires device for full test; script construction testable without)
| ID | Test | Status | Notes |
|----|------|--------|-------|
| L5 | --mode default (no --dump): command includes "*:S" TAG:V AndroidRuntime:E, no -d | PASS | Verify via dry-run grep |
| L6 | --mode full (no --dump): command is logcat -v time, no filter, no -d | MANUAL | |
| L7 | --mode crash (no --dump): command includes "*:S" AndroidRuntime:E TAG:E, no -d | PASS | |
| L8 | --dump flag: -d added to command | PASS | |
| L9 | --mode crash --dump: crash filter + -d (Bug #1 fix verified) | PASS | |
| L10 | Legacy --mode dump: treated as --mode default --dump | PASS | |
| L11 | adb connect called before logcat | MANUAL | Check output |
| L12 | Snapshot label printed for --dump mode | PASS | |
| L13 | Streaming label printed for non-dump mode | PASS | |

---

## A — agents/android.md content

| ID | Test | Status | Notes |
|----|------|--------|-------|
| A1 | File exists at D:\MyData\Software\openclaw-config\agents\android.md | PASS | |
| A2 | All 10 paths present: ADB, JAVA_HOME, SDK root, GH CLI, android-deploy, android-logs, android-new, android-skeleton, discord-send, agent-smart | PASS | |
| A3 | Device section has both IPs: 100.122.101.27:5555 and 10.0.0.122:5555 | PENDING | |
| A4 | Toolchain versions: AGP 8.2.2, Gradle 8.2, Java 17, source/target 1.8, minSdk 24, targetSdk 34 | PENDING | |
| A5 | Debug keystore creds: storepass=android, alias=androiddebugkey, keypass=android | PENDING | |
| A6 | Usage examples for android-deploy.sh, android-logs.sh, android-new.sh | PENDING | |
| A7 | dump mode note: "Use dump for Discord output — streaming modes block" | PASS | |
| A8 | Local vs CI deploy comparison | PENDING | |
| A9 | app/build.gradle template has correct namespace, applicationId, signingConfig, compileOptions VERSION_1_8 | PENDING | |
| A10 | GitHub Actions template uses java-version 17, distribution temurin, artifact name app-debug | PENDING | |
| A11 | Android detection heuristics present | PASS | |
| A12 | Troubleshooting covers: build, ADB, logcat, runtime errors | PENDING | |
| A13 | New project guide uses android-new.sh (not "open Android Studio") | PASS | |

---

## T — TableNew/CLAUDE.md content

| ID | Test | Status | Notes |
|----|------|--------|-------|
| T1 | File exists at AndroidStudioProjects/TableNew/CLAUDE.md | PASS | |
| T2 | Sub-session rules (5-step) present | PASS | |
| T3 | All 6 paths in table: ADB, JAVA_HOME, GH CLI, android-deploy, android-logs, discord-send | PENDING | |
| T4 | Tailscale IP 100.122.101.27:5555 in Device section (not local IP) | PASS | |
| T5 | Package: com.example.tablenew | PASS | |
| T6 | GitHub repo: pranavhj/TableNew | PASS | |
| T7 | Source paths list MainActivity.java and TCPClient.java | PENDING | |
| T8 | 7 quick invoke entries: build, deploy, deploy-ci, logs, logs-dump, logs-crash, adb-connect | PASS | |
| T9 | deploy quick invoke: --project /c/Users/prana/AndroidStudioProjects/TableNew | PASS | |
| T10 | deploy and deploy-ci use Tailscale IP 100.122.101.27:5555 | PASS | |
| T11 | logs-dump uses --mode default --dump or --mode dump | PASS | |
| T12 | logs-crash uses --mode crash --dump (Bug #1 fix) | PASS | |
| T13 | logs has NO --dump flag (streaming) | PASS | |
| T14 | adb-connect uses full ADB path and Tailscale IP | PENDING | |
| T15 | Stack: Java 1.8 compat, AGP 8.2.2, minSdk 24, targetSdk 34 | PENDING | |
| T16 | Pointer to agents/android.md | PASS | |

---

## R — Router openclaw/CLAUDE.md

| ID | Test | Status | Notes |
|----|------|--------|-------|
| R1 | Android detection note exists | PASS | |
| R2 | Detection by gradlew + app/build.gradle mentioned | PASS | |
| R3 | Detection by AndroidManifest.xml mentioned | PASS | |
| R4 | Detection by "create/new/make Android project/app" prompt mentioned | PASS | |
| R5 | Routing table has 6 intent rows (deploy, deploy-ci, logs, logs-crash, build, adb-connect) | PASS | Bug #3 fix |
| R6 | "deploy" → deploy quick invoke | PASS | |
| R7 | "deploy from CI/GitHub/Actions" → deploy-ci | PASS | |
| R8 | "logs/logcat/what's happening" → logs-dump (dump, not streaming) | PASS | |
| R9 | "crash/exception/stacktrace" → logs-crash (crash filter + dump) | PASS | Bug #3 fix |
| R10 | "always dump, never streaming" note present | PASS | |
| R11 | "build only" → build | PASS | |
| R12 | "connect ADB/device not found" → adb-connect | PASS | |
| R13 | "fix/add/change/implement" → spawn sub-session | PASS | |
| R14 | android-new.sh command with all 4 flags shown for new project | PASS | |
| R15 | New Android Project Template block is ABSENT (75-line block removed) | PASS | |

---

## Y — Sync check

| ID | Test | Status | Notes |
|----|------|--------|-------|
| Y1 | diff openclaw/CLAUDE.md agents/openclaw-CLAUDE.md → no differences | PASS | |

---

## E — End-to-end integration (all MANUAL — require full openclaw stack)

| ID | Prompt | Expected | Status | Notes |
|----|--------|----------|--------|-------|
| E1 | "deploy TableNew" | Tool invoke → deploy quick invoke → android-deploy.sh --project .../TableNew --device 100.122.101.27:5555 | MANUAL | |
| E2 | "deploy TableNew from GitHub Actions" | deploy-ci quick invoke → android-deploy.sh --ci pranavhj/TableNew | MANUAL | |
| E3 | "show me TableNew logs" | logs-dump quick invoke → android-logs.sh --mode default --dump | MANUAL | |
| E4 | "show TableNew crash logs" | logs-crash quick invoke → android-logs.sh --mode crash --dump | MANUAL | Bug #3 fix |
| E5 | "fix the TCP bug in TableNew" | Sub-session spawned in AndroidStudioProjects/TableNew | MANUAL | |
| E6 | "create a new Android app called SensorApp" | android-new.sh --slug sensorapp --dest ... | MANUAL | |
| E7 | "build TableNew" | build quick invoke → gradlew assembleDebug | MANUAL | |
| E8 | "TableNew ADB not connecting" | adb-connect quick invoke | MANUAL | |
| E9 | Non-Android project prompt | Android routing NOT triggered | MANUAL | |

---

## Bugs

| ID | Description | Fix | Status |
|----|-------------|-----|--------|
| BUG-1 | logs-crash used `--mode crash --mode dump` — last --mode wins, crash filter silently dropped | Added `--dump` boolean flag to android-logs.sh; fixed TableNew CLAUDE.md and android-new.sh template | FIXED |
| BUG-2 | android-new.sh did not create local.properties — new project builds fail with "SDK location not found" | android-new.sh now writes local.properties with sdk.dir | FIXED |
| BUG-3 | Router mapped all log requests including "crash" to logs-dump (default filter) | Added separate logs-crash row in routing table pointing to crash-filter+dump | FIXED |
| BUG-4 | android-deploy.sh exits 1 even on successful local deploy — `[[ -n "$CI_REPO" ]] && rm ...` last line returns 1 (empty var) with `set -e` | Changed to `if [[ -n "$CI_REPO" ]]; then rm ...; fi` | FIXED |
