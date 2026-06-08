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

set -eo pipefail

ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"
GH="/c/Program Files/GitHub CLI/gh.exe"
JAVA_HOME_PATH="/c/Users/prana/jdk17/jdk-17.0.19+10"

# --- Parse args ---
PROJECT=""
DEVICE=""
CI_REPO=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project) [[ $# -ge 2 ]] || { echo "Error: --project requires a value"; exit 1; }
                   PROJECT="$2"; shift 2 ;;
        --device)  [[ $# -ge 2 ]] || { echo "Error: --device requires a value"; exit 1; }
                   DEVICE="$2";  shift 2 ;;
        --ci)      [[ $# -ge 2 ]] || { echo "Error: --ci requires a value"; exit 1; }
                   CI_REPO="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$PROJECT" || -z "$DEVICE" ]]; then
    echo "Usage: bash android-deploy.sh --project <path> --device <ip:port> [--ci <repo>]"
    exit 1
fi

# --- Read package name from build.gradle ---
BUILD_GRADLE=""
if [[ -f "$PROJECT/app/build.gradle" ]]; then
    BUILD_GRADLE="$PROJECT/app/build.gradle"
elif [[ -f "$PROJECT/app/build.gradle.kts" ]]; then
    BUILD_GRADLE="$PROJECT/app/build.gradle.kts"
else
    echo "Error: $PROJECT/app/build.gradle not found"
    exit 1
fi
# Handles both: applicationId "com.example.foo" and applicationId = "com.example.foo"
# Excludes comment lines
PACKAGE=$(grep -v '^\s*//' "$BUILD_GRADLE" | grep -m1 'applicationId' | sed 's/.*applicationId[[:space:]]*=\?[[:space:]]*"\([^"]*\)".*/\1/')
if [[ -z "$PACKAGE" ]]; then
    echo "Error: could not read applicationId from $BUILD_GRADLE"
    exit 1
fi
echo "Package: $PACKAGE"

# --- Connect to device ---
echo "Connecting to $DEVICE..."
"$ADB" connect "$DEVICE" 2>&1 || true
sleep 1

if ! "$ADB" devices | grep -F "$DEVICE" | grep -q "device$"; then
    echo "Error: device $DEVICE not reachable or not authorized after connect attempt"
    "$ADB" devices
    exit 1
fi

# --- Get APK ---
TMP_DIR=""
if [[ -n "$CI_REPO" ]]; then
    # CI path: download from GitHub Actions
    TMP_DIR="/tmp/android-deploy-$PACKAGE"
    trap 'rm -rf "$TMP_DIR"' EXIT
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
INSTALL_OUT=$("$ADB" -s "$DEVICE" install -r "$APK" 2>&1)
INSTALL_EXIT=$?
echo "$INSTALL_OUT"
if [[ $INSTALL_EXIT -eq 0 ]]; then
    echo "Done."
else
    # Only attempt uninstall+reinstall for signature mismatch errors
    if echo "$INSTALL_OUT" | grep -qE "INSTALL_FAILED_UPDATE_INCOMPATIBLE|INCONSISTENT_CERTIFICATES"; then
        echo "Signature mismatch — uninstalling and reinstalling (app data will be lost)..."
        "$ADB" -s "$DEVICE" uninstall "$PACKAGE" || true
        "$ADB" -s "$DEVICE" install "$APK" && echo "Done." || {
            echo "Install failed after uninstall. Check device logs."
            exit 1
        }
    else
        echo "Install failed. Check device logs."
        exit 1
    fi
fi
