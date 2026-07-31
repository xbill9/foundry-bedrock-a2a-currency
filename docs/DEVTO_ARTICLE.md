---
title: Can Amazon Bedrock AgentCore Talk to Microsoft Foundry over A2A?
published: true
series: A2A
tags: aws, azure, aiagents, a2a
cover_image: https://raw.githubusercontent.com/xbill9/bedrock-foundry-a2a-currency/main/devto-cover.png
---

I wanted to test one specific path:

```text
Amazon Bedrock AgentCore (AWS)
    |
    +-- MCP --> live exchange-rate tool
    |
    +-- A2A v1.0 --> Microsoft Foundry hosted agent (Azure)
```

On July 29, 2026, that path worked end to end. An AgentCore-hosted Strands
coordinator called a Microsoft Foundry agent over A2A v1.0, authenticated with
Microsoft Entra, and compared the reply with an independent MCP conversion.

For the smoke case, both sides converted 100 USD to EUR using a rate of
`0.87873` and returned `87.87300`. The deterministic comparator reported zero
relative difference and no warnings.

This article shows how to run that demo and documents what failed on the way.

The code is in
[xbill9/bedrock-foundry-a2a-currency](https://github.com/xbill9/bedrock-foundry-a2a-currency).

## What the demo measures

This is not intended to be a currency chatbot. Currency conversion gives the
demo a small domain with exact arithmetic, a public data source, and answers
that are easy to compare.

The coordinator supports three modes:

| Mode | Path |
|---|---|
| `mcp_only` | AgentCore calls the exchange-rate MCP tool |
| `a2a_only` | AgentCore delegates to the Foundry agent over A2A |
| `verified` | Both calls run concurrently and deterministic code compares the results |

The LLM selects and explains the workflow. It does not calculate the
conversion or decide whether two amounts agree. Python `Decimal` does that:

```python
difference = abs(primary.converted_amount - verifier.converted_amount)
relative_difference = difference / abs(primary.converted_amount)
agreed = relative_difference <= Decimal("0.005")
```

If the two sources disagree, the coordinator returns both quotes. It never
asks a model which number looks better.

## Architecture

```text
CLI / test runner
       |
       | SigV4
       v
Amazon Bedrock AgentCore Runtime, us-east-1
Strands Agents coordinator, Amazon Nova Micro
       |
       +-- MCP stdio
       |      |
       |      +-- Frankfurter daily reference rates
       |
       +-- AWS Secrets Manager
       |      |
       |      +-- Entra service-principal credential
       |
       +-- Entra OAuth client-credentials exchange
       |
       +-- A2A v1.0 JSON-RPC
              |
              v
Microsoft Foundry hosted agent, East US 2
Microsoft Agent Framework, gpt-5-mini
       |
       +-- MCP stdio
              |
              +-- Frankfurter daily reference rates
```

The two agents use the same rate provider deliberately. This smoke test is
about transport, authentication, tool use, and cross-framework agreement, not
about reconciling different market feeds.

## Prerequisites

You need:

- Python 3.11 or later
- Node.js 20 or later
- AWS CLI v2, authenticated to the target account
- Azure CLI 2.80 or later
- Azure Developer CLI (`azd`) with the Foundry agent extension
- permission to deploy AgentCore resources in AWS
- permission to create a Foundry project and hosted agent in Azure

Install the AgentCore CLI and authenticate:

```bash
npm install -g @aws/agentcore

aws sts get-caller-identity
az login
azd auth login
```

The Azure identity performing the deployment needs `Foundry Project Manager`
on the Foundry project. Azure management-plane `Owner` or `Contributor` alone
does not grant the data-plane `agents/write` action.

## Run the credential-free local checks

Clone the repository and install into the current user's Python environment.
The related benchmark repositories expose the same console-script names, so
invoking modules from the intended checkout avoids accidentally running a
sibling clone.

```bash
git clone https://github.com/xbill9/bedrock-foundry-a2a-currency.git
cd bedrock-foundry-a2a-currency

pip3 install --user --break-system-packages -e ".[dev]"
pip3 install --user --break-system-packages -r requirements.txt

PYTHONPATH=. python3 -m pytest -q
```

The July 29 build passed 66 tests. These cover the `Decimal` domain logic,
MCP subprocess transport, failure policies, Entra credential parsing, and a
Foundry-shaped authenticated A2A v1.0 server.

Try the three modes with deterministic fixture rates:

```bash
PYTHONPATH=. python3 -m coordinator.cli \
  100 USD EUR --mode mcp_only

PYTHONPATH=. python3 -m coordinator.cli \
  100 USD EUR --mode a2a_only

PYTHONPATH=. python3 -m coordinator.cli \
  100 USD EUR --mode verified --transport mcp-stdio --json
```

Fixture results prove orchestration and protocol behavior. They are not
financial quotes.

## Deploy the Microsoft Foundry peer

The repository's deployment script packages the Foundry agent, provisions the
project and `gpt-5-mini` model deployment, deploys the hosted agent, enables
incoming A2A, and reads back the authenticated v1.0 agent card:

```bash
./infra/deploy_foundry_peer.sh
```

The script prints an endpoint shaped like:

```text
https://<account>.services.ai.azure.com/api/projects/<project>/agents/currency-a2a-agent/endpoint/protocols/a2a
```

Save it for the next steps:

```bash
export CURRENCY_FOUNDRY_A2A_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>/agents/currency-a2a-agent/endpoint/protocols/a2a"
```

The card is not public. Foundry serves it at
`agentCard/v1.0`, and it requires an Entra bearer token just like the message
endpoint.

Before involving AWS, test the real Foundry peer from the local coordinator.
The local path uses your ambient Azure CLI credential:

```bash
CURRENCY_RATE_PROVIDER=frankfurter \
CURRENCY_FOUNDRY_A2A_ENDPOINT="$CURRENCY_FOUNDRY_A2A_ENDPOINT" \
PYTHONPATH=. python3 -m coordinator.cli \
  100 USD EUR \
  --mode verified \
  --transport mcp-stdio \
  --a2a-peer foundry \
  --timeout-seconds 90 \
  --json
```

Expect `mcp-stdio:frankfurter-live` as the primary source and
`hosted-foundry-a2a` as the verifier.

## Give the AWS runtime an Azure identity

An AgentCore runtime has an AWS IAM role, but it has no Azure identity.
Foundry does not accept an API key for incoming A2A. The demo uses a dedicated
Entra service principal with `Foundry Agent Consumer` on only the Foundry
project.

Create that identity using your organization's normal process, grant the
project role, and place the client secret in a protected local file. Then run:

```bash
export AZURE_TENANT_ID="<tenant-id>"
export AZURE_CLIENT_ID="<application-client-id>"
export AZURE_CLIENT_SECRET_FILE="/secure/path/to/client-secret"
export CURRENCY_AZURE_SECRET_ID="bedrock-foundry-a2a/azure-service-principal"

./infra/configure_azure_secret.sh
```

That script stores a JSON credential in AWS Secrets Manager without putting
the secret on the command line. It also prints the narrow IAM policy needed
by the generated AgentCore execution role:

```json
{
  "Effect": "Allow",
  "Action": "secretsmanager:GetSecretValue",
  "Resource": "<the-one-secret-arn>"
}
```

Do not place the client secret in `agentcore.json`. Runtime environment
variables are visible through the control plane.

## Deploy the AgentCore coordinator

Configure the AWS target and deploy once:

```bash
./infra/configure_aws_target.sh
./infra/sync_app.sh
agentcore deploy -y
agentcore status
```

Grant the generated execution role the one-secret policy printed by
`configure_azure_secret.sh`.

Now point the runtime at Foundry and redeploy:

```bash
export CURRENCY_AZURE_SECRET_ID="bedrock-foundry-a2a/azure-service-principal"
export CURRENCY_FOUNDRY_A2A_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>/agents/currency-a2a-agent/endpoint/protocols/a2a"

./infra/point_coordinator_at_foundry.sh
```

The script updates the local, account-specific runtime configuration, syncs
the bundle, deploys it, checks status, and runs a smoke request. Keep the
generated endpoint and account configuration out of Git.

Run each hosted mode explicitly:

```bash
agentcore invoke "Convert 100 USD to EUR in mcp_only mode."
agentcore invoke "Convert 100 USD to EUR in a2a_only mode."
agentcore invoke "Convert 100 USD to EUR in verified mode."
```

## Observed results

These are the hosted smoke observations from July 29, 2026. They are not a
latency distribution and should not be read as a platform benchmark.

| Mode | Observed source | Result | Observed tool latency |
|---|---|---|---:|
| `mcp_only` | `mcp-stdio:frankfurter-live` | rate `0.87873`, amount `87.87300` | about 4.2 s |
| `a2a_only` | `hosted-foundry-a2a` | rate `0.87873`, amount `87.87300` | about 18.8 s |
| `verified` | both sources | zero relative difference, no warnings | MCP about 3.1 s; A2A about 18.1 s |

The verified path runs both legs concurrently, so its tool time is dominated
by the slower Foundry call rather than the sum of both calls.

The important result is functional: AWS SigV4 invocation, Bedrock tool use,
MCP stdio, AWS Secrets Manager, an Entra client-credentials exchange, Foundry
agent-card discovery, and A2A v1.0 JSON-RPC all completed in one request.

The full 38-case AWS-to-Foundry matrix, repeated warm/cold distributions,
token use, and cloud cost have not been measured yet.

## Failures found while building it

### Foundry deployment returned 403

The Azure resource deployment succeeded, but hosted-agent creation failed
with:

```text
Identity does not have permissions for
Microsoft.CognitiveServices/accounts/AIServices/agents/write
```

Assigning `Foundry Project Manager` at the project scope fixed it. Azure
`Owner` did not imply this Foundry data-plane permission.

### The Foundry container never became ready

The manifest passed an unset `AZURE_AI_MODEL_DEPLOYMENT_NAME` template value.
The container exited with:

```text
ValueError: Model is required
```

The model deployment is owned by the same manifest, so the fix was to set its
known deployment name, `gpt-5-mini`, explicitly.

### The AgentCore A2A leg lacked `aiohttp`

`azure.identity.aio` uses Azure Core's optional aiohttp transport. The first
hosted invocation failed before token acquisition because `aiohttp` was not
declared in the CodeZip application's own dependency manifest.

Adding and locking `aiohttp==3.13.3` in
`app/CurrencyCoordinator/pyproject.toml` fixed the deployed runtime. Adding it
only to the repository-root requirements file was not enough; CodeZip resolves
the application bundle independently.

Each of these interoperability failures now has a regression test or a
manifest assertion.

## What A2A added

For this small conversion, MCP alone was faster and sufficient. A2A added an
independently hosted implementation, a separate model and framework, another
tool invocation, and a distinct failure boundary.

It also added real engineering work:

- cross-cloud identity and least-privilege role assignment
- authenticated agent-card discovery
- protocol-version pinning
- another cold-start boundary
- more dependency and deployment surfaces

That overhead is worthwhile only if independent execution, failover, or
cross-framework portability matters to the application. The demo now gives us
a reproducible way to measure that tradeoff instead of treating an HTTP 200 as
proof of interoperability.
