#!/bin/bash
# Switch the AgentCore coordinator's A2A leg from the Cloud Run ADK agent to
# the Foundry agent, then redeploy and smoke-test it.
#
#   export CURRENCY_FOUNDRY_A2A_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>/agents/currency-a2a-agent/endpoint/protocols/a2a"
#   export CURRENCY_AZURE_SECRET_ID="bedrock-foundry-a2a/azure-service-principal"
#   ./infra/point_coordinator_at_foundry.sh
#
# Pass `adk` as the first argument to switch back.
#
# The endpoint embeds the Azure account and project names, so it is written
# into agentcore/agentcore.json locally. Keep that change out of commits, the
# same way infra/deploy_live.sh handles the Cloud Run URL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PEER="${1:-foundry}"

if [[ "$PEER" == "foundry" ]]; then
  : "${CURRENCY_FOUNDRY_A2A_ENDPOINT:?Set CURRENCY_FOUNDRY_A2A_ENDPOINT (see infra/enable_foundry_a2a.py output)}"
  : "${CURRENCY_AZURE_SECRET_ID:?Set CURRENCY_AZURE_SECRET_ID (see infra/configure_azure_secret.sh)}"
fi

cd "$REPO_ROOT"
PEER="$PEER" python3 - <<'PY'
import json
import os

path = "agentcore/agentcore.json"
with open(path) as stream:
    config = json.load(stream)
env = config["runtimes"][0].setdefault("envVars", [])

wanted = {"CURRENCY_A2A_PEER": os.environ["PEER"]}
for name in ("CURRENCY_FOUNDRY_A2A_ENDPOINT", "CURRENCY_AZURE_SECRET_ID"):
    if value := os.getenv(name):
        wanted[name] = value

for var in env:
    if var["name"] in wanted:
        var["value"] = wanted.pop(var["name"])
env.extend({"name": name, "value": value} for name, value in wanted.items())

with open(path, "w") as stream:
    json.dump(config, stream, indent=2)
    stream.write("\n")
print(f"agentcore.json now targets the {os.environ['PEER']} peer")
PY

./infra/sync_app.sh
agentcore deploy -y
agentcore status
agentcore invoke "Convert 100 USD to EUR in verified mode."
