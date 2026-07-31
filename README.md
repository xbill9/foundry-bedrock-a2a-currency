# Foundry → Bedrock Cross-Cloud Currency Agent

A buildable interoperability lab in which a Microsoft Agent Framework
coordinator hosted in Foundry verifies currency conversions by combining:

- a live exchange-rate tool exposed through MCP;
- a remote Strands currency agent exposed through A2A v1.0 from Amazon Bedrock
  AgentCore Runtime; and
- deterministic comparison and evaluation code.

The goal is not another currency chatbot. The goal is to measure what A2A adds
to a normal tool-calling workflow: accuracy, latency, cost, failure recovery,
and cross-framework portability. The domain core is unchanged from the earlier
AWS-master runs, so the same 38 cases can compare the orchestration direction
like-for-like. Earlier ADK/Foundry peer profiles and results are retained as
historical benchmark evidence.

## Target architecture

```text
CLI / test runner
       |
Microsoft Foundry hosted coordinator
Microsoft Agent Framework (Python)
       |
       +-- MCP --> exchange-rate server
       |
       +-- A2A v1.0 --> Strands currency agent (Bedrock AgentCore)
                       runtime bearer token, well-known agent card
       |
       +-- OpenTelemetry traces + evaluation results
```

Bedrock is the default peer (`CURRENCY_A2A_PEER=bedrock`). Everything
vendor-specific about the A2A leg lives in
`coordinator/a2a_peers.py`.

## Research questions

1. Can a Foundry-hosted Microsoft Agent Framework coordinator discover and
   invoke a Strands agent on AgentCore through an A2A agent card?
2. What latency and token overhead does remote-agent verification add?
3. Does MCP plus independent A2A verification improve numeric correctness or
   failure recovery enough to justify that overhead?
4. Which failures are protocol, authentication, framework, model, or
   application failures?
5. What does authenticating from an Azure-hosted master to an AWS runtime cost
   in engineering terms?

## MVP

The first publishable version has only:

- one Python Microsoft Agent Framework coordinator in Foundry;
- one remote Strands currency agent in Bedrock AgentCore;
- one MCP exchange-rate server;
- one AgentCore Runtime deployment;
- AgentCore runtime authentication supplied to the Foundry host as a secret;
- A2A agent-card discovery;
- structured conversion results;
- hosted trace correlation, with benchmark trace-ID export still pending; and
- 30–50 repeatable evaluation cases.

AgentCore Gateway/Memory/Identity, Amazon Q integrations, and a custom web
frontend are explicitly out of scope for the MVP.

## Repository map

```text
coordinator/       Framework-independent domain types and coordinator adapters
adk_agent/         Runnable Google ADK agent exposed over A2A v1.0
foundry_agent/     Microsoft Foundry hosted master coordinator
mcp_server/        Exchange-rate MCP server adapter
app/               AgentCore Runtime A2A specialist (Strands + synced copies)
agentcore/         AgentCore CLI project config and CDK assets
evaluations/       Cases, runner, scorers, and generated results
infra/             Deployment scripts (Cloud Run + Foundry + AgentCore) and notes
docs/              Architecture, implementation plan, and article guidance
tests/             Fast deterministic tests
```

## Run locally

The repository includes a credential-free implementation with deterministic
fixture rates. Fixture results exercise the orchestration and protocols; they
are not live financial quotes.

1. Install the project and development dependencies for your user account:

   ```bash
   pip3 install --user --break-system-packages -e ".[dev]"
   ```

2. Run the local deterministic tests:

   ```bash
   pytest
   ```

3. Exercise all three paths from the CLI:

   ```bash
   currency-benchmark 100 USD CAD EUR --mode mcp_only
   currency-benchmark 100 USD CAD EUR --mode a2a_only
   currency-benchmark 100 USD CAD EUR --mode verified --json
   ```

   Add `--transport mcp-stdio` to route the rate tool through the local MCP
   stdio server (spawned as a subprocess) instead of the in-process fixture.
   Add `--a2a-peer foundry` (with `CURRENCY_FOUNDRY_A2A_ENDPOINT` set, or an
   explicit `--a2a-endpoint`) to run the A2A leg against Foundry instead of
   the ADK agent.

   The three sibling repositories install the same console-script names, so
   whichever was installed last wins. Run `python3 -m coordinator.cli …` and
   `python3 -m evaluations.runner …` from a clone to be sure you are running
   that clone's code.

4. Run the 38-case benchmark matrix (114 records). Raw JSONL goes to `--output`;
   a per-mode summary (success rate, nearest-rank median/p95 latency, agreement
   rate) prints to stderr and can be written with `--summary`:

   ```bash
   currency-evaluate --output /tmp/currency-results.jsonl --summary /tmp/currency-summary.json
   ```

5. Start the local MCP stdio server:

   ```bash
   currency-mcp-server
   ```

   It implements `initialize`, `ping`, `tools/list`, and `tools/call` for the
   `convert_currency` tool using newline-delimited JSON-RPC. Configure an MCP
   client to launch that command over stdio.

## Deploy Bedrock remote, then the Foundry master

Deploy the AgentCore A2A specialist first:

```bash
./infra/sync_app.sh
agentcore deploy -y
```

Retrieve its runtime URL/card and a runtime bearer token using the AgentCore
CLI or AWS API, then inject both without committing them:

```bash
export CURRENCY_BEDROCK_A2A_ENDPOINT='https://.../invocations/'
export CURRENCY_BEDROCK_A2A_BEARER_TOKEN='...'
az login && azd auth login
./infra/deploy_foundry_peer.sh
```

The bearer value is stored as a secret in the local azd environment. It is not
written to `azure.yaml` or any tracked file.

Direct hosted-agent dependencies are pinned in `requirements.txt`. Update those
pins only after a new end-to-end deployment has been verified, and retain the
working versions with the benchmark evidence.

Cloud deployment remains adapter work: copy `.env.example` to `.env`, keep it
uncommitted, and validate current SDK examples before re-pinning Strands
Agents, Bedrock AgentCore, Google ADK, and A2A packages.

## Three benchmark modes

| Mode | Implementation | Purpose |
|---|---|---|
| `mcp_only` | Foundry coordinator calls the rate tool | Baseline |
| `a2a_only` | Foundry coordinator delegates to Bedrock over A2A | Measure remote-agent behavior |
| `verified` | MCP result checked by the A2A peer | Accuracy/overhead tradeoff |

Each mode runs against whichever peer is selected, so `a2a_only` and `verified`
produce one set of numbers per peer.

## Local implementation status

- Implemented: domain validation, `Decimal` cross-rate arithmetic, deterministic
  provider, three coordinator modes, concurrent verification, typed adapter
  failures, fallback policy, disagreement/staleness warnings, CLI, MCP stdio
  server and client adapter (subprocess JSON-RPC round trip), per-mode
  evaluation summaries, 38 evaluation cases, and deterministic tests.
- Ported and deployed on 2026-07-28: coordinator hosting moved from Microsoft
  Foundry to Strands + AgentCore (`app/CurrencyCoordinator/main.py`, Amazon
  Nova Micro), the A2A adapter moved to the plain `a2a-sdk` 1.x client, and
  hosted invocation moved to `bedrock-agentcore:InvokeAgentRuntime`. All
  three modes completed hosted the same day (AWS us-east-1 → GCP Cloud Run);
  verified mode agreed. See `infra/README.md` for the observed results.
- Retained Azure-era evidence (2026-07-26/27): hosted provisioning, live
  Frankfurter rates over MCP stdio, the cross-cloud A2A v1.0 call to the
  Cloud Run ADK agent, and a full 38-case live evaluation
  (`evaluations/results/live-2026-07-27.jsonl`). Those measurements are the
  baseline for the AWS run; see `infra/README.md`.
- Added on 2026-07-28: a second A2A peer. `coordinator/a2a_peers.py` carries
  the vendor differences (agent-card path, card-URL rewriting, Entra bearer
  token, pinned protocol version), `coordinator/entra_auth.py` mints Entra
  tokens from an AWS Secrets Manager service principal, and `foundry_agent/`
  is the Foundry hosted agent. Verified locally against a Foundry-shaped A2A
  server (`tests/test_a2a_foundry_shape.py`) and against the real MCP client
  path; the MCP stdio server answers the official MCP SDK, not only this
  repository's client.
- Observed on 2026-07-29: the Foundry peer was deployed in Azure and called
  from the AgentCore-hosted AWS coordinator. All three hosted modes completed.
  For the 100 USD → EUR smoke case, MCP and Foundry both returned rate
  `0.87873` and amount `87.87300`; verified mode agreed with no warnings.
- Not yet measured: token usage, cloud cost, repeated warm/cold hosted
  distributions, the full 38-case AWS → Foundry matrix, or benchmark trace-ID
  export.

## Full benchmark definition of done

- A fresh user can reproduce the local tests from the README.
- A deployed coordinator calls both MCP and A2A endpoints.
- Every result records rate timestamp, source, amount, currencies, latency, and
  agreement status.
- At least 30 evaluation cases run in all three modes.
- Results include median/p95 latency, numeric accuracy, completion rate, tool
  selection accuracy, recovery rate, token use, and estimated cost.
- The article reports platform limitations and failed experiments as well as
  wins.

## Current platform references

- [Enable incoming A2A on a Foundry agent](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint)
- [Get started with AgentCore Runtime (CLI)](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-cli.html)
- [AgentCore CLI](https://github.com/aws/agentcore-cli)
- [Bedrock AgentCore Python SDK](https://github.com/aws/bedrock-agentcore-sdk-python)
- [Strands Agents quickstart](https://strandsagents.com/docs/user-guide/quickstart/python/)
- [A2A protocol support in AgentCore Runtime](https://aws.amazon.com/blogs/machine-learning/introducing-agent-to-agent-protocol-support-in-amazon-bedrock-agentcore-runtime/)

These services and SDKs move quickly. Pin working versions once the first
end-to-end deployment succeeds, and record them in the article.
