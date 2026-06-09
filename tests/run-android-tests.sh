#!/bin/bash
# run-android-tests.sh — automated tests for Android openclaw implementation
# Run from openclaw-config root: bash tests/run-android-tests.sh
# Updates tests/android-test-cases.md with results.

PASS=0; FAIL=0; SKIP=0
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKEL="$ROOT/android-skeleton"
DEPLOY="$ROOT/bin/android-deploy.sh"
LOGS="$ROOT/bin/android-logs.sh"
NEW="$ROOT/bin/android-new.sh"
ANDROID_MD="$ROOT/agents/android.md"
TABLENEW="/c/Users/prana/AndroidStudioProjects/TableNew/CLAUDE.md"
ROUTER="/c/Users/prana/projects/openclaw/CLAUDE.md"
ROUTER_BACKUP="$ROOT/agents/openclaw-CLAUDE.md"
TMP_PROJ="/tmp/android-test-sensorapp"

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'; YELLOW='\033[1;33m'

pass() { echo -e "${GREEN}PASS${NC} [$1] $2"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}FAIL${NC} [$1] $2"; FAIL=$((FAIL+1)); }
skip() { echo -e "${YELLOW}SKIP${NC} [$1] $2 — $3"; SKIP=$((SKIP+1)); }

# Cleanup any prior test run
rm -rf "$TMP_PROJ"

echo "=== android-skeleton structure ==="

check_file() { [[ -f "$1" ]] && pass "$2" "$1 exists" || fail "$2" "$1 MISSING"; }
check_nonempty() { [[ -s "$1" ]] && pass "$2" "$1 non-empty" || fail "$2" "$1 empty or missing"; }
check_contains() { grep -q "$3" "$1" 2>/dev/null && pass "$2" "\"$3\" in $1" || fail "$2" "\"$3\" NOT in $1"; }

check_file "$SKEL/gradlew" S1a
check_file "$SKEL/gradlew.bat" S1b
check_file "$SKEL/gradle/wrapper/gradle-wrapper.jar" S1c
check_file "$SKEL/gradle/wrapper/gradle-wrapper.properties" S1d
check_file "$SKEL/build.gradle" S1e
check_file "$SKEL/settings.gradle" S1f
check_file "$SKEL/gradle.properties" S1g
check_file "$SKEL/app/build.gradle" S1h
check_file "$SKEL/app/src/main/AndroidManifest.xml" S1i
check_file "$SKEL/app/src/main/java/com/example/APPSLUG/MainActivity.java" S1j
check_file "$SKEL/app/src/main/res/layout/activity_main.xml" S1k
check_file "$SKEL/app/src/main/res/values/strings.xml" S1l
check_file "$SKEL/app/src/main/res/values/colors.xml" S1m
check_file "$SKEL/app/src/main/res/values/themes.xml" S1n
check_file "$SKEL/app/src/main/res/drawable/ic_launcher_background.xml" S1o
check_file "$SKEL/app/src/main/res/drawable/ic_launcher_foreground.xml" S1p
check_file "$SKEL/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml" S1q
check_file "$SKEL/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml" S1r
check_file "$SKEL/debug.keystore" S1s
check_file "$SKEL/.gitignore" S1t

check_contains "$SKEL/gradle/wrapper/gradle-wrapper.properties" S2 "gradle-8.2-bin.zip"
check_contains "$SKEL/build.gradle" S3 "8.2.2"
check_contains "$SKEL/app/build.gradle" S4a "namespace"
check_contains "$SKEL/app/build.gradle" S4b "minSdk 24"
check_contains "$SKEL/app/build.gradle" S4c "targetSdk 34"
check_contains "$SKEL/app/build.gradle" S4d "androiddebugkey"
check_contains "$SKEL/app/build.gradle" S5 "APPSLUG"
check_contains "$SKEL/settings.gradle" S6 'rootProject.name = "APPSLUG"'
check_contains "$SKEL/app/src/main/res/values/strings.xml" S7 "APPSLUG"
check_contains "$SKEL/app/src/main/res/values/themes.xml" S8 "Theme.APPSLUG"
check_nonempty "$SKEL/debug.keystore" S11
check_nonempty "$SKEL/gradle/wrapper/gradle-wrapper.jar" S12
# S9: adaptive icons must be XML only — no binary PNGs in mipmap-anydpi-v26/
png_files=$(find "$SKEL/app/src/main/res/mipmap-anydpi-v26/" -name "*.png" 2>/dev/null)
[[ -z "$png_files" ]] && pass S9 "no PNGs in mipmap-anydpi-v26/ (XML only)" || fail S9 "PNG files found: $png_files"
# S10: .gitignore excludes build/, .gradle/, local.properties
check_contains "$SKEL/.gitignore" S10a "build/"
check_contains "$SKEL/.gitignore" S10b ".gradle"
check_contains "$SKEL/.gitignore" S10c "local.properties"

echo ""
echo "=== android-new.sh argument handling ==="

bash "$NEW" 2>/dev/null; [[ $? -ne 0 ]] && pass N1 "no args exits non-zero" || fail N1 "should exit non-zero with no args"
bash "$NEW" --slug only 2>/dev/null; [[ $? -ne 0 ]] && pass N2 "--slug only exits non-zero" || fail N2 "should exit non-zero"
bash "$NEW" --dest /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass N3 "--dest only exits non-zero" || fail N3 "should exit non-zero"
mkdir -p /tmp/android-test-exists && bash "$NEW" --slug x --dest /tmp/android-test-exists 2>/dev/null
[[ $? -ne 0 ]] && pass N4 "existing dest exits non-zero" || fail N4 "should error on existing dest"
rm -rf /tmp/android-test-exists
bash "$NEW" --slug x --dest /tmp/y --unknown 2>/dev/null; [[ $? -ne 0 ]] && pass N5 "unknown flag exits non-zero" || fail N5 "should error on unknown flag"
# Slug validation: hyphens, dots, uppercase, leading digit all rejected
bash "$NEW" --slug "my-app" --dest /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass N5a "hyphen slug rejected" || fail N5a "hyphen slug should be rejected"
bash "$NEW" --slug "MyApp" --dest /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass N5b "uppercase slug rejected" || fail N5b "uppercase slug should be rejected"
bash "$NEW" --slug "2app" --dest /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass N5c "digit-leading slug rejected" || fail N5c "digit-leading slug should be rejected"
bash "$NEW" --slug "app.one" --dest /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass N5d "dot-containing slug rejected" || fail N5d "dot slug should be rejected"

echo ""
echo "=== android-new.sh scaffolding (running --slug sensorapp) ==="

bash "$NEW" --slug sensorapp --dest "$TMP_PROJ" --app-tag SensorApp --github-repo pranavhj/SensorApp
if [[ $? -ne 0 ]]; then
    fail N6 "android-new.sh failed — skipping N7-N29"
else
    pass N6 "android-new.sh ran successfully"
    check_contains "$TMP_PROJ/app/build.gradle" N7 'applicationId "com.example.sensorapp"'
    check_contains "$TMP_PROJ/settings.gradle" N8 'rootProject.name = "sensorapp"'
    check_contains "$TMP_PROJ/app/src/main/AndroidManifest.xml" N9 "Theme.sensorapp"
    check_contains "$TMP_PROJ/app/src/main/java/com/example/sensorapp/MainActivity.java" N10 "package com.example.sensorapp"
    check_contains "$TMP_PROJ/app/src/main/res/values/strings.xml" N11 "sensorapp"
    [[ -d "$TMP_PROJ/app/src/main/java/com/example/sensorapp" ]] && pass N12 "package dir renamed to sensorapp (main)" || fail N12 "sensorapp/ dir missing in main"
    [[ ! -d "$TMP_PROJ/app/src/main/java/com/example/APPSLUG" ]] && pass N13 "APPSLUG/ dir gone (main)" || fail N13 "APPSLUG/ dir still exists in main"
    # N12b/N13b: test and androidTest dirs also renamed
    if [[ -d "$TMP_PROJ/app/src/test/java/com/example/APPSLUG" ]]; then
        fail N12b "APPSLUG/ dir still exists in test/"
    elif [[ -d "$TMP_PROJ/app/src/test" ]]; then
        [[ -d "$TMP_PROJ/app/src/test/java/com/example/sensorapp" ]] && pass N12b "package dir renamed in test/" || fail N12b "sensorapp/ dir missing in test/"
    else
        pass N12b "no test/ source dir in skeleton (ok)"
    fi
    if [[ -d "$TMP_PROJ/app/src/androidTest/java/com/example/APPSLUG" ]]; then
        fail N12c "APPSLUG/ dir still exists in androidTest/"
    elif [[ -d "$TMP_PROJ/app/src/androidTest" ]]; then
        [[ -d "$TMP_PROJ/app/src/androidTest/java/com/example/sensorapp" ]] && pass N12c "package dir renamed in androidTest/" || fail N12c "sensorapp/ dir missing in androidTest/"
    else
        pass N12c "no androidTest/ source dir in skeleton (ok)"
    fi
    # N13b: verify no APPSLUG remains in any text file (completeness check)
    remaining_appslug=$(find "$TMP_PROJ" -type f ! -name "*.jar" ! -name "*.keystore" ! -name "*.class" | xargs grep -rl "APPSLUG" 2>/dev/null)
    [[ -z "$remaining_appslug" ]] && pass N13b "no APPSLUG left in any text file" || fail N13b "APPSLUG still in: $remaining_appslug"
    ORIG_JAR="$SKEL/gradle/wrapper/gradle-wrapper.jar"
    NEW_JAR="$TMP_PROJ/gradle/wrapper/gradle-wrapper.jar"
    [[ $(wc -c < "$NEW_JAR") -eq $(wc -c < "$ORIG_JAR") ]] && pass N14 "gradle-wrapper.jar byte count matches" || fail N14 "gradle-wrapper.jar differs"
    check_nonempty "$TMP_PROJ/debug.keystore" N15
    cd "$TMP_PROJ" && git log --oneline 2>/dev/null | grep -q "init" && pass N16 "git init + commit present" || fail N16 "no initial commit"
    check_contains "$TMP_PROJ/local.properties" N17 "sdk.dir"

    check_file "$TMP_PROJ/CLAUDE.md" N18
    check_contains "$TMP_PROJ/CLAUDE.md" N19 "SensorApp"
    check_contains "$TMP_PROJ/CLAUDE.md" N20 "SensorApp"
    check_contains "$TMP_PROJ/CLAUDE.md" N21 "pranavhj/SensorApp"
    check_contains "$TMP_PROJ/CLAUDE.md" N22 "pranavhj/SensorApp"
    check_contains "$TMP_PROJ/CLAUDE.md" N23 "com.example.sensorapp"
    check_contains "$TMP_PROJ/CLAUDE.md" N24 "$TMP_PROJ"
    check_contains "$TMP_PROJ/CLAUDE.md" N25 "\-\-mode default \-\-dump"
    check_contains "$TMP_PROJ/CLAUDE.md" N26 "\-\-mode crash \-\-dump"
    # logs entry should NOT have --dump
    grep -q "# logs " "$TMP_PROJ/CLAUDE.md" && \
        ! grep -A2 "# logs " "$TMP_PROJ/CLAUDE.md" | grep -q "\-\-dump" && \
        pass N27 "logs entry has no --dump" || fail N27 "logs entry incorrectly has --dump"
    N28_FAIL=0
    for entry in "build" "deploy" "deploy-ci" "logs-dump" "logs-crash" "logs" "adb-connect" "test-ping" "test-inline" "test-screenshot" "test-state"; do
        grep -q "# $entry" "$TMP_PROJ/CLAUDE.md" 2>/dev/null || { fail N28 "missing quick invoke: $entry"; N28_FAIL=1; }
    done
    [[ $N28_FAIL -eq 0 ]] && pass N28 "all 11 quick invoke entries present"
    check_contains "$TMP_PROJ/CLAUDE.md" N29 "android.md"
fi

echo ""
echo "=== android-deploy.sh argument handling ==="

bash "$DEPLOY" 2>/dev/null; [[ $? -ne 0 ]] && pass D1 "no args exits non-zero" || fail D1 "should exit non-zero"
bash "$DEPLOY" --project /tmp/x 2>/dev/null; [[ $? -ne 0 ]] && pass D2 "missing --device exits non-zero" || fail D2 "should exit non-zero"
bash "$DEPLOY" --device 1.2.3.4:5555 2>/dev/null; [[ $? -ne 0 ]] && pass D3 "missing --project exits non-zero" || fail D3 "should exit non-zero"
bash "$DEPLOY" --project /tmp/nonexistent --device 1.2.3.4:5555 2>/dev/null; [[ $? -ne 0 ]] && pass D4 "missing app/build.gradle exits non-zero" || fail D4 "should error"
bash "$DEPLOY" --project /tmp --device x --unknown 2>/dev/null; [[ $? -ne 0 ]] && pass D5 "unknown flag exits non-zero" || fail D5 "should error"

echo ""
echo "=== android-deploy.sh package detection ==="

TMPG=$(mktemp -d)
mkdir -p "$TMPG/app"
echo 'applicationId "com.example.foo"' > "$TMPG/app/build.gradle"
PKG=$(grep -m1 'applicationId' "$TMPG/app/build.gradle" | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
[[ "$PKG" == "com.example.foo" ]] && pass D6 "Groovy DSL applicationId parsed" || fail D6 "Got: $PKG"

echo 'applicationId = "com.example.bar"' > "$TMPG/app/build.gradle"
PKG=$(grep -m1 'applicationId' "$TMPG/app/build.gradle" | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
[[ "$PKG" == "com.example.bar" ]] && pass D7 "Kotlin DSL applicationId parsed" || fail D7 "Got: $PKG"

echo 'namespace "com.example.baz"' > "$TMPG/app/build.gradle"
bash "$DEPLOY" --project "$TMPG" --device 1.2.3.4:5555 2>/dev/null; [[ $? -ne 0 ]] && pass D8 "missing applicationId exits non-zero" || fail D8 "should error"
# D8b: comment line with applicationId must not be parsed
echo $'// applicationId "com.example.commented"\napplicationId "com.example.real"' > "$TMPG/app/build.gradle"
PKG=$(grep -v '^\s*//' "$TMPG/app/build.gradle" | grep -m1 'applicationId' | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
[[ "$PKG" == "com.example.real" ]] && pass D8b "commented applicationId line skipped" || fail D8b "expected com.example.real, got: $PKG"
# D9b: build.gradle.kts detected when build.gradle absent
rm -f "$TMPG/app/build.gradle"
echo 'applicationId = "com.example.kts"' > "$TMPG/app/build.gradle.kts"
PKG=$(grep -v '^\s*//' "$TMPG/app/build.gradle.kts" | grep -m1 'applicationId' | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
[[ "$PKG" == "com.example.kts" ]] && pass D9b "build.gradle.kts applicationId parsed" || fail D9b "expected com.example.kts, got: $PKG"
rm -rf "$TMPG"

echo ""
echo "=== android-deploy.sh unreachable device ==="
TMPG=$(mktemp -d); mkdir -p "$TMPG/app"
echo 'applicationId "com.example.test"' > "$TMPG/app/build.gradle"
# 127.0.0.1:5554 — localhost wrong port, always immediately refused, never in adb devices
out=$(bash "$DEPLOY" --project "$TMPG" --device 127.0.0.1:5554 2>&1)
rc=$?
rm -rf "$TMPG"
if [[ $rc -ne 0 ]] && echo "$out" | grep -qi "not reachable"; then
    pass D10 "unreachable device → 'not reachable' error, exits non-zero"
else
    fail D10 "expected non-zero + 'not reachable' (rc=$rc)"
fi

echo ""
echo "=== android-logs.sh argument handling ==="

bash "$LOGS" 2>/dev/null; [[ $? -ne 0 ]] && pass L1 "no args exits non-zero" || fail L1 "should exit non-zero"
bash "$LOGS" --device 1.2.3.4:5555 2>/dev/null; [[ $? -ne 0 ]] && pass L2 "missing --tag exits non-zero" || fail L2 "should exit non-zero"
bash "$LOGS" --tag MyApp 2>/dev/null; [[ $? -ne 0 ]] && pass L3 "missing --device exits non-zero" || fail L3 "should exit non-zero"
bash "$LOGS" --tag MyApp --device x --unknown 2>/dev/null; [[ $? -ne 0 ]] && pass L4 "unknown flag exits non-zero" || fail L4 "should exit non-zero"
# L4b: invalid --mode value exits non-zero
bash "$LOGS" --tag MyApp --device 1.2.3.4:5555 --mode typo 2>/dev/null; [[ $? -ne 0 ]] && pass L4b "invalid --mode exits non-zero" || fail L4b "invalid --mode should be rejected"

echo ""
echo "=== script quality (inspection) ==="
grep -q "pipefail" "$DEPLOY" && pass Q1 "android-deploy.sh has pipefail" || fail Q1 "android-deploy.sh missing pipefail"
grep -q "pipefail" "$LOGS" && pass Q2 "android-logs.sh has pipefail" || fail Q2 "android-logs.sh missing pipefail"
grep -q "pipefail" "$NEW" && pass Q3 "android-new.sh has pipefail" || fail Q3 "android-new.sh missing pipefail"
grep -q 'grep -F' "$DEPLOY" && pass Q4 "android-deploy.sh uses grep -F for device check" || fail Q4 "android-deploy.sh should use grep -F"
grep -q 'grep -F' "$LOGS" && pass Q5 "android-logs.sh uses grep -F for device check" || fail Q5 "android-logs.sh should use grep -F"
grep -q '"device\$"' "$DEPLOY" && pass Q6 "android-deploy.sh checks device state (not just presence)" || fail Q6 "android-deploy.sh should verify 'device' state"
grep -q '"device\$"' "$LOGS" && pass Q7 "android-logs.sh checks device state (not just presence)" || fail Q7 "android-logs.sh should verify 'device' state"
grep -q 'grep -v.*\/\/' "$DEPLOY" && pass Q8 "android-deploy.sh filters comment lines from applicationId grep" || fail Q8 "android-deploy.sh should skip comment lines"
grep -q 'build.gradle.kts' "$DEPLOY" && pass Q9 "android-deploy.sh supports build.gradle.kts" || fail Q9 "android-deploy.sh missing kts support"
grep -q 'INSTALL_FAILED_UPDATE_INCOMPATIBLE\|INCONSISTENT_CERTIFICATES' "$DEPLOY" && pass Q10 "android-deploy.sh sig mismatch recovery is targeted" || fail Q10 "sig mismatch recovery should check error text"
grep -q 'trap' "$DEPLOY" && pass Q11 "android-deploy.sh has trap for CI temp cleanup" || fail Q11 "android-deploy.sh missing trap for CI cleanup"
grep -q '\$# -ge 2' "$DEPLOY" && pass Q12 "android-deploy.sh has shift guards" || fail Q12 "android-deploy.sh missing shift guards"
grep -q '\$# -ge 2' "$NEW" && pass Q13 "android-new.sh has shift guards" || fail Q13 "android-new.sh missing shift guards"
grep -q '".*\$SLUG.*"\|'"'[a-z].*regex'" "$NEW" && pass Q14 "android-new.sh has slug validation" || fail Q14 "android-new.sh missing slug validation"
# gitignore should not have duplicate local.properties
dup=$(grep -c "local.properties" "$SKEL/.gitignore" 2>/dev/null)
[[ "$dup" -le 1 ]] && pass Q15 ".gitignore has no duplicate local.properties" || fail Q15 ".gitignore has $dup local.properties entries"
# CLAUDE.md generated by android-new.sh should quote DEST in deploy commands
grep -q '"$DEST"' "$NEW" && pass Q16 'android-new.sh quotes $DEST in CLAUDE.md deploy commands' || fail Q16 'android-new.sh should quote $DEST'

echo ""
echo "=== android-logs.sh mode logic (script inspection) ==="

# L5: default mode (*) filter: *:S, TAG:V, AndroidRuntime:E
grep -qF '"*:S" "${TAG}:V" AndroidRuntime:E' "$LOGS" && pass L5 "default mode filter: *:S TAG:V AndroidRuntime:E" || fail L5 "default mode filter not found"
# Test that --dump flag is parsed as a separate boolean
grep -q "\-\-dump)[[:space:]]*DUMP=1" "$LOGS" && pass L8 "--dump flag sets DUMP=1" || fail L8 "--dump flag not found in script"
# Test legacy --mode dump still handled
grep -q '"dump"' "$LOGS" && pass L10 "legacy --mode dump handled" || fail L10 "legacy --mode dump not handled"
# Verify crash mode uses correct filter
grep -q 'AndroidRuntime:E.*TAG.*:E\|${TAG}:E' "$LOGS" && pass L7 "crash mode has AndroidRuntime:E + TAG:E filter" || fail L7 "crash filter not found"
# Verify --dump prints snapshot label
grep -q "snapshot" "$LOGS" && pass L12 "snapshot label in script" || fail L12 "snapshot label missing"
grep -q "streaming" "$LOGS" && pass L13 "streaming label in script" || fail L13 "streaming label missing"
# Verify Bug #1 fix: --mode crash --dump should work (DUMP is independent of MODE)
grep -q "DUMP_FLAG=\"-d\"" "$LOGS" && pass L9 "DUMP_FLAG set from --dump (Bug #1 fix)" || fail L9 "DUMP_FLAG not set correctly"

echo ""
echo "=== agents/android.md content ==="

check_file "$ANDROID_MD" A1
check_file "$ROOT/agents/android-test-engine.md" A1b
for path in "platform-tools/adb.exe" "jdk17" "Android/Sdk" "GitHub CLI" "android-deploy" "android-logs" "android-new" "android-skeleton" "discord-send" "agent-smart"; do
    check_contains "$ANDROID_MD" A2 "$path"
done
check_contains "$ANDROID_MD" A3a "100.122.101.27:5555"
check_contains "$ANDROID_MD" A3b "10.0.0.122:5555"
check_contains "$ANDROID_MD" A4a "8.2.2"
check_contains "$ANDROID_MD" A4b "gradle-8.2\|Gradle.*8.2\| 8.2 "
check_contains "$ANDROID_MD" A4c "JDK 17\|Java.*17\|17.*Temurin"
check_contains "$ANDROID_MD" A4d "VERSION_1_8"
check_contains "$ANDROID_MD" A5a "storepass"
check_contains "$ANDROID_MD" A5b "androiddebugkey"
check_contains "$ANDROID_MD" A7 "Discord"
check_contains "$ANDROID_MD" A10a "temurin"
check_contains "$ANDROID_MD" A10b "app-debug"
check_contains "$ANDROID_MD" A11 "gradlew"
check_contains "$ANDROID_MD" A13 "android-new.sh"

echo ""
echo "=== TableNew/CLAUDE.md content ==="

check_file "$TABLENEW" T1
check_contains "$TABLENEW" T2 "Sub-session rules"
check_contains "$TABLENEW" T3a "platform-tools/adb.exe"
check_contains "$TABLENEW" T3b "jdk17"
check_contains "$TABLENEW" T4 "100.122.101.27:5555"
check_contains "$TABLENEW" T5 "com.example.tablenew"
check_contains "$TABLENEW" T6 "pranavhj/TableNew"
check_contains "$TABLENEW" T7a "MainActivity.java"
check_contains "$TABLENEW" T7b "TCPClient.java"
for entry in "build" "deploy" "deploy-ci" "logs" "logs-dump" "logs-crash" "adb-connect"; do
    grep -q "# $entry" "$TABLENEW" && pass T8 "quick invoke: $entry" || fail T8 "MISSING quick invoke: $entry"
done
check_contains "$TABLENEW" T9 "/c/Users/prana/AndroidStudioProjects/TableNew"
check_contains "$TABLENEW" T10 "100.122.101.27:5555"
check_contains "$TABLENEW" T11 "\-\-mode default \-\-dump\|\-\-mode dump"
check_contains "$TABLENEW" T12 "\-\-mode crash \-\-dump"
# T13: logs (streaming) entry must NOT have --dump; match "# logs " (with space/paren) to exclude logs-dump/logs-crash
logs_stream_cmd=$(grep -A3 "^# logs " "$TABLENEW" | grep -v "^# logs ")
if echo "$logs_stream_cmd" | grep -qF -- "--dump"; then
    fail T13 "logs streaming entry incorrectly has --dump"
else
    pass T13 "logs streaming entry has no --dump"
fi
check_contains "$TABLENEW" T14 "adb.exe connect 100.122.101.27:5555"
check_contains "$TABLENEW" T15a "AGP.*8.2.2\|8.2.2.*AGP"
check_contains "$TABLENEW" T15b "minSdk.*24\|24.*minSdk"
check_contains "$TABLENEW" T16 "android.md"

echo ""
echo "=== Router openclaw/CLAUDE.md ==="

check_contains "$ROUTER" R1 "Android projects"
check_contains "$ROUTER" R2 "app/build.gradle"
check_contains "$ROUTER" R3 "AndroidManifest.xml"
grep -qi "create.*android\|new.*android\|android.*new" "$ROUTER" && pass R4 "create/new Android project detection present" || fail R4 "create/new Android project detection missing"
check_contains "$ROUTER" R5 "logs-crash"
check_contains "$ROUTER" R6 "deploy"
check_contains "$ROUTER" R7 "deploy-ci"
check_contains "$ROUTER" R8 "logs-dump"
check_contains "$ROUTER" R9 "logs-crash"
check_contains "$ROUTER" R10 "never streaming"
check_contains "$ROUTER" R11 "build"
check_contains "$ROUTER" R12 "adb-connect"
check_contains "$ROUTER" R13 "sub-session"
check_contains "$ROUTER" R14 "android-new.sh"
! grep -q "New Android Project Template" "$ROUTER" && pass R15 "template block absent (lean router)" || fail R15 "template block still present — router is bloated"

echo ""
echo "=== Sync check ==="

diff "$ROUTER" "$ROUTER_BACKUP" > /dev/null 2>&1 && pass Y1 "openclaw/CLAUDE.md == agents/openclaw-CLAUDE.md" || fail Y1 "FILES DIFFER — run: cp $ROUTER $ROUTER_BACKUP"

echo ""
echo "=== android-skeleton debug source set ==="

check_file "$SKEL/app/src/debug/AndroidManifest.xml" SD1
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/DebugTestServer.java" SD2
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/ScriptExecutor.java" SD3
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/TestBridge.java" SD4
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/UiHelper.java" SD5
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/ScreenshotHelper.java" SD6
check_file "$SKEL/app/src/debug/java/com/example/APPSLUG/testing/TestServerInitProvider.java" SD7
check_contains "$SKEL/app/src/debug/AndroidManifest.xml" SD8 "INTERNET"
check_contains "$SKEL/app/src/debug/AndroidManifest.xml" SD9 "TestServerInitProvider"
check_contains "$SKEL/app/build.gradle" SD10 "debugImplementation.*nanohttpd"
check_contains "$SKEL/app/build.gradle" SD11 "debugImplementation.*bsh"

echo ""
echo "=== android-new.sh debug source set rename ==="

# N30: debug source set package dir renamed correctly in scaffolded project
if [[ -d "$TMP_PROJ" ]]; then
    [[ -d "$TMP_PROJ/app/src/debug/java/com/example/sensorapp/testing" ]] && pass N30 "debug testing dir renamed to sensorapp" || fail N30 "debug testing dir not renamed"
    [[ ! -d "$TMP_PROJ/app/src/debug/java/com/example/APPSLUG" ]] && pass N31 "APPSLUG dir gone in debug/" || fail N31 "APPSLUG dir still exists in debug/"
    # N32: APPSLUG replaced in debug Java files
    debug_appslug=$(find "$TMP_PROJ/app/src/debug" -name "*.java" -exec grep -l "APPSLUG" {} \; 2>/dev/null)
    [[ -z "$debug_appslug" ]] && pass N32 "no APPSLUG in debug Java files" || fail N32 "APPSLUG still in: $debug_appslug"
else
    skip N30 "debug dir rename" "scaffolded project not available"
    skip N31 "APPSLUG dir gone" "scaffolded project not available"
    skip N32 "APPSLUG in debug Java" "scaffolded project not available"
fi

echo ""
echo "=== android-test.sh ==="

TEST_SH="$ROOT/bin/android-test.sh"
check_file "$TEST_SH" TS1
grep -q "pipefail" "$TEST_SH" && pass TS2 "android-test.sh has pipefail" || fail TS2 "android-test.sh missing pipefail"
grep -q '\$# -ge 2' "$TEST_SH" && pass TS3 "android-test.sh has shift guards" || fail TS3 "android-test.sh missing shift guards"
bash "$TEST_SH" 2>/dev/null; [[ $? -ne 0 ]] && pass TS4 "no args exits non-zero" || fail TS4 "should exit non-zero"
bash "$TEST_SH" --device 1.2.3.4:5555 2>/dev/null; [[ $? -ne 0 ]] && pass TS5 "no action exits non-zero" || fail TS5 "should exit non-zero with no action"
bash "$TEST_SH" --device 1.2.3.4:5555 --unknown 2>/dev/null; [[ $? -ne 0 ]] && pass TS6 "unknown flag exits non-zero" || fail TS6 "should error on unknown flag"
bash "$TEST_SH" --device 1.2.3.4:5555 --script /tmp/nonexistent.bsh 2>/dev/null; [[ $? -ne 0 ]] && pass TS7 "missing script file exits non-zero" || fail TS7 "should error on missing script"
grep -q "trap" "$TEST_SH" && pass TS8 "android-test.sh has trap for cleanup" || fail TS8 "android-test.sh missing trap"
grep -q "/ping" "$TEST_SH" && pass TS9 "android-test.sh has /ping endpoint" || fail TS9 "/ping missing"
grep -q "/exec" "$TEST_SH" && pass TS10 "android-test.sh has /exec endpoint" || fail TS10 "/exec missing"
grep -q "/screenshot" "$TEST_SH" && pass TS11 "android-test.sh has /screenshot endpoint" || fail TS11 "/screenshot missing"
grep -q "/state" "$TEST_SH" && pass TS12 "android-test.sh has /state endpoint" || fail TS12 "/state missing"

echo ""
echo "=== /tmp path check ==="
TMP_RESOLVED=$(bash -c 'echo /tmp')
[[ -n "$TMP_RESOLVED" && -d "$TMP_RESOLVED" ]] && pass D19 "/tmp resolves to: $TMP_RESOLVED" || fail D19 "/tmp not a valid directory: $TMP_RESOLVED"

echo ""
echo "========================================"
echo "Results: ${GREEN}${PASS} PASS${NC}  ${RED}${FAIL} FAIL${NC}  ${YELLOW}${SKIP} SKIP${NC}"
echo "Manual tests remaining — see tests/android-test-cases.md"
echo "========================================"

# Cleanup
rm -rf "$TMP_PROJ"
