#!/usr/bin/env bash
# Background runner for dump_fw.py so it survives beyond the interactive shell timeout.
# Usage: ./run_bg.sh <action> [args...]
# Logs to a3000-work/output/bg_log.txt
set -u
cd "$(dirname "$0")"
LOG="output/bg_log.txt"
PY="../Sony-PMCA-RE/.venv/bin/python"
echo "=== $(date) start: $* ===" >> "$LOG"
# trigger the update; sudo password via stdin is handled by the caller.
"$PY" dump_fw.py "$@" >> "$LOG" 2>&1
echo "=== $(date) exit: $? ===" >> "$LOG"
