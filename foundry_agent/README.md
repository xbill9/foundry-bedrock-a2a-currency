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
export CURRENCY_BEDROCK_OAUTH_TOKEN_URL='https://.../oauth2/token'
export CURRENCY_BEDROCK_OAUTH_CLIENT_ID='...'
export CURRENCY_BEDROCK_OAUTH_CLIENT_SECRET='...'
export CURRENCY_BEDROCK_OAUTH_SCOPE='currencybench/invoke'
az login && azd auth login
./infra/deploy_foundry_peer.sh
```

The deploy script registers the settings with the hosted agent, which obtains
short-lived access tokens at runtime. Do not put the client secret or tokens in
tracked files, logs, or benchmark evidence.

`coordinator/` and `mcp_server/` here are generated bundle copies. Edit the
root packages and run `infra/sync_app.sh`.
