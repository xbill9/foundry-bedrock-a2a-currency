# AgentCore deployment

Deploy the coordinator to Amazon Bedrock AgentCore Runtime with the AgentCore
CLI (`npm install -g @aws/agentcore`, Node 20+, CDK-based). The hosted
coordinator uses the AgentCore execution role and the AWS credential chain;
do not commit API keys.

Provision only the MVP resources:

- AgentCore Runtime hosting the Strands coordinator (`main.py`);
- Bedrock model access for the chosen Claude inference profile;
- the CLI-created IAM execution role and CloudWatch log group;
- CDK bootstrap assets (S3 staging for CodeZip builds).

Candidate deployment versions researched on 2026-07-28 (re-pin after the
first verified end-to-end deployment):

- AgentCore CLI: `@aws/agentcore` (npm, current)
- Python runtime SDK: `bedrock-agentcore` `1.18.1`
- Strands Agents: `1.50.2`
- A2A SDK: `1.1.2` (validated live against google-adk 2.5.0 on 2026-07-27)
- Bedrock model: `us.amazon.nova-micro-v1:0` — the cheapest Bedrock model
  with tool calling; no use-case form or agreement needed, unlike Anthropic
  models. Override with `BEDROCK_MODEL_ID` (inference-profile IDs only;
  bare model IDs fail with an on-demand-throughput 400 on newer models)
- Region: the active AWS profile's configured region, or `AWS_REGION`

Note: the older pip-based starter-toolkit flow (`agentcore configure` /
`agentcore launch` from `bedrock-agentcore-starter-toolkit`) was deprecated in
June 2026; use the npm CLI.

## Project layout (already scaffolded)

The AgentCore project was created on 2026-07-28 with
`agentcore create --framework Strands --protocol HTTP --model-provider Bedrock
--memory none` and relocated into the repo root:

- `agentcore/agentcore.json` — project config, including the runtime `envVars`
  for the live cross-cloud loop (committed);
- `agentcore/aws-targets.json` — account-specific deployment target generated
  locally by `infra/configure_aws_target.sh` and excluded from Git;
- `agentcore/.env.local`, `agentcore/.cli/` — local state (not committed);
- `app/CurrencyCoordinator/` — the deployable app: `main.py`
  (`BedrockAgentCoreApp` entrypoint), `model/load.py`, its own
  `pyproject.toml`/`uv.lock`, plus copies of `coordinator/` and `mcp_server/`
  synced by `infra/sync_app.sh` (the copies are build artifacts; edit the
  repo-root packages).

## Deploy and smoke-test

```bash
./infra/configure_aws_target.sh       # uses the active AWS profile/account
./infra/sync_app.sh                   # refresh the app's package copies
agentcore deploy -y                   # CDK deploy; prints the runtime ARN
agentcore status
agentcore invoke "Convert 100 USD to EUR in verified mode."
```

Select a non-default profile or region through the standard AWS environment
variables before configuring and deploying:

```bash
export AWS_PROFILE=my-profile
export AWS_REGION=us-east-1
./infra/configure_aws_target.sh
agentcore deploy -y
```

The generated target file contains the caller's AWS account ID and must remain
local. Run the configuration script again when switching profiles or regions.

Runtime environment variables live in `agentcore/agentcore.json` under
`runtimes[0].envVars`:

- `CURRENCY_A2A_PEER` — `adk` or `foundry`; selects the remote agent
- `CURRENCY_A2A_ENDPOINT` — Cloud Run URL of the ADK agent
- `CURRENCY_FOUNDRY_A2A_ENDPOINT` — Foundry A2A base path (set locally by
  `point_coordinator_at_foundry.sh`; it embeds the Azure account and project
  names, so keep it out of commits)
- `CURRENCY_AZURE_SECRET_ID` — AWS Secrets Manager id of the Entra service
  principal used for the Foundry peer
- `CURRENCY_RATE_PROVIDER=frankfurter`
- `CURRENCY_RATE_TRANSPORT=mcp-stdio`
- `CURRENCY_TIMEOUT_SECONDS=60` (Cloud Run cold starts exceed the 10 s default)
- `BEDROCK_MODEL_ID` — override of the default inference profile

## Observed results

Observed deployment result on 2026-07-28:

- Stack `AgentCore-currencybench-default` deployed to us-east-1; runtime
  `currencybench_CurrencyCoordinator` active with CloudWatch logs at
  `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` and OTel traces.
- All three benchmark modes completed hosted. Verified mode (100 USD → EUR,
  CHF) returned both quotes with primary `mcp-stdio:frankfurter-live`
  (per-quote latency ~3.9 s including Cloud Run warm-up) and verifier
  `hosted-adk-a2a` in agreement. a2a_only (500 EUR → USD) returned 1.1367
  from the Gemini agent, exactly matching mcp_only — both use Frankfurter
  upstream. `evaluations/invoke_hosted.py` (boto3 SigV4) round-tripped in
  ~12 s wall clock.
- Failure notes: Anthropic models on Bedrock require a one-time use-case
  form (`PutUseCaseForModelAccess`; `intendedUsers` is a numeric-code
  string) plus a marketplace agreement — switching to Nova Micro avoided
  both. The first A2A attempt failed with a protocol error because the ADK
  agent card advertises its bind address; see `coordinator/a2a_remote.py`.

Historical baseline: the same benchmark ran hosted on Microsoft Foundry on
2026-07-27 (all three modes completed; verified mode agreed exactly with
relative_difference 0; mcp_only elapsed 0.71 s, verified 2.7 s). That result
is retained as the comparison target for the AgentCore runs.

Observed AWS → Foundry smoke result on 2026-07-29: the AgentCore-hosted
Strands coordinator completed `mcp_only`, `a2a_only`, and `verified` against
the deployed Foundry peer. For 100 USD → EUR, both live legs returned rate
`0.87873` and amount `87.87300`; verified mode agreed with no warnings. The
single observed tool latencies were approximately 3.1 s for the MCP leg and
18.1 s for the Foundry A2A leg. These are smoke observations, not latency
distributions.

## Foundry A2A peer (Azure half)

The second remote agent is a Foundry hosted agent with incoming A2A enabled.
Deploy it and wire the coordinator to it:

```bash
az login && azd auth login
./infra/deploy_foundry_peer.sh          # sync, azd provision/deploy, enable A2A
./infra/configure_azure_secret.sh       # service principal -> AWS Secrets Manager
./infra/point_coordinator_at_foundry.sh # agentcore.json + redeploy + smoke test
```

Role assignments needed (the RBAC names were renamed recently; the old
`Azure AI …` names may still appear in the portal):

- **Foundry Project Manager** on the Foundry account for the deploying
  identity. The equivalent assignment on the sibling Azure project was role
  definition `eadc314b-1a2d-4efa-be10-5d325db5065e`; missing it is what failed
  the first Foundry deployment on 2026-07-26.
- **Foundry User** or higher on the project to PATCH the agent card and enable
  the A2A protocol.
- **Foundry Agent Consumer** on the project for the *calling* identity — the
  service principal whose secret lives in AWS Secrets Manager. Without it the
  coordinator fails at the agent card with a typed `authentication` failure,
  not a protocol error.

Notes carried from the Microsoft documentation (2026-07-28) that the client
depends on:

- incoming A2A requires the responses protocol, so the peer runs through
  `ResponsesHostServer`;
- the card is published at `…/endpoint/protocols/a2a/agentCard/v1.0`, not the
  well-known path, and it is not anonymously readable;
- Foundry serves A2A v0.3 unless the caller pins v1.0 by header, query string,
  or v1.0-card negotiation — the coordinator sends `A2A-Version: 1.0`;
- v1.0 is JSONRPC-only on Foundry: no HTTP+JSON, no gRPC, no streaming, text
  modality only.

`deploy_live.sh` intentionally contains no project ID or key path. Set
`GCP_PROJECT`; optionally set `GCP_REGION`, `CURRENCY_A2A_SERVICE`,
`GEMINI_SECRET_NAME`, and `GEMINI_KEY_FILE`. `GEMINI_KEY_FILE` is used only
when creating a missing Secret Manager secret.

Before deployment, verify the latest official instructions:

- https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint
- https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/framework-hosted-agents
- https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html
- https://github.com/aws/agentcore-cli
- https://strandsagents.com/docs/user-guide/quickstart/python/
