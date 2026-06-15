#!/usr/bin/env bash
# Prints the env-var values currently set on the Fly deployment so they
# can be copy-pasted into an Azure runtime resource (App Service /
# Container Apps / AKS Secret).
#
# Output goes to stdout ONLY. Nothing is written to disk and nothing
# leaves the operator's terminal session. Treat the output like a
# password — close the terminal when done, don't commit it anywhere.
#
# Usage:
#   ./scripts/export_fly_secrets_for_azure.sh
#   ./scripts/export_fly_secrets_for_azure.sh --app my-other-fly-app
#
# See docs/azure-deployment-setup.md for what to do with the values.
set -euo pipefail

APP="tcs-knowledge-fabric"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APP="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,17p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

VARS=(
  JWT_SECRET
  LLM_PROVIDER
  OPENAI_API_KEY
  HITL_ADMIN_PASSWORD
  NEO4J_URI
  NEO4J_USER
  NEO4J_PASSWORD
  NEO4J_DATABASE
)

# Build the regex once.
REGEX="^($(IFS='|'; echo "${VARS[*]}"))="

echo "Reading env vars from Fly app: ${APP}"
echo "(Values are printed in plain text — close this terminal when done.)"
echo ""

# Wake the machine first (Fly's auto-stop kills idle machines).
fly status -a "${APP}" >/dev/null 2>&1 || true

# Read the values from the live container's env. `fly ssh console -C`
# runs the given shell command non-interactively.
fly ssh console -a "${APP}" -C "env" 2>/dev/null \
  | grep -E "${REGEX}" \
  | sort

echo ""
echo "Next steps:"
echo "  1. Copy the values above into your Azure resource's config."
echo "  2. See docs/azure-deployment-setup.md for per-runtime commands."
echo "  3. Verify the connection via the probe at the end of that doc."
