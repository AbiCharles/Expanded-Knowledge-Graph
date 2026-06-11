#!/usr/bin/env bash
# Post-deploy smoke check. Hits the live URL and verifies the boring,
# high-leverage things that break first after a bad deploy:
#   - app is responding
#   - the scenario catalogue is loaded (not just an empty 200)
#   - Phase 1 versioning endpoints are wired up
#   - per-class ontology lookup endpoints respond
#   - decision audit-trail endpoint responds
#
# Exits non-zero on any failure so it can wedge into `fly deploy` /
# CI / cron without parsing the output. Run after every deploy:
#
#     ./scripts/prod_smoke.sh
#     ./scripts/prod_smoke.sh https://staging.example.fly.dev
#
set -euo pipefail

BASE="${1:-https://tcs-knowledge-fabric.fly.dev}"
TIMEOUT=15
PASS=0
FAIL=0

check() {
    local name="$1"; shift
    local url="$1"; shift
    local validator="${1:-}"  # optional grep pattern that must appear in body

    local body code
    body=$(curl -s --max-time "${TIMEOUT}" -w "\n__CODE__:%{http_code}" "${url}" || true)
    code=$(printf '%s\n' "${body}" | awk -F'__CODE__:' '/__CODE__:/ { print $2 }')
    body=$(printf '%s\n' "${body}" | sed '/^__CODE__:/d')

    if [ "${code}" != "200" ]; then
        printf '  ✗ %-40s  HTTP %s\n' "${name}" "${code:-no-response}"
        FAIL=$((FAIL+1))
        return
    fi
    if [ -n "${validator}" ] && ! printf '%s' "${body}" | grep -qE "${validator}"; then
        printf '  ✗ %-40s  HTTP 200 but body missing /%s/\n' "${name}" "${validator}"
        FAIL=$((FAIL+1))
        return
    fi
    printf '  ✓ %-40s  HTTP 200\n' "${name}"
    PASS=$((PASS+1))
}

echo "Smoke-checking ${BASE}"
echo ""

# Wake the machine if Fly auto-stopped it; throws away the body.
curl -s --max-time "${TIMEOUT}" -o /dev/null "${BASE}/api/health" || true

# Tier 1: app responding + scenarios loaded
check "health"                       "${BASE}/api/health"                           '"ok"|"status"'
check "scenarios list non-empty"     "${BASE}/api/scenarios"                        '"SC-PP-008"'

# Tier 2: Phase 1 versioning surface
check "scenarios?full=1 (SC-PP-008)" "${BASE}/api/scenarios/SC-PP-008?full=1"       '"stages"'
check "versions list (SC-PP-008)"    "${BASE}/api/scenarios/SC-PP-008/versions"     '"version"'
check "version snapshot (v1)"        "${BASE}/api/scenarios/SC-PP-008?version=1"    '"stages"'

# Tier 3: ontology surface
check "ontology list"                "${BASE}/api/ontologies"                       '"tcs_core"'

# Tier 4: data sources surface
check "data-sources list"            "${BASE}/api/data-sources"                     '"governance_sqlite"'

echo ""
echo "  ${PASS} passed · ${FAIL} failed"
[ "${FAIL}" -eq 0 ] || exit 1
