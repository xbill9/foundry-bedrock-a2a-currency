# Microsoft Foundry master coordinator

This bundle hosts the benchmark's master agent in Microsoft Foundry:

```text
client → Foundry coordinator
             ├── MCP stdio → Frankfurter
             └── A2A v1.0 → Bedrock AgentCore currency specialist
```

The Microsoft Agent Framework model calls `run_currency_benchmark`; the
framework-independent coordinator performs all orchestration and uses
`Decimal` for quote comparison. The model never performs arithmetic.

Deploy the AgentCore A2A runtime first, then:

```bash
export CURRENCY_BEDROCK_A2A_ENDPOINT='https://.../invocations/'
export CURRENCY_BEDROCK_A2A_BEARER_TOKEN='...'
az login && azd auth login
./infra/deploy_foundry_peer.sh
```

The deploy script stores the bearer value as a secret in the azd environment.
Do not put tokens in `azure.yaml`, `.env`, logs, or benchmark evidence.

`coordinator/` and `mcp_server/` here are generated bundle copies. Edit the
root packages and run `infra/sync_app.sh`.
