#!/bin/bash
# Deploy the Azure master:
#   1. sync coordinator/ + mcp_server/ into the foundry_agent bundle
#   2. configure the Bedrock A2A endpoint
#   3. azd provision + deploy the Foundry hosted coordinator
#
# Requires `az login` and `azd auth login`, plus Foundry Project Manager on the
# account for provisioning (see infra/README.md). Prints the A2A endpoint to
# feed back into the AgentCore runtime configuration.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT_DIR="$REPO_ROOT/foundry_agent"
AZD_ENV="${AZD_ENV_NAME:-bedrock-foundry-a2a-currency-dev}"

echo "=== 1/3 sync packages into the agent bundle ==="
"$REPO_ROOT/infra/sync_app.sh"

if [[ -z "${CURRENCY_BEDROCK_A2A_ENDPOINT:-}" ]]; then
  echo "CURRENCY_BEDROCK_A2A_ENDPOINT is required." >&2
  exit 2
fi
for name in CURRENCY_BEDROCK_OAUTH_TOKEN_URL CURRENCY_BEDROCK_OAUTH_CLIENT_ID \
  CURRENCY_BEDROCK_OAUTH_CLIENT_SECRET CURRENCY_BEDROCK_OAUTH_SCOPE; do
  if [[ -z "${!name:-}" ]]; then
    echo "$name is required." >&2
    exit 2
  fi
done

echo "=== 2/3 configure Bedrock peer ==="
cd "$AGENT_DIR"
azd env select "$AZD_ENV" 2>/dev/null || azd env new "$AZD_ENV"
azd env set CURRENCY_RATE_PROVIDER "${CURRENCY_RATE_PROVIDER:-frankfurter}"
azd env set CURRENCY_BEDROCK_A2A_ENDPOINT "$CURRENCY_BEDROCK_A2A_ENDPOINT"
azd env set CURRENCY_BEDROCK_OAUTH_TOKEN_URL "$CURRENCY_BEDROCK_OAUTH_TOKEN_URL"
azd env set CURRENCY_BEDROCK_OAUTH_CLIENT_ID "$CURRENCY_BEDROCK_OAUTH_CLIENT_ID"
azd env set CURRENCY_BEDROCK_OAUTH_CLIENT_SECRET "$CURRENCY_BEDROCK_OAUTH_CLIENT_SECRET"
azd env set CURRENCY_BEDROCK_OAUTH_SCOPE "$CURRENCY_BEDROCK_OAUTH_SCOPE"

echo "=== 3/3 azd provision + deploy ==="
azd provision --no-prompt
azd deploy --no-prompt

echo "=== Done. Foundry is the coordinator; Bedrock is the remote A2A peer. ==="
