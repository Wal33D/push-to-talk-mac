#!/usr/bin/env bash

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-quick}"
FAILED=0

print_header() {
    printf "\n== %s ==\n" "$1"
}

run_check() {
    local name="$1"
    shift
    printf "[check] %s\n" "$name"
    if "$@"; then
        printf "[pass]  %s\n" "$name"
    else
        printf "[fail]  %s\n" "$name"
        FAILED=1
    fi
}

check_no_conflict_markers() {
    local patterns='^(<<<<<<<|=======|>>>>>>>)'
    if rg -n "$patterns" . \
        --glob '!.git/**' \
        --glob '!venv/**' \
        --glob '!*.min.js' \
        --glob '!*.lock' >/tmp/dictator_conflict_markers.txt 2>/dev/null; then
        cat /tmp/dictator_conflict_markers.txt
        rm -f /tmp/dictator_conflict_markers.txt
        return 1
    fi
    rm -f /tmp/dictator_conflict_markers.txt
    return 0
}

smoke_launch_voice() {
    if [ ! -x "./voice" ]; then
        echo "./voice is not executable."
        return 1
    fi

    local smoke_log="/tmp/dictator_pre_push_smoke.log"
    ./voice --debug >"$smoke_log" 2>&1 &
    local pid=$!

    sleep 8
    kill "$pid" >/dev/null 2>&1 || true
    wait "$pid" >/dev/null 2>&1 || true

    if rg -n "Traceback|FileNotFoundError|ModuleNotFoundError" "$smoke_log" >/dev/null 2>&1; then
        echo "Smoke run reported runtime errors:"
        cat "$smoke_log"
        return 1
    fi
    return 0
}

print_header "Dictator Pre-Push Checks"
echo "Mode: $MODE"

run_check "No merge conflict markers" check_no_conflict_markers
run_check "Python syntax compile (dictator.py)" \
    env PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m py_compile dictator.py
run_check "Shell syntax (install/autostart/voice)" \
    bash -n install.sh autostart.sh voice
run_check "Unit tests (tests/unit)" \
    env PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests/unit -p "test_*.py"

if [ "$MODE" = "--smoke" ] || [ "$MODE" = "smoke" ]; then
    run_check "Runtime smoke launch (./voice --debug)" smoke_launch_voice
fi

if [ "$FAILED" -ne 0 ]; then
    print_header "Result: FAILED"
    exit 1
fi

print_header "Result: PASSED"
exit 0
