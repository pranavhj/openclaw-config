#!/bin/bash
# android-new.sh — scaffold a new Android project from the skeleton + generate CLAUDE.md
#
# Usage:
#   bash android-new.sh --slug <name> --dest <path> [--app-tag <Tag>] [--github-repo <owner/repo>]
#
# Flags:
#   --slug        short app name, lowercase letters/digits, no hyphens (e.g. sensorapp) [required]
#   --dest        full destination path                                                  [required]
#   --app-tag     display name / logcat tag (default: capitalized slug)
#   --github-repo GitHub repo slug (default: pranavhj/<slug>)
#
# What it does:
#   1. Copies android-skeleton/ to <dest>
#   2. Replaces APPSLUG placeholder throughout all text files
#   3. Renames the Java package directories (main, test, androidTest)
#   4. Generates CLAUDE.md with all values filled in
#   5. Runs git init + initial commit

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKELETON_DIR="$(cd "$SCRIPT_DIR/../android-skeleton" && pwd)"

# --- Parse args ---
SLUG=""
DEST=""
APP_TAG=""
GITHUB_REPO=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --slug)        [[ $# -ge 2 ]] || { echo "Error: --slug requires a value"; exit 1; }
                       SLUG="$2";        shift 2 ;;
        --dest)        [[ $# -ge 2 ]] || { echo "Error: --dest requires a value"; exit 1; }
                       DEST="$2";        shift 2 ;;
        --app-tag)     [[ $# -ge 2 ]] || { echo "Error: --app-tag requires a value"; exit 1; }
                       APP_TAG="$2";     shift 2 ;;
        --github-repo) [[ $# -ge 2 ]] || { echo "Error: --github-repo requires a value"; exit 1; }
                       GITHUB_REPO="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$SLUG" || -z "$DEST" ]]; then
    echo "Usage: bash android-new.sh --slug <name> --dest <path> [--app-tag <Tag>] [--github-repo owner/repo]"
    exit 1
fi

# Validate slug: lowercase letters and digits only, must start with a letter
if [[ ! "$SLUG" =~ ^[a-z][a-z0-9]*$ ]]; then
    echo "Error: --slug must be lowercase letters/digits only, starting with a letter (e.g. sensorapp, myapp2)"
    exit 1
fi

if [[ -e "$DEST" ]]; then
    echo "Error: destination already exists: $DEST"
    exit 1
fi

# Defaults
[[ -z "$APP_TAG" ]]     && APP_TAG="$(echo "$SLUG" | sed 's/./\u&/')"
[[ -z "$GITHUB_REPO" ]] && GITHUB_REPO="pranavhj/$SLUG"

PACKAGE="com.example.$SLUG"

echo "Scaffolding Android project '$SLUG' at $DEST..."
echo "  App tag:     $APP_TAG"
echo "  Package:     $PACKAGE"
echo "  GitHub repo: $GITHUB_REPO"

# --- Copy skeleton ---
cp -r "$SKELETON_DIR" "$DEST"

# --- Replace APPSLUG in all text files (extension-based, no `file` command) ---
# Process substitution avoids find|while subshell — errors propagate correctly
while IFS= read -r f; do
    case "$f" in
        *.java|*.xml|*.gradle|*.properties|*.md|*.txt|*.json|*.yaml|*.yml|*.sh|*.bat|*.pro|gradlew)
            sed -i "s/APPSLUG/$SLUG/g" "$f"
            ;;
    esac
done < <(find "$DEST" -type f ! -name "*.jar" ! -name "*.keystore")

# --- Rename Java package directories (main, test, androidTest) ---
for SRC_TYPE in main test androidTest; do
    OLD_PKG_DIR="$DEST/app/src/$SRC_TYPE/java/com/example/APPSLUG"
    NEW_PKG_DIR="$DEST/app/src/$SRC_TYPE/java/com/example/$SLUG"
    [[ -d "$OLD_PKG_DIR" ]] && mv "$OLD_PKG_DIR" "$NEW_PKG_DIR"
done

# --- Write local.properties (SDK location for CLI builds) ---
echo 'sdk.dir=C\:\\Users\\prana\\AppData\\Local\\Android\\Sdk' > "$DEST/local.properties"

# --- Generate CLAUDE.md ---
cat > "$DEST/CLAUDE.md" <<CLAUDEMD
# $APP_TAG — Android sub-session

You are running inside the $APP_TAG Android project. Do NOT do project detection or spawn sub-sessions.

## Sub-session rules
1. Skim \`PROGRESS.md\` for current state
2. Do the work (edit files in this directory)
3. Update \`PROGRESS.md\`
4. Send response via \`discord-send.py\`
5. Output: SENT

Send using:
\`\`\`
python D:\\MyData\\Software\\openclaw-config\\bin\\discord-send.py --target <target> --message "<text>"
\`\`\`

---

## Paths

| What | Path |
|------|------|
| ADB | \`/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe\` |
| JAVA_HOME | \`/c/Users/prana/jdk17/jdk-17.0.19+10\` |
| GitHub CLI | \`/c/Program Files/GitHub CLI/gh.exe\` |
| android-deploy | \`D:\\MyData\\Software\\openclaw-config\\bin\\android-deploy.sh\` |
| android-logs | \`D:\\MyData\\Software\\openclaw-config\\bin\\android-logs.sh\` |
| discord-send | \`D:\\MyData\\Software\\openclaw-config\\bin\\discord-send.py\` |

---

## Device

- **Tailscale (stable):** \`100.122.101.27:5555\` ← always use this
- **Local (may change):** \`10.0.0.122:5555\`

---

## Project

- **Package:** \`$PACKAGE\`
- **GitHub repo:** \`$GITHUB_REPO\`
- **Source:** \`app/src/main/java/com/example/$SLUG/\`

---

## Quick invoke

\`\`\`bash
# build only
export JAVA_HOME="/c/Users/prana/jdk17/jdk-17.0.19+10" && ./gradlew assembleDebug --quiet

# deploy (local build → install on phone)
bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh \\
  --project "$DEST" \\
  --device 100.122.101.27:5555

# deploy-ci (GitHub Actions artifact → install on phone)
bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh \\
  --project "$DEST" \\
  --device 100.122.101.27:5555 \\
  --ci $GITHUB_REPO

# logs-dump (snapshot — use for Discord output)
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \\
  --tag $APP_TAG --device 100.122.101.27:5555 --mode default --dump

# logs-crash (crash-only snapshot — use for Discord crash reports)
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \\
  --tag $APP_TAG --device 100.122.101.27:5555 --mode crash --dump

# logs (streaming — interactive only, not Discord)
bash /d/MyData/Software/openclaw-config/bin/android-logs.sh \\
  --tag $APP_TAG --device 100.122.101.27:5555

# adb-connect
/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe connect 100.122.101.27:5555
\`\`\`

---

## Stack

- **Language:** Java (source/target compat 1.8, build JDK 17)
- **AGP:** 8.2.2 | **Gradle:** 8.2 | **minSdk:** 24 | **targetSdk/compileSdk:** 34
- **Debug keystore:** \`debug.keystore\` in project root (storepass=android, alias=androiddebugkey)

---

## Common errors

| Error | Fix |
|-------|-----|
| Build fails — Java version | \`export JAVA_HOME="/c/Users/prana/jdk17/jdk-17.0.19+10"\` |
| \`adb: device offline\` | \`adb disconnect 100.122.101.27:5555 && adb connect 100.122.101.27:5555\` |
| Signature mismatch on install | \`android-deploy.sh\` handles automatically |
| \`NetworkOnMainThreadException\` | All network calls must be on background thread |

## Full troubleshooting
Read \`D:\\MyData\\Software\\openclaw-config\\agents\\android.md\`
CLAUDEMD

# --- Git init ---
cd "$DEST"
git init
git add .
git commit -m "init: scaffold from android-skeleton (slug=$SLUG)"

echo ""
echo "Done! Project created at: $DEST"
echo "Package: $PACKAGE"
echo "CLAUDE.md generated."
echo ""
echo "Next steps:"
echo "  1. Build: cd \"$DEST\" && export JAVA_HOME=/c/Users/prana/jdk17/jdk-17.0.19+10 && ./gradlew assembleDebug"
echo "  2. Deploy: bash /d/MyData/Software/openclaw-config/bin/android-deploy.sh --project \"$DEST\" --device 100.122.101.27:5555"
echo "  3. Push: cd \"$DEST\" && /c/Program\ Files/GitHub\ CLI/gh.exe repo create $GITHUB_REPO --public --source=. --push"
