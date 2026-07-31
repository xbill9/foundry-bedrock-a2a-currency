# Google ADK agent

Runnable benchmark agent derived from `xbill9/currency-agent@aeef3c4`, with the
A2UI extension removed. See `agent.py` for why: `a2ui-agent-sdk` (through 0.4.0)
pins `a2a-sdk<0.4`, which serves the A2A v0.3.0 wire methods (`message/send`),
while A2A v1.0 clients (`a2a-sdk>=1.0`, including the Bedrock coordinator's
adapter) call the v1.0 methods (`SendMessage`). The two cannot interoperate;
upgrading to `google-adk==2.5.0` (the first release allowing `a2a-sdk<2`) and
dropping A2UI lets this agent serve A2A v1.0.

## Recorded interoperability findings

- `MethodNotFoundError` is the observable symptom of the v0.3.0/v1.0 skew:
  a2a-sdk 1.x clients call `SendMessage`; 0.3.x servers only route
  `message/send`. There is no version negotiation from the agent card. This
  affects any v1.0 client the same way, regardless of hosting cloud.
- The v1.0 agent card moved `url`/`protocolVersion` into `supportedInterfaces`.
- ADK's `to_a2a()` puts the server's *bind* address (e.g.
  `http://127.0.0.1:8080`) in `supportedInterfaces[].url`. a2a-sdk 1.x
  clients route transport by card URL and therefore fail cross-cloud unless
  they rewrite the card URLs to the known public endpoint (the Microsoft
  Agent Framework client ignored the card URL, masking this).
- ADK auto-advertises MCP tools (`get_exchange_rate`) as A2A skills on the card.
- With A2UI removed, replies arrive as plain text parts, which
  `coordinator/a2a_remote.py` parses as one JSON object per target currency.

## Run

The agent needs `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) in the environment.
Build and run it as a container so its Google SDK dependencies remain separate
from the AWS and Azure SDKs used by the coordinator. The image includes the MCP
exchange-rate server and defaults it to `http://127.0.0.1:8081/mcp`:

```bash
docker build -t currency-adk-a2a-local ./adk_agent
docker run --rm --name currency-adk-a2a-local \
  -p 10001:8080 \
  -e GOOGLE_API_KEY \
  currency-adk-a2a-local
```

In another terminal, verify with:

```bash
curl http://127.0.0.1:10001/health
curl http://127.0.0.1:10001/.well-known/agent-card.json
currency-benchmark 100 USD EUR --mode a2a_only --a2a-endpoint http://127.0.0.1:10001
```
