#!/bin/bash
# android-test.sh — orchestrate embedded test server on Android device
#
# Usage:
#   bash android-test.sh --device <ip:port> --ping
#   bash android-test.sh --device <ip:port> --inline '<script>'
#   bash android-test.sh --device <ip:port> --script <file.bsh>
#   bash android-test.sh --device <ip:port> --screenshot <output.png>
#   bash android-test.sh --device <ip:port> --state
#
# Flags:
#   --device      ADB device address (ip:port)                    [required]
#   --ping        Health check — verify test server is running
#   --inline      Execute inline BeanShell script
#   --script      Execute BeanShell script from file
#   --screenshot  Capture screenshot and save to given path
#   --state       Get current activity and view state
#
# Screenshot falls back to ADB screencap if the test server endpoint fails.
#
# Prerequisites:
#   - App deployed with debug build (test server auto-starts)
#   - ADB accessible

set -eo pipefail

ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"
TEST_PORT=8973
LOCAL_PORT=8973

# --- Parse args ---
DEVICE=""
ACTION=""
ACTION_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --device)     [[ $# -ge 2 ]] || { echo "Error: --device requires a value"; exit 1; }
                      DEVICE="$2";     shift 2 ;;
        --ping)       ACTION="ping";   shift ;;
        --inline)     [[ $# -ge 2 ]] || { echo "Error: --inline requires a script"; exit 1; }
                      ACTION="inline"; ACTION_ARG="$2"; shift 2 ;;
        --script)     [[ $# -ge 2 ]] || { echo "Error: --script requires a file path"; exit 1; }
                      ACTION="script"; ACTION_ARG="$2"; shift 2 ;;
        --screenshot) [[ $# -ge 2 ]] || { echo "Error: --screenshot requires output path"; exit 1; }
                      ACTION="screenshot"; ACTION_ARG="$2"; shift 2 ;;
        --state)      ACTION="state";  shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$DEVICE" ]]; then
    echo "Error: --device is required"
    echo "Usage: bash android-test.sh --device <ip:port> --ping|--inline|--script|--screenshot|--state"
    exit 1
fi

if [[ -z "$ACTION" ]]; then
    echo "Error: specify an action: --ping, --inline, --script, --screenshot, or --state"
    exit 1
fi

# --- Ensure ADB connection ---
"$ADB" connect "$DEVICE" > /dev/null 2>&1 || true

# Verify device is reachable
if ! "$ADB" -s "$DEVICE" get-state 2>/dev/null | grep -qF "device"; then
    echo "Error: device $DEVICE not reachable"
    exit 1
fi

# --- Set up ADB port forwarding ---
# Remove any existing forward for this port, then re-establish
"$ADB" -s "$DEVICE" forward --remove tcp:$LOCAL_PORT 2>/dev/null || true
"$ADB" -s "$DEVICE" forward tcp:$LOCAL_PORT tcp:$TEST_PORT

# Cleanup port forward on exit
cleanup() {
    "$ADB" -s "$DEVICE" forward --remove tcp:$LOCAL_PORT 2>/dev/null || true
}
trap cleanup EXIT

BASE_URL="http://127.0.0.1:$LOCAL_PORT"

# --- ADB screenshot fallback ---
# Used when test server /screenshot endpoint fails (server down, phone locked, etc.)
adb_screenshot() {
    local outpath="$1"
    # Convert to Windows path for adb exec-out redirection
    local winpath
    winpath=$(cygpath -w "$outpath" 2>/dev/null || echo "$outpath")
    "$ADB" -s "$DEVICE" exec-out screencap -p > "$winpath" 2>/dev/null
    if [[ -f "$outpath" ]] && [[ $(wc -c < "$outpath") -gt 100 ]]; then
        return 0
    else
        rm -f "$outpath"
        return 1
    fi
}

# --- Actions ---
case "$ACTION" in
    ping)
        curl -s --max-time 5 "$BASE_URL/ping"
        echo ""
        ;;

    inline)
        result=$(curl -s --max-time 35 -X POST -H "Content-Type: text/plain" --data-binary "$ACTION_ARG" "$BASE_URL/exec")
        echo "$result"
        # Exit non-zero if script failed
        if echo "$result" | grep -q '"success":false'; then
            exit 1
        fi
        ;;

    script)
        if [[ ! -f "$ACTION_ARG" ]]; then
            echo "Error: script file not found: $ACTION_ARG"
            exit 1
        fi
        result=$(curl -s --max-time 35 -X POST -H "Content-Type: text/plain" --data-binary @"$ACTION_ARG" "$BASE_URL/exec")
        echo "$result"
        if echo "$result" | grep -q '"success":false'; then
            exit 1
        fi
        ;;

    screenshot)
        # Try test server first, fall back to ADB screencap
        http_code=$(curl -s -o "$ACTION_ARG" -w "%{http_code}" --max-time 10 "$BASE_URL/screenshot" 2>/dev/null || echo "000")
        if [[ "$http_code" == "200" ]] && [[ -f "$ACTION_ARG" ]] && [[ $(wc -c < "$ACTION_ARG") -gt 100 ]]; then
            size=$(wc -c < "$ACTION_ARG")
            echo "Screenshot saved to $ACTION_ARG ($size bytes) [test-server]"
        else
            # Fallback: ADB screencap (works even when test server is down or phone is locked)
            rm -f "$ACTION_ARG"
            if adb_screenshot "$ACTION_ARG"; then
                size=$(wc -c < "$ACTION_ARG")
                echo "Screenshot saved to $ACTION_ARG ($size bytes) [adb-fallback]"
            else
                echo "Error: screenshot failed (test server HTTP $http_code, ADB fallback also failed)"
                exit 1
            fi
        fi
        ;;

    state)
        curl -s --max-time 5 "$BASE_URL/state"
        echo ""
        ;;
esac
