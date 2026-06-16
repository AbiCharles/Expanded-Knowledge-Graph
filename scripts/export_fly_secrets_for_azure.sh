#!/usr/bin/env bash
# Prints the env-var values currently set on the Fly deployment so they
# can be copy-pasted into an Azure runtime resource (App Service /
# Container Apps / AKS Secret).
#
# Supports both LLM providers:
#   LLM_PROVIDER=openai → uses OPENAI_API_KEY
#   LLM_PROVIDER=azure  → uses AZURE_OPENAI_* (5 vars)
#
# If the Azure-deployment target should run on Azure OpenAI but those
# vars aren't yet set on Fly, the script prints a clear "missing" hint
# at the end and points you at the right `fly secrets set` commands.
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
      sed -n '2,24p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# Every var we know about. The script tries to read each from Fly;
# missing ones are reported at the bottom so you know what to set.
VARS=(
  JWT_SECRET
  LLM_PROVIDER
  OPENAI_API_KEY
  OPENAI_MODEL
  AZURE_OPENAI_API_KEY
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_API_VERSION
  AZURE_OPENAI_DEPLOYMENT
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT
  HITL_ADMIN_PASSWORD
  NEO4J_URI
  NEO4J_USER
  NEO4J_PASSWORD
  NEO4J_DATABASE
)

# Vars required when running LLM_PROVIDER=azure. Listed here so we can
# tell the operator exactly what's missing for the Azure-OpenAI flow.
AZURE_OPENAI_REQUIRED=(
  AZURE_OPENAI_API_KEY
  AZURE_OPENAI_ENDPOINT
  AZURE_OPENAI_DEPLOYMENT
)
AZURE_OPENAI_OPTIONAL=(
  AZURE_OPENAI_API_VERSION
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT
)

REGEX="^($(IFS='|'; echo "${VARS[*]}"))="

echo "Reading env vars from Fly app: ${APP}"
echo "(Values are printed in plain text — close this terminal when done.)"
echo ""

# Wake the machine first (Fly's auto-stop kills idle machines).
fly status -a "${APP}" >/dev/null 2>&1 || true

# Capture the matched env lines so we can both print them and detect
# which expected vars were absent.
FOUND="$(fly ssh console -a "${APP}" -C "env" 2>/dev/null | grep -E "${REGEX}" | sort)"
echo "${FOUND}"

# Compute the set of vars that DID appear so we can warn about the rest.
FOUND_NAMES="$(echo "${FOUND}" | awk -F= '{print $1}')"

is_present() {
  echo "${FOUND_NAMES}" | grep -qx "$1"
}

missing_required=()
missing_optional=()
for v in "${AZURE_OPENAI_REQUIRED[@]}"; do
  is_present "$v" || missing_required+=("$v")
done
for v in "${AZURE_OPENAI_OPTIONAL[@]}"; do
  is_present "$v" || missing_optional+=("$v")
done

# Was OPENAI_API_KEY set (i.e. is this currently an OpenAI deployment)?
is_present OPENAI_API_KEY && has_openai=1 || has_openai=0

echo ""
if [ "${#missing_required[@]}" -gt 0 ]; then
  echo "AZURE OPENAI: ${#missing_required[@]} required var(s) not set on Fly."
  echo "  Missing required: ${missing_required[*]}"
  if [ "${#missing_optional[@]}" -gt 0 ]; then
    echo "  Missing optional: ${missing_optional[*]}"
  fi
  echo ""
  echo "  Two ways to provide them:"
  echo ""
  echo "  (A) Manage centrally on Fly (recommended — same script then exports"
  echo "      them to Azure too). Run on this machine:"
  echo ""
  echo "      fly secrets set -a ${APP} \\"
  echo "        AZURE_OPENAI_API_KEY='<your-key>' \\"
  echo "        AZURE_OPENAI_ENDPOINT='https://<resource>.openai.azure.com' \\"
  echo "        AZURE_OPENAI_DEPLOYMENT='<chat-deployment-name>' \\"
  echo "        AZURE_OPENAI_API_VERSION='2024-10-21' \\"
  echo "        AZURE_OPENAI_EMBEDDING_DEPLOYMENT='<embed-deployment-name-or-empty>' \\"
  echo "        LLM_PROVIDER='azure'"
  echo ""
  echo "      Then re-run this export script."
  echo ""
  echo "  (B) Set them only on the Azure Container App (skip Fly). In that case"
  echo "      paste the values directly into the 'Step 2' command in"
  echo "      docs/azure-deployment-setup.md, e.g.:"
  echo ""
  echo "      az containerapp secret set -n <app> -g <rg> --secrets \\"
  echo "        azure-openai-key='<your-key>' ..."
  echo ""
  echo "      az containerapp update -n <app> -g <rg> --set-env-vars \\"
  echo "        LLM_PROVIDER=azure \\"
  echo "        AZURE_OPENAI_API_KEY=secretref:azure-openai-key \\"
  echo "        AZURE_OPENAI_ENDPOINT='https://<resource>.openai.azure.com' \\"
  echo "        AZURE_OPENAI_DEPLOYMENT='<chat-deployment-name>' \\"
  echo "        AZURE_OPENAI_API_VERSION='2024-10-21'"
  echo ""
fi

if [ "${has_openai}" -eq 1 ] && [ "${#missing_required[@]}" -eq 0 ]; then
  echo "NOTE: Both OPENAI_API_KEY and the Azure OpenAI vars are set on Fly."
  echo "  Override LLM_PROVIDER per deployment to control which one runs:"
  echo "    Fly app:   LLM_PROVIDER=openai  (or stay on current setting)"
  echo "    Azure app: LLM_PROVIDER=azure"
  echo ""
fi

echo "Next steps:"
echo "  1. Copy the values above into your Azure resource's config."
echo "  2. See docs/azure-deployment-setup.md for per-runtime commands."
echo "  3. Verify Neo4j + LLM connectivity via the probes at the end of that doc."
