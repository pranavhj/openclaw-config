#!/bin/bash
# android-logs.sh — stream or dump logcat from an Android device
#
# Usage:
#   bash android-logs.sh --tag <AppTag> --device <ip:port> [--mode <default|full|crash>] [--dump]
#
# Flags:
#   --tag    <AppTag>   logcat tag to filter (e.g. TableNew)          [required]
#   --device <ip:port>  ADB device address, e.g. 100.122.101.27:5555  [required]
#   --mode   <mode>     filter mode: default (default), full, crash
#   --dump              snapshot mode — adds -d flag, exits after printing
#                       combine with any --mode, e.g. --mode crash --dump
#
# Examples:
#   Stream app logs (interactive):        --tag MyApp --device 100.x.x.x:5555
#   Snapshot for Discord:                 --tag MyApp --device ... --mode default --dump
#   Crash-only snapshot for Discord:      --tag MyApp --device ... --mode crash --dump
#   All logs snapshot:                    --tag MyApp --device ... --mode full --dump
#
# Legacy: --mode dump still works (= --mode default --dump)

set -e

ADB="/c/Users/prana/AppData/Local/Android/Sdk/platform-tools/adb.exe"

# --- Parse args ---
TAG=""
DEVICE=""
MODE="default"
DUMP=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --tag)    TAG="$2";    shift 2 ;;
        --device) DEVICE="$2"; shift 2 ;;
        --mode)   MODE="$2";   shift 2 ;;
        --dump)   DUMP=1;      shift   ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# Legacy: --mode dump = --mode default --dump
if [[ "$MODE" == "dump" ]]; then
    MODE="default"
    DUMP=1
fi

if [[ -z "$TAG" || -z "$DEVICE" ]]; then
    echo "Usage: bash android-logs.sh --tag <AppTag> --device <ip:port> [--mode default|full|crash] [--dump]"
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
DUMP_FLAG=""
[[ $DUMP -eq 1 ]] && DUMP_FLAG="-d"

SNAPSHOT_OR_STREAM=$([ $DUMP -eq 1 ] && echo "snapshot" || echo "streaming — Ctrl+C to stop")
echo "[logcat] mode=$MODE dump=$DUMP tag=$TAG device=$DEVICE — $SNAPSHOT_OR_STREAM"

case "$MODE" in
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
