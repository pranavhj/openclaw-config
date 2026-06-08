#!/bin/bash
# android-new.sh — scaffold a new Android project from the skeleton
# Usage: bash android-new.sh --slug <name> --dest <path>
#
# Example:
#   bash android-new.sh --slug sensorapp --dest /c/Users/prana/AndroidStudioProjects/SensorApp
#
# What it does:
#   1. Copies android-skeleton/ to <dest>
#   2. Replaces APPSLUG placeholder throughout all text files
#   3. Renames the Java package directory
#   4. Runs git init in the new project

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKELETON_DIR="$(cd "$SCRIPT_DIR/../android-skeleton" && pwd)"

# --- Parse args ---
SLUG=""
DEST=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --slug) SLUG="$2"; shift 2 ;;
        --dest) DEST="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$SLUG" || -z "$DEST" ]]; then
    echo "Usage: bash android-new.sh --slug <name> --dest <path>"
    echo "  --slug   short app name, lowercase, no spaces (e.g. sensorapp)"
    echo "  --dest   full destination path (e.g. /c/Users/prana/AndroidStudioProjects/SensorApp)"
    exit 1
fi

if [[ -e "$DEST" ]]; then
    echo "Error: destination already exists: $DEST"
    exit 1
fi

echo "Scaffolding Android project '$SLUG' at $DEST..."

# --- Copy skeleton ---
cp -r "$SKELETON_DIR" "$DEST"

# --- Replace APPSLUG in all text files ---
find "$DEST" -type f ! -name "*.jar" ! -name "*.keystore" ! -name "gradlew.bat" | while read -r f; do
    if file "$f" | grep -q "text"; then
        sed -i "s/APPSLUG/$SLUG/g" "$f"
    fi
done

# --- Rename Java package directory ---
OLD_PKG_DIR="$DEST/app/src/main/java/com/example/APPSLUG"
NEW_PKG_DIR="$DEST/app/src/main/java/com/example/$SLUG"
if [[ -d "$OLD_PKG_DIR" ]]; then
    mv "$OLD_PKG_DIR" "$NEW_PKG_DIR"
fi

# --- Git init ---
cd "$DEST"
git init
git add .
git commit -m "init: scaffold from android-skeleton (slug=$SLUG)"

echo ""
echo "Done! Project created at: $DEST"
echo "Package: com.example.$SLUG"
echo ""
echo "Next steps:"
echo "  1. Add CLAUDE.md (use router Android template, fill in slug/package/device)"
echo "  2. cd $DEST && export JAVA_HOME=/c/Users/prana/jdk17/jdk-17.0.19+10 && ./gradlew assembleDebug"
echo "  3. bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh --project $DEST --device 100.122.101.27:5555"
