---
title: "Foundry as Master, Bedrock as Remote: The Smoke Test Finally Passed"
description: "A measured cross-cloud smoke test: Microsoft Foundry orchestrates MCP and calls an Amazon Bedrock AgentCore specialist over authenticated A2A."
published: false
series: A2A
tags: azure, aws, aiagents, a2a
cover_image: https://raw.githubusercontent.com/xbill9/foundry-bedrock-a2a-currency/main/devto-cover-foundry-master.png
---

I wanted one specific piece of coverage:

```text
Microsoft Foundry (master)
    ├── MCP ──> live exchange-rate baseline
    └── A2A ──> Amazon Bedrock AgentCore (remote specialist)
```

On July 30, 2026, that direction worked end to end.

This matters because I had already tested the reverse topology—AgentCore as
coordinator and Foundry as remote. A cross-cloud claim based on only one
direction is weak. This run proves Foundry can own the request, execute its
local MCP baseline, call an AgentCore A2A agent, and apply deterministic
verification.

The code and sanitized evidence are in
[xbill9/foundry-bedrock-a2a-currency](https://github.com/xbill9/foundry-bedrock-a2a-currency).

## What actually passed

The input was `100 USD → EUR`. I invoked the Foundry-hosted coordinator through
its Responses endpoint in all three benchmark modes:

| Mode | Path | Observed result | Adapter time |
|---|---|---:|---:|
| `mcp_only` | Foundry → local MCP | 87.13800 EUR | 359 ms |
| `a2a_only` | Foundry → A2A → AgentCore | 87.138 EUR | 25,105 ms |
| `verified` | both paths concurrently | exact agreement | 28,163 ms |

The verified result reported:

```json
{
  "relative_difference": "0",
  "agreed": true,
  "failures": {}
}
```

That is one smoke case, not a latency distribution and not a completed
benchmark matrix. The useful conclusion is narrower: the Foundry-master cloud
boundary works, including authentication, discovery, invocation, and
deterministic comparison.

The repository also passes 66 deterministic tests; one optional integration
test is skipped without its external dependency.

## The model does not do the math

Currency conversion makes interoperability easy to falsify. Every quote carries
the amount, rate, converted amount, observation time, source, and adapter
latency. Money and rates use Python `Decimal`.

The coordinator—not an LLM—checks agreement:

```python
difference = abs(primary.converted_amount - verifier.converted_amount)
relative_difference = difference / abs(primary.converted_amount)
agreed = relative_difference <= Decimal("0.005")
```

The model handles intent and chooses one tool call. Framework-independent code
owns arithmetic, concurrency, timeout policy, and failure reporting.

## The boundary that survived the flip

The stable application depends on two interfaces:

- an MCP-backed `ExchangeRateTool`;
- an A2A-backed `RemoteCurrencyAgent`.

Microsoft Agent Framework and Foundry hosting sit outside those interfaces.
Strands and AgentCore sit outside them on the other side. Flipping the clouds
did not require rewriting the domain service.

That is more valuable than merely getting two SDKs into one process. Each cloud
can be deployed independently, and the benchmark can still compare MCP-only,
A2A-only, and verified execution.

## Authentication was the real cross-cloud problem

AgentCore's default runtime authorization is IAM/SigV4. That is appropriate for
AWS callers, but a Foundry-hosted container does not automatically have AWS
credentials.

For this test I configured AgentCore with a custom JWT authorizer and used a
Cognito machine-to-machine client:

```text
Foundry container
    ├── client_credentials ──> Cognito token endpoint
    └── Bearer JWT ──────────> AgentCore A2A runtime
```

The coordinator's A2A adapter now supports OAuth client credentials, caches the
token until shortly before expiry, and retains static bearer support for other
peer profiles. The AgentCore authorizer validates the issuer, client, and
required `currencybench/invoke` scope.

No token participates in the domain layer.

## What broke before the green run

The successful diagram hides most of the work. These were observed failures,
not hypothetical risks.

### 1. AgentCore's A2A server and the client wanted different SDK generations

The coordinator client uses A2A 1.x. AgentCore's A2A extra currently requires
the 0.3 line in the deployed server bundle. Installing both into the same
bundle produced an unsatisfiable dependency graph.

The fix was architectural: pin the AgentCore application bundle to its
compatible A2A SDK while keeping the Foundry-side client separate. The network
protocol interoperated even though the Python packages did not share a
version.

### 2. IAM authorization did not cross the cloud boundary

A direct AWS CLI invocation worked, but the Foundry container could not sign an
AWS request. Switching the runtime to custom JWT authorization and adding the
OAuth adapter made the remote callable without embedding AWS credentials.

### 3. The default ten-second timeout was false confidence

The first hosted `a2a_only` call failed cleanly:

```json
{
  "failures": {
    "a2a": "timeout: adapter timed out"
  },
  "elapsed_ms": 10010
}
```

A direct remote call had already taken about 25 seconds. The adapter was
working; the benchmark policy was too aggressive for a cold cross-cloud path.
The hosted timeout is now 60 seconds. The next A2A-only invocation completed in
25.1 seconds.

### 4. Foundry's source build could not find its image

The hosted-agent remote build repeatedly ended with `ImageError: Container
image not found`. I switched to a prebuilt, digest-pinned image in Azure
Container Registry.

The next failure was more precise: registry authentication. Three identities
were visible—the Foundry account, the project, and the per-agent runtime
identity. Image pull uses the **project managed identity**. Granting the other
two `AcrPull` did not help.

The deployment became active after:

- enabling ACR authentication-as-ARM;
- granting the project identity repository-reader/pull access; and
- redeploying the same digest-pinned image.

### 5. Azure resource state and RBAC both had memory

A soft-deleted Foundry account blocked recreation until it was purged. Project
role assignments also took time to propagate. Those are deployment-plane
facts, distinct from whether A2A works at runtime.

## The smoke result

In verified mode, Foundry started both adapters. Its MCP leg returned rate
`0.87138`; the AgentCore specialist returned rate `0.87138`. Deterministic code
computed a relative difference of zero and marked the quotes as agreed.

The MCP result also carried a stale-observation warning. The coordinator
preserved it rather than letting the model smooth it away.

The hosted response took about 45 seconds end to end while the measured adapter
work took 28.2 seconds. That gap includes model and hosted-response overhead.
With one observation, it would be irresponsible to call either number a
benchmark.

## What this proves—and what it does not

Observed:

- Foundry hosted the master coordinator.
- Foundry's MCP-only path completed.
- Foundry acquired an OAuth token and invoked AgentCore over A2A.
- AgentCore returned a structured currency quote.
- Verified mode ran both paths and reported exact agreement.
- The three-mode smoke completed without adapter failures after the timeout
  correction.

Not yet established:

- warm and cold latency distributions;
- behavior under throttling or token expiry;
- a full multi-currency matrix;
- production secret rotation and availability controls;
- superiority of either framework or cloud.

That distinction is the point of the project. The result is coverage, not a
victory lap: Microsoft Foundry works as the main cloud, and Amazon Bedrock
AgentCore works as its authenticated remote A2A specialist.
