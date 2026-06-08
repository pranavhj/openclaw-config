#!/bin/bash
# android-logs.sh — stream or dump logcat from an Android device
#
# Usage:
#   bash android-logs.sh --tag <AppTag> --device <ip:port> [--mode <default|full|crash|dump>]
#
# Flags:
#   --tag    <AppTag>   logcat tag to filter (e.g. TableNew) (required)
#   --device <ip:port>  ADB device address, e.g. 100.122.101.27:5555 (required)
#   --mode   <mode>     default (default), full, crash, dump
#
# Modes:
#   default  stream: filter to <tag>:V AndroidRuntime:E *:S
#   full     stream: unfiltered logcat -v time
#   crash    stream: *:S AndroidRuntime:E <tag>:E (crashes only)
#   dump     snapshot (adds -d): use this for Discord output — does not block

set -e

ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"

# --- Parse args ---
TAG=""
DEVICE=""
MODE="default"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)    TAG="$2";    shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        --mode)   MODE="$2";   shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ -z "$TAG" || -z "$DEVICE" ]]; then
    echo "Usage: bash android-logs.sh --tag <AppTag> --device <ip:port> [--mode default|full|crash|dump]"
    exit 1
fi

# --- Connect to device ---
echo "Connecting to $DEVICE..."
"$ADB" connect "$DEVICE" 2>&1 || true
sleep 1

if ! "$ADB" devices | grep -q "^${DEVICE}[[:space:]]"; then
    echo "Error: device $DEVICE not reachable"
    "$ADB" devices
    exit 1
fi

ADB_FLAGS="-s $DEVICE"

# dump mode adds -d to any filter
DUMP_FLAG=""
ACTUAL_MODE="$MODE"
if [[ "$MODE" == "dump" ]]; then
    DUMP_FLAG="-d"
    ACTUAL_MODE="default"
fi

echo "[logcat] mode=$MODE tag=$TAG device=$DEVICE — $([ -n "$DUMP_FLAG" ] && echo 'snapshot' || echo 'streaming, Ctrl+C to stop')"

case "$ACTUAL_MODE" in
    full)
        "$ADB" $ADB_FLAGS logcat $DUMP_FLAG -v time
        ;;
    crash)
        "$ADB" $ADB_FLAGS logcat $DUMP_FLAG -v time "*:S" AndroidRuntime:E "${TAG}:E"
        ;;
    *)
        "$ADB" $ADB_FLAGS logcat $DUMP_FLAG -v time "*:S" "${TAG}:V" AndroidRuntime:E
        ;;
esac
