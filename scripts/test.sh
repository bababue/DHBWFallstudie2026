#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"

run_tests() {
    local path="$1"
    local tests="$2"
    PYTHONPATH="$path" "$PYTHON" -m unittest discover -s "$tests" -p 'test*.py'
}

run_tests "$ROOT/src" "$ROOT/src"
run_tests "$ROOT/src/sensors:$ROOT/src" "$ROOT/src/sensors"
run_tests "$ROOT/src/dashboard:$ROOT/src" "$ROOT/src/dashboard"
run_tests "$ROOT/scripts:$ROOT/src/sensors:$ROOT/src" "$ROOT/scripts"
