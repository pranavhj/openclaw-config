#!/bin/bash
# android-deploy.sh — build (or download) and install an Android APK on a device
#
# Usage:
#   bash android-deploy.sh --project <path> --device <ip:port>
#   bash android-deploy.sh --project <path> --device <ip:port> --ci <repo>
#
# Flags:
#   --project <path>   absolute path to Android project root (required)
#   --device  <ip:port> ADB device address, e.g. 100.122.101.27:5555 (required)
#   --ci <repo>        GitHub repo (e.g. pranavhj/TableNew) — download latest artifact
#                      instead of building locally
#
# Local path:  cd <project>, export JAVA_HOME, ./gradlew assembleDebug, adb install
# CI path:     gh run download latest success → /tmp/, adb install
#
# Note: signature mismatch recovery uninstalls the app (loses app data).

set -e

ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"
GH="/c/Program Files/GitHub CLI/gh.exe"
JAVA_HOME_PATH="/c/Users/prana/jdk17/jdk-17.0.19+10"

# --- Parse args ---
PROJECT=""
DEVICE=""
CI_REPO=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project) PROJECT="$2"; shift 2 ;;
        --device)  DEVICE="$2";  shift 2 ;;
        --ci)      CI_REPO="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$PROJECT" || -z "$DEVICE" ]]; then
    echo "Usage: bash android-deploy.sh --project <path> --device <ip:port> [--ci <repo>]"
    exit 1
fi

# --- Read package name from build.gradle ---
BUILD_GRADLE="$PROJECT/app/build.gradle"
if [[ ! -f "$BUILD_GRADLE" ]]; then
    echo "Error: $BUILD_GRADLE not found"
    exit 1
fi
# Handles both: applicationId "com.example.foo" and applicationId = "com.example.foo"
PACKAGE=$(grep -m1 'applicationId' "$BUILD_GRADLE" | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
if [[ -z "$PACKAGE" ]]; then
    echo "Error: could not read applicationId from $BUILD_GRADLE"
    exit 1
fi
echo "Package: $PACKAGE"

# --- Connect to device ---
echo "Connecting to $DEVICE..."
"$ADB" connect "$DEVICE" 2>&1 || true
sleep 1

if ! "$ADB" devices | grep -q "^${DEVICE}[[:space:]]"; then
    echo "Error: device $DEVICE not reachable after connect attempt"
    "$ADB" devices
    exit 1
fi

# --- Get APK ---
if [[ -n "$CI_REPO" ]]; then
    # CI path: download from GitHub Actions
    TMP_DIR="/tmp/android-deploy-$PACKAGE"
    rm -rf "$TMP_DIR" && mkdir -p "$TMP_DIR"
    echo "Finding latest successful run in $CI_REPO..."
    RUN_ID=$("$GH" run list --repo "$CI_REPO" --status success --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
    if [[ -z "$RUN_ID" ]]; then
        echo "Error: no successful runs found in $CI_REPO"
        exit 1
    fi
    echo "Downloading artifact from run $RUN_ID..."
    "$GH" run download "$RUN_ID" --repo "$CI_REPO" -n app-debug -D "$TMP_DIR"
    APK="$TMP_DIR/app-debug.apk"
else
    # Local path: build from source
    echo "Building..."
    export JAVA_HOME="$JAVA_HOME_PATH"
    cd "$PROJECT"
    ./gradlew assembleDebug --quiet || { echo "Build failed."; exit 1; }
    APK="$PROJECT/app/build/outputs/apk/debug/app-debug.apk"
fi

if [[ ! -f "$APK" ]]; then
    echo "Error: APK not found at $APK"
    exit 1
fi

# --- Install ---
echo "Installing $APK on $DEVICE..."
"$ADB" -s "$DEVICE" install -r "$APK" && echo "Done." || {
    echo "Install failed — trying signature mismatch recovery (uninstall + reinstall, app data lost)..."
    "$ADB" -s "$DEVICE" uninstall "$PACKAGE" || true
    "$ADB" -s "$DEVICE" install "$APK" && echo "Done." || {
        echo "Install failed after uninstall. Check device logs."
        exit 1
    }
}

# Cleanup CI temp dir
[[ -n "$CI_REPO" ]] && rm -rf "$TMP_DIR"
