"""A2A peer profiles: what differs between the remote agents we call.

The production topology calls the Bedrock AgentCore agent from the
Foundry-hosted coordinator. Earlier peer profiles remain reproducible:

- ``bedrock`` — a Strands agent hosted by Bedrock AgentCore Runtime.
- ``adk`` — the Google ADK agent on Cloud Run. Anonymous, standard
  ``/.well-known/agent-card.json`` discovery, and a card that advertises the
  server's bind address rather than its public URL.
- ``foundry`` — a Microsoft Foundry hosted agent with incoming A2A enabled.
  Entra-authenticated (card included), a non-standard card path, and JSONRPC
  only. Foundry serves A2A v0.3 unless the caller pins v1.0, so the version
  header is sent explicitly rather than relying on card negotiation alone.

Everything protocol-shaped lives here so ``a2a_remote`` stays a single code
path and the article can point at one file for "what cross-vendor A2A actually
costs you".
"""

import os
from dataclasses import dataclass, field

from coordinator.entra_auth import DEFAULT_SCOPE

FOUNDRY_AGENT_CARD_PATH = "agentCard/v1.0"


@dataclass(frozen=True)
class A2APeerProfile:
    """Vendor-specific A2A client settings."""

    name: str
    source: str
    agent_card_path: str = "/.well-known/agent-card.json"
    #: Rewrite the card's advertised interface URLs to the configured endpoint.
    #: Needed for agents that publish their bind address; harmful for agents
    #: whose card already carries the correct public URL.
    rewrite_card_urls: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)
    #: Entra scope to mint a bearer token for, or None for anonymous peers.
    auth_scope: str | None = None
    token_env: str | None = None
    #: Environment variable holding this peer's base URL.
    endpoint_env: str = "CURRENCY_A2A_ENDPOINT"


ADK_PEER = A2APeerProfile(
    name="adk",
    source="hosted-adk-a2a",
    endpoint_env="CURRENCY_A2A_ENDPOINT",
)

BEDROCK_PEER = A2APeerProfile(
    name="bedrock",
    source="hosted-bedrock-a2a",
    rewrite_card_urls=False,
    token_env="CURRENCY_BEDROCK_A2A_BEARER_TOKEN",
    endpoint_env="CURRENCY_BEDROCK_A2A_ENDPOINT",
)

FOUNDRY_PEER = A2APeerProfile(
    name="foundry",
    source="hosted-foundry-a2a",
    agent_card_path=FOUNDRY_AGENT_CARD_PATH,
    rewrite_card_urls=False,
    extra_headers={"A2A-Version": "1.0"},
    auth_scope=DEFAULT_SCOPE,
    endpoint_env="CURRENCY_FOUNDRY_A2A_ENDPOINT",
)

PEERS: dict[str, A2APeerProfile] = {
    BEDROCK_PEER.name: BEDROCK_PEER,
    ADK_PEER.name: ADK_PEER,
    FOUNDRY_PEER.name: FOUNDRY_PEER,
}

DEFAULT_PEER = BEDROCK_PEER.name


def get_peer(name: str | None) -> A2APeerProfile:
    key = (name or DEFAULT_PEER).strip().lower()
    try:
        return PEERS[key]
    except KeyError:
        raise ValueError(f"unknown A2A peer {name!r}; expected one of {sorted(PEERS)}") from None


def resolve_endpoint(profile: A2APeerProfile, override: str | None = None) -> str | None:
    """Return the peer's base URL from an explicit override or its own variable.

    Each peer reads its own variable and never falls back to another peer's:
    sending an Entra-authenticated Foundry request to the Cloud Run agent would
    fail as a confusing 404 rather than as an obvious missing-configuration
    error.
    """
    return override or os.getenv(profile.endpoint_env)
