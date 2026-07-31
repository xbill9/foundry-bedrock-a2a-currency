#!/bin/bash
# Store the Azure service principal that the AgentCore coordinator uses to
# authenticate to the Foundry A2A endpoint.
#
# The coordinator runs on AWS and has no Azure identity, and AgentCore runtime
# environment variables live in a committed file, so the Entra client secret
# goes to AWS Secrets Manager and is read at call time by coordinator/entra_auth.py.
#
#   export AZURE_TENANT_ID=... AZURE_CLIENT_ID=...
#   export AZURE_CLIENT_SECRET_FILE=/path/to/secret        # or AZURE_CLIENT_SECRET
#   ./infra/configure_azure_secret.sh
#
# The secret value is passed to the AWS CLI through a 0600 temp file, never on
# a command line where `ps` could read it.
set -euo pipefail

SECRET_ID="${CURRENCY_AZURE_SECRET_ID:-bedrock-foundry-a2a/azure-service-principal}"
: "${AZURE_TENANT_ID:?Set AZURE_TENANT_ID}"
: "${AZURE_CLIENT_ID:?Set AZURE_CLIENT_ID}"

if [[ -n "${AZURE_CLIENT_SECRET_FILE:-}" ]]; then
  CLIENT_SECRET="$(<"$AZURE_CLIENT_SECRET_FILE")"
else
  : "${AZURE_CLIENT_SECRET:?Set AZURE_CLIENT_SECRET or AZURE_CLIENT_SECRET_FILE}"
  CLIENT_SECRET="$AZURE_CLIENT_SECRET"
fi

PAYLOAD_FILE="$(mktemp)"
chmod 600 "$PAYLOAD_FILE"
trap 'rm -f "$PAYLOAD_FILE"' EXIT
AZURE_TENANT_ID="$AZURE_TENANT_ID" AZURE_CLIENT_ID="$AZURE_CLIENT_ID" \
CLIENT_SECRET="$CLIENT_SECRET" python3 - "$PAYLOAD_FILE" <<'PY'
import json, os, sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "tenant_id": os.environ["AZURE_TENANT_ID"],
            "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["CLIENT_SECRET"],
        }
    ),
    encoding="utf-8",
)
PY

if aws secretsmanager describe-secret --secret-id "$SECRET_ID" >/dev/null 2>&1; then
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_ID" --secret-string "file://$PAYLOAD_FILE" >/dev/null
  echo "Updated secret $SECRET_ID"
else
  aws secretsmanager create-secret \
    --name "$SECRET_ID" \
    --description "Entra service principal used by the AgentCore coordinator for Foundry A2A" \
    --secret-string "file://$PAYLOAD_FILE" >/dev/null
  echo "Created secret $SECRET_ID"
fi

SECRET_ARN="$(aws secretsmanager describe-secret --secret-id "$SECRET_ID" --query ARN --output text)"
cat <<EOF

Grant the AgentCore execution role read access, for example:

  aws iam put-role-policy \\
    --role-name <agentcore-execution-role> \\
    --policy-name ReadFoundryServicePrincipal \\
    --policy-document '{
      "Version": "2012-10-17",
      "Statement": [{
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": "$SECRET_ARN"
      }]
    }'

Then set these in agentcore/agentcore.json (runtimes[0].envVars):

  CURRENCY_AZURE_SECRET_ID = $SECRET_ID
  CURRENCY_A2A_PEER        = foundry
EOF
