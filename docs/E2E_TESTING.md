# End-to-end testing

The benchmark runs at six tiers. Each tier adds one real dependency, so a
failure always points at the layer that was just introduced. Run them in
order when validating a change; run only tier 5 to smoke-test the deployed
system.

| Tier | What runs | Needs |
|---|---|---|
| 0 | Deterministic tests, fixture adapters, Foundry-shaped A2A server | nothing |
| 1 | Live ADK agent + live rates, local | Gemini key |
| 2 | Full 38-case matrix vs live local stack | Gemini key |
| 3 | Local coordinator → Cloud Run ADK agent | deployed `currency-adk-a2a` |
| 4 | Local coordinator → Foundry agent | deployed Foundry peer + `az login` |
| 5 | AgentCore-hosted coordinator → either peer | full deployment + AWS credentials |

## Prerequisites

- Python 3.13, `pip3 install --user --break-system-packages -e ".[dev]"`
  from the repo root, and
  `pip3 install --user --break-system-packages -r requirements.txt` for tiers 3–5.
- Docker for tiers 1–2. The ADK image keeps Google's SDK dependency set
  separate from the AWS and Azure coordinator dependencies.
- A Gemini API key exported as `GOOGLE_API_KEY` (tiers 1–2). Keep
  `GOOGLE_GENAI_USE_VERTEXAI` unset.
- `az login` with the **Foundry Agent Consumer** role on the Foundry project
  (tier 4).
- AWS credentials with `bedrock-agentcore:InvokeAgentRuntime` on the deployed
  runtime, e.g. via `aws configure` or SSO (tier 5).

The three sibling repositories install the same `currency-benchmark` and
`currency-evaluate` console scripts, so whichever clone was installed last is
the one on `PATH`. Run `python3 -m coordinator.cli …` and
`python3 -m evaluations.runner …` from the clone you mean to test.

## Tier 0 — deterministic core (no credentials)

```bash
pytest
currency-benchmark 100 USD EUR --mode verified --transport mcp-stdio
```

Expect 66 tests passing and a fixture-labeled quote
(`mcp-stdio:deterministic-fixture`). Anything failing here is a code
regression, not an integration problem.

Tier 0 covers more than fixtures. `tests/test_a2a_foundry_shape.py` stands up
a local A2A server with Foundry's shape — card at `agentCard/v1.0`, a bearer
token required on every request including the card, and the agent's real URL
already in the card — and drives it through the same adapter the deployed
coordinator uses. A regression in the Foundry client path fails here rather
than after a deployment.

## Tier 1 — live local stack

Build and start the benchmark ADK image. It serves A2A v1.0 on host port 10001
and runs its MCP rate server inside the same container:

```bash
docker build -t currency-adk-a2a-local ./adk_agent
docker run --rm --name currency-adk-a2a-local \
  -p 10001:8080 -e GOOGLE_API_KEY \
  currency-adk-a2a-local
```

Then, from another terminal:

```bash
curl -s http://127.0.0.1:10001/health
```

Then, from the repo root, run all three modes against it:

```bash
CURRENCY_RATE_PROVIDER=frankfurter currency-benchmark 250 GBP USD JPY \
  --mode verified --transport mcp-stdio \
  --a2a-endpoint http://127.0.0.1:10001 --timeout-seconds 60
```

Expect quotes labeled `mcp-stdio:frankfurter-live` with ` verified` suffixes.
A missing suffix plus a warning means one side failed — the failure kind in
the output says which.

## Tier 2 — full evaluation matrix

```bash
CURRENCY_RATE_PROVIDER=frankfurter currency-evaluate \
  --a2a-endpoint http://127.0.0.1:10001 --live-rates \
  --output evaluations/results/live-$(date +%F).jsonl \
  --summary evaluations/results/summary-live-$(date +%F).json
```

38 cases x 3 modes = 114 records; fault-free cases use the live adapters,
fault-injection cases stay deterministic (a live agent cannot be ordered to
time out). Takes a few minutes; exit code 0 means every case met its expected
behavior. Compare against the retained baselines
`evaluations/results/live-2026-07-27.jsonl` (Microsoft-client stack) and
`live-2026-07-28-run2.jsonl` (a2a-sdk stack; success 1.0 in all modes; the
only `agreed: false` should be case `a2a-disagreement`).

## Tier 3 — cross-cloud from the local coordinator

Requires the Cloud Run deployment (`infra/deploy_live.sh` steps 1–2, or see
`adk_agent/README.md`). The deployment script requires `GCP_PROJECT`; it never
stores a project ID or local key path in Git.

```bash
A2A_URL=$(gcloud run services describe currency-adk-a2a \
  --region us-central1 --format='value(status.url)')
curl -s "$A2A_URL/health"
CURRENCY_RATE_PROVIDER=frankfurter currency-benchmark 250 GBP USD JPY \
  --mode verified --transport mcp-stdio \
  --a2a-endpoint "$A2A_URL" --timeout-seconds 60
```

Keep `--timeout-seconds 60`: a Cloud Run cold start plus multi-target
generation exceeds the 10 s default, and cold starts can also produce
partial replies (typed as `protocol` failures — rerun once warm before
concluding anything is broken).

## Tier 4 — cross-cloud to the Foundry agent

Requires `infra/deploy_foundry_peer.sh`. Locally the ambient `az login`
credential is used; the service principal in AWS Secrets Manager only matters
once the coordinator itself is hosted (tier 5).

```bash
export CURRENCY_FOUNDRY_A2A_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>/agents/currency-a2a-agent/endpoint/protocols/a2a"
CURRENCY_RATE_PROVIDER=frankfurter python3 -m coordinator.cli 250 GBP USD JPY \
  --mode verified --transport mcp-stdio \
  --a2a-peer foundry --timeout-seconds 60
```

Expect verifier quotes labeled `hosted-foundry-a2a`. Unlike the Cloud Run
agent, this endpoint cannot be checked with a bare `curl` — the agent card
itself requires a token:

```bash
TOKEN=$(az account get-access-token --resource https://ai.azure.com \
  --query accessToken -o tsv)
curl -s -H "Authorization: Bearer $TOKEN" \
  "$CURRENCY_FOUNDRY_A2A_ENDPOINT/agentCard/v1.0" | head -20
```

A 401/403 there with a valid token means the role assignment is missing, not
that A2A is misconfigured. The coordinator reports it as an `authentication`
failure rather than a protocol error, which is the distinction that matters
when the article claims a failure was an auth failure.

Run the same cases against each peer to compare the legs:

```bash
python3 -m evaluations.runner --a2a-peer foundry --live-rates \
  --output evaluations/results/foundry-$(date +%F).jsonl
python3 -m evaluations.runner --a2a-peer adk --a2a-endpoint "$A2A_URL" --live-rates \
  --output evaluations/results/adk-$(date +%F).jsonl
```

## Tier 5 — fully hosted (AWS -> GCP or AWS -> Azure)

Requires the full deployment (`infra/deploy_live.sh`) and AWS credentials
with `bedrock-agentcore:InvokeAgentRuntime` on the runtime ARN (see
`infra/README.md`). For the Foundry leg, run
`infra/configure_azure_secret.sh` and `infra/point_coordinator_at_foundry.sh`
first: the hosted coordinator has no ambient Azure identity.

```bash
export AGENTCORE_RUNTIME_ARN="arn:aws:bedrock-agentcore:REGION:ACCOUNT:runtime/NAME"
python3 -m evaluations.invoke_hosted "Convert 500 EUR to USD and CHF in verified mode."
python3 -m evaluations.invoke_hosted "Convert 500 EUR to USD in mcp_only mode."
python3 -m evaluations.invoke_hosted "Convert 500 EUR to USD in a2a_only mode."
```

Expect the verified run to include `"agreed": true` with sources
`mcp-stdio:frankfurter-live` (rates fetched inside the AgentCore container)
and the configured peer's label — `hosted-adk-a2a` (Cloud Run) or
`hosted-foundry-a2a` (Foundry). This exercises every hop: SigV4 auth, the
AgentCore invocation contract, Nova Micro tool selection on Bedrock, MCP
stdio, and the cross-cloud A2A v1.0 call — plus, on the Foundry leg, a
Secrets Manager read and an Entra client-credentials exchange. The
equivalent Azure-hosted tier passed on 2026-07-27; the AWS→GCP leg passed on
2026-07-28 (all three modes, verified mode in agreement). The AWS→Azure leg
has not been run yet.

## Known transient failures
- Empty-message provider timeouts locally — IPv6 hang; the provider and the
  A2A adapter pin IPv4, but other HTTP paths in new code may need the same
  treatment.
- First request after Cloud Run scale-to-zero is slow (~10 s) and
  occasionally incomplete; warm requests are the meaningful signal.
- `AzureCliCredential` shells out to `az`, so the first Foundry call in a
  process can be seconds slower than the rest. The token is cached until
  shortly before expiry; measure warm calls.
