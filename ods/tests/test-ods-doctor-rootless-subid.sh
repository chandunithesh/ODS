#!/usr/bin/env bash
# Fixture tests for the ROOTLESS_SUBID runtime check in scripts/ods-doctor.sh.
# ODS_ASSUME_ROOTLESS forces the rootless path and ODS_SUBUID_FILE /
# ODS_SUBGID_FILE point at temp fixtures, so no rootless daemon is needed.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCTOR="$ROOT_DIR/scripts/ods-doctor.sh"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'
PASSED=0
FAILED=0
pass() { printf "  ${GREEN}✓ PASS${NC} %s\n" "$1"; PASSED=$((PASSED + 1)); }
fail() { printf "  ${RED}✗ FAIL${NC} %s\n" "$1"; FAILED=$((FAILED + 1)); }

echo ""
echo "=== ods-doctor rootless subordinate ID tests ==="
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[SKIP] python3 not available — doctor cannot run here"
    exit 0
fi

if bash -n "$DOCTOR" 2>/dev/null; then
    pass "ods-doctor.sh passes bash -n"
else
    fail "ods-doctor.sh bash -n failed"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
CURRENT_USER="$(id -un)"

# Doctor exits non-zero when the report records blockers/warnings from the
# host environment; only the report content matters for these assertions.
run_doctor() {
    # $1=subuid fixture, $2=subgid fixture, $3=report path
    ODS_ASSUME_ROOTLESS=1 \
    ODS_SUBUID_FILE="$1" \
    ODS_SUBGID_FILE="$2" \
        bash "$DOCTOR" "$3" >/dev/null 2>&1 || true
    [[ -f "$3" ]]
}

subid_status() {
    python3 -c '
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    report = json.load(f)
check = report["runtime"]["rootless_subid_check"]
hints = [h for h in report.get("autofix_hints", []) if "subordinate" in h]
print(check["status"], report["runtime"]["rootless_docker"], len(hints))
' "$1"
}

printf '%s:100000:65536\n' "$CURRENT_USER" >"$TMP_DIR/subuid-ok"
printf '%s:100000:65536\n' "$CURRENT_USER" >"$TMP_DIR/subgid-ok"
printf 'someone-else:100000:65536\n' >"$TMP_DIR/subuid-missing"
printf '%s:100000:1000\n' "$CURRENT_USER" >"$TMP_DIR/subuid-small"

if run_doctor "$TMP_DIR/subuid-ok" "$TMP_DIR/subgid-ok" "$TMP_DIR/report-ok.json"; then
    read -r status rootless hints <<<"$(subid_status "$TMP_DIR/report-ok.json")"
    [[ "$status" == "pass" ]] && pass "full 65536 range reports pass" || fail "expected pass, got $status"
    [[ "$rootless" == "True" ]] && pass "report marks the daemon rootless" || fail "rootless_docker not True"
    [[ "$hints" == "0" ]] && pass "no subordinate-ID fix hint on pass" || fail "unexpected fix hint on pass"
else
    echo "[SKIP] doctor did not produce a report on this host (missing deps?)"
    exit 0
fi

if run_doctor "$TMP_DIR/subuid-missing" "$TMP_DIR/subgid-ok" "$TMP_DIR/report-missing.json"; then
    read -r status _ hints <<<"$(subid_status "$TMP_DIR/report-missing.json")"
    [[ "$status" == "fail" ]] && pass "missing user entry reports fail" || fail "expected fail, got $status"
    [[ "$hints" == "1" ]] && pass "missing entry surfaces the usermod fix hint" || fail "fix hint missing on fail"
else
    fail "doctor did not produce a report for the missing-entry fixture"
fi

if run_doctor "$TMP_DIR/subuid-small" "$TMP_DIR/subgid-ok" "$TMP_DIR/report-small.json"; then
    read -r status _ hints <<<"$(subid_status "$TMP_DIR/report-small.json")"
    [[ "$status" == "warn" ]] && pass "sub-65536 range reports warn" || fail "expected warn, got $status"
    [[ "$hints" == "1" ]] && pass "small range surfaces the usermod fix hint" || fail "fix hint missing on warn"
else
    fail "doctor did not produce a report for the small-range fixture"
fi

echo ""
echo "Result: $PASSED passed, $FAILED failed"
echo ""
[[ $FAILED -eq 0 ]]
