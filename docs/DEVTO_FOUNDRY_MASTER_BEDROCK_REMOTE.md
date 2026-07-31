---
title: "Flipping A2A Around: Microsoft Foundry as the Master, Bedrock AgentCore as the Remote Agent"
published: false
series: A2A
tags: azure, aws, aiagents, a2a
---

I previously built this currency benchmark in the other direction:

```text
Amazon Bedrock AgentCore coordinator
    |
    +-- A2A --> Microsoft Foundry remote agent
```

That path worked, but it left a useful interoperability question unanswered:
does the same domain core still work when Microsoft Foundry owns orchestration
and Amazon Bedrock AgentCore becomes the remote A2A specialist?

I flipped the architecture:

```text
Microsoft Foundry coordinator
    |
    +-- MCP --> live exchange-rate baseline
    |
    +-- A2A v1.0 --> Bedrock AgentCore currency specialist
                           |
                           +-- MCP --> independent live conversion
```

The code is in
[xbill9/foundry-bedrock-a2a-currency](https://github.com/xbill9/foundry-bedrock-a2a-currency).

At the time of writing, the inverted implementation passes all 67 deterministic
tests. The new cloud direction has not yet been deployed and benchmarked, so
this post distinguishes the implemented architecture from the earlier observed
AWS-to-Azure results.

## This is a benchmark, not another chatbot

Currency conversion is useful here because it gives the system:

- a small, constrained domain;
- exact inputs and outputs;
- a public live data source;
- deterministic arithmetic; and
- obvious failure cases.

The master supports three modes:

| Mode | Execution path |
|---|---|
| `mcp_only` | Foundry calls the exchange-rate MCP adapter |
| `a2a_only` | Foundry delegates to the Bedrock A2A agent |
| `verified` | Both execute concurrently and deterministic code compares them |

The model never calculates an amount and never judges whether two answers
agree. Python `Decimal` owns both operations:

```python
difference = abs(primary.converted_amount - verifier.converted_amount)
relative_difference = difference / abs(primary.converted_amount)
agreed = relative_difference <= Decimal("0.005")
```

If the legs disagree, the coordinator returns both quotes and a warning. It
does not ask either model to choose the more convincing number.

## Why the flip matters

It would have been easy to rewrite the application around Microsoft Agent
Framework. That would make the comparison less useful.

Instead, the stable domain layer stayed independent of both vendors:

```text
coordinator/
    models.py          Decimal domain types
    service.py         three benchmark modes and fallback policy
    compare.py         deterministic verification
    adapters.py        framework-independent boundaries
    a2a_remote.py      A2A client adapter
    mcp_stdio.py       MCP client adapter
```

Only the hosting adapters traded places.

Foundry now hosts the master agent. Its model collects the amount, source
currency, target currencies, and benchmark mode, then invokes
`run_currency_benchmark` exactly once.

AgentCore now hosts a narrow Strands specialist. It exposes an A2A server and
has one currency tool backed by MCP.

That separation is the main design result: changing which cloud is “in charge”
does not change validation, arithmetic, comparison, or failure policy.

## The Foundry master

The Foundry entrypoint uses Microsoft Agent Framework and the responses hosting
server:

```python
from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer

from coordinator.hosted_tool import run_currency_benchmark

agent = Agent(
    client=FoundryChatClient(...),
    name="currency-coordinator",
    instructions=INSTRUCTION,
    tools=[tool(run_currency_benchmark)],
    default_options={"store": False},
)

ResponsesHostServer(agent).run()
```

The instruction is deliberately restrictive:

```text
For every conversion call run_currency_benchmark exactly once.
Never calculate or verify arithmetic yourself.
Preserve amounts, rates, timestamps, source labels, failures,
and warnings exactly.
```

The hosted model remains useful for intent handling and explanation. It is not
the system of record for money.

## The Bedrock remote agent

AgentCore Runtime supports A2A as a first-class runtime protocol. The remote
entrypoint wraps a Strands agent with `StrandsA2AExecutor` and starts it with
`serve_a2a`:

```python
from bedrock_agentcore.runtime import serve_a2a
from strands import Agent, tool
from strands.multiagent.a2a.executor import StrandsA2AExecutor

@tool
async def convert_currency(
    amount: str,
    source_currency: str,
    target_currencies: list[str],
) -> str:
    request = ConversionRequest(
        amount=Decimal(amount),
        source_currency=source_currency,
        target_currencies=target_currencies,
    )
    quotes = await McpStdioExchangeRateTool().convert(request)
    return serialize_quotes(quotes)

agent = Agent(
    model=load_model(),
    system_prompt=SYSTEM_PROMPT,
    tools=[convert_currency],
)

serve_a2a(StrandsA2AExecutor(agent))
```

The AgentCore manifest also changes from the ordinary HTTP runtime contract to:

```json
{
  "name": "CurrencyAgent",
  "protocol": "A2A",
  "entrypoint": "main.py"
}
```

According to the current AgentCore documentation, `serve_a2a` supplies the
agent card, health endpoint, Bedrock header propagation, and the stateless A2A
server expected on port 9000.

## A2A stays behind one adapter

The coordinator does not import Strands, Bedrock, or Microsoft Agent Framework.
It depends on a `RemoteCurrencyAgent` protocol.

The Bedrock-specific client settings live in a peer profile:

```python
BEDROCK_PEER = A2APeerProfile(
    name="bedrock",
    source="hosted-bedrock-a2a",
    rewrite_card_urls=False,
    token_env="CURRENCY_BEDROCK_A2A_BEARER_TOKEN",
    endpoint_env="CURRENCY_BEDROCK_A2A_ENDPOINT",
)
```

Earlier Google ADK and Foundry peer profiles remain in the repository. Keeping
them is intentional: the benchmark can reproduce earlier evidence without
putting old vendor conditions into the domain service.

## Authentication changes direction too

In the previous topology, AWS needed a Microsoft Entra identity to read the
Foundry card and invoke the remote agent.

After the flip, Foundry needs permission to call AgentCore Runtime. The current
adapter accepts:

```text
CURRENCY_BEDROCK_A2A_ENDPOINT
CURRENCY_BEDROCK_A2A_BEARER_TOKEN
```

The token is not committed to `azure.yaml`, `.env`, logs, or benchmark output.
The deployment script writes it to the local `azd` environment as a secret.

This is adequate for an initial authenticated smoke test, but token lifecycle
is part of the benchmark—not an implementation detail to hide. A production
version should use an appropriate renewable workload identity or OAuth
configuration rather than treating a short-lived token as static application
configuration.

## Failure behavior did not change

The coordinator preserves the same policy in either cloud direction:

- MCP fails, A2A succeeds: return the remote quote as explicitly unverified.
- A2A fails, MCP succeeds: return the MCP quote with verification missing.
- Both succeed but disagree: return both and warn.
- Both fail: return typed failures and fabricate nothing.
- Any quote is stale: retain it with its timestamp and add a warning.

Verified mode starts both legs concurrently:

```python
mcp_quotes, a2a_quotes = await asyncio.gather(
    call_mcp(),
    call_a2a(),
)
```

That means verified latency is normally dominated by the slower leg, not the
sum of both legs.

## Run the local benchmark

Clone and test:

```bash
git clone https://github.com/xbill9/foundry-bedrock-a2a-currency.git
cd foundry-bedrock-a2a-currency

pip3 install --user --break-system-packages -e ".[dev]"
python3 -m pytest -q
```

The current implementation passes 67 tests covering:

- `Decimal` conversion and comparison;
- all three orchestration modes;
- concurrent verification;
- timeout and fallback behavior;
- MCP subprocess transport;
- A2A card and response parsing;
- Foundry-shaped authenticated A2A behavior;
- the new default Bedrock peer and bearer header; and
- deployment-manifest assertions.

Exercise the credential-free fixtures:

```bash
python3 -m coordinator.cli 100 USD EUR --mode mcp_only
python3 -m coordinator.cli 100 USD EUR --mode a2a_only
python3 -m coordinator.cli \
  100 USD EUR --mode verified --transport mcp-stdio --json
```

Fixture rates validate orchestration. They are not live financial quotes.

## Deploy in the new order

Deploy Bedrock first because Foundry needs its A2A endpoint:

```bash
./infra/sync_app.sh
agentcore deploy -y
```

Retrieve the AgentCore runtime URL and authentication token through the
AgentCore CLI or AWS API. Then deploy the Foundry master:

```bash
export CURRENCY_BEDROCK_A2A_ENDPOINT="https://.../invocations/"
export CURRENCY_BEDROCK_A2A_BEARER_TOKEN="..."

az login
azd auth login
./infra/deploy_foundry_peer.sh
```

The script supplies the endpoint as configuration and the token as an azd
secret.

## What is observed and what is still a hypothesis

Observed:

- The earlier Bedrock-master to Foundry-remote topology completed all three
  hosted modes on July 29, 2026.
- Its smoke conversion for 100 USD to EUR agreed across MCP and A2A.
- The inverted code passes 67 local deterministic tests.
- The AgentCore runtime is configured for A2A and the Foundry host is configured
  as the coordinator.

Not yet observed:

- a deployed Foundry-to-Bedrock end-to-end request;
- the full 38-case inverted cloud matrix;
- warm and cold latency distributions;
- token use and cloud cost;
- runtime token renewal behavior; and
- cross-cloud trace correlation.

I would rather publish those as open measurements than imply that a green unit
test proves cloud interoperability.

## What this architecture lets us measure

Once the inverted deployment runs, the interesting comparison is no longer
“can A2A return HTTP 200?”

It is:

- Does orchestration direction change completion rate?
- Which platform has the larger cold-start contribution?
- How much latency comes from the model, MCP, authentication, and A2A?
- Does either direction recover more cleanly when one leg fails?
- How much glue is genuinely protocol-specific?
- Can the same 38 cases and deterministic scorers compare both directions
  without special treatment?

That is the point of flipping the architecture. A portable agent protocol is
most convincing when either framework can be the master and the benchmark
still means the same thing.

## References

- [Deploy A2A servers in Amazon Bedrock AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html)
- [A2A protocol contract for AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)
- [Microsoft Foundry hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)
- [Project source](https://github.com/xbill9/foundry-bedrock-a2a-currency)
