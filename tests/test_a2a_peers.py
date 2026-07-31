import pytest

from coordinator.a2a_peers import (
    ADK_PEER,
    BEDROCK_PEER,
    FOUNDRY_PEER,
    get_peer,
    resolve_endpoint,
)
from coordinator.a2a_remote import A2ARemoteCurrencyAgent, build_remote_agent, status_failure_kind
from coordinator.entra_auth import StaticTokenProvider
from coordinator.errors import FailureKind


def test_default_peer_is_the_bedrock_agent() -> None:
    assert get_peer(None) is BEDROCK_PEER
    assert get_peer("FOUNDRY") is FOUNDRY_PEER


def test_unknown_peer_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown A2A peer"):
        get_peer("openai")


def test_peers_read_only_their_own_endpoint_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURRENCY_A2A_ENDPOINT", "https://adk.example")
    monkeypatch.delenv("CURRENCY_FOUNDRY_A2A_ENDPOINT", raising=False)

    assert resolve_endpoint(ADK_PEER) == "https://adk.example"
    # No cross-peer fallback: an Entra-signed request to the ADK agent would
    # fail as a confusing 404 rather than as missing configuration.
    assert resolve_endpoint(FOUNDRY_PEER) is None
    assert resolve_endpoint(FOUNDRY_PEER, "https://foundry.example") == "https://foundry.example"


def test_build_remote_agent_without_an_endpoint_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CURRENCY_A2A_ENDPOINT", raising=False)
    monkeypatch.delenv("CURRENCY_FOUNDRY_A2A_ENDPOINT", raising=False)

    assert build_remote_agent(peer="foundry") is None


def test_build_remote_agent_labels_quotes_by_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURRENCY_FOUNDRY_A2A_ENDPOINT", "https://foundry.example/a2a")
    monkeypatch.setenv("CURRENCY_A2A_BEARER_TOKEN", "token")

    agent = build_remote_agent(peer="foundry")

    assert agent is not None
    assert agent.peer_name == "foundry"
    assert agent.source == "hosted-foundry-a2a"


@pytest.mark.asyncio
async def test_foundry_headers_carry_the_token_and_pin_v1() -> None:
    agent = A2ARemoteCurrencyAgent(
        "https://foundry.example/a2a",
        peer=FOUNDRY_PEER,
        token_provider=StaticTokenProvider("abc123"),
    )

    headers = await agent._headers()

    assert headers["Authorization"] == "Bearer abc123"
    # Foundry serves A2A v0.3 unless the caller pins v1.0.
    assert headers["A2A-Version"] == "1.0"


@pytest.mark.asyncio
async def test_adk_peer_sends_no_authorization_header() -> None:
    agent = A2ARemoteCurrencyAgent("https://adk.example", peer=ADK_PEER)

    assert await agent._headers() == {}


@pytest.mark.asyncio
async def test_bedrock_peer_uses_its_runtime_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURRENCY_BEDROCK_A2A_BEARER_TOKEN", "runtime-token")
    agent = A2ARemoteCurrencyAgent("https://bedrock.example/invocations/", peer=BEDROCK_PEER)

    assert await agent._headers() == {"Authorization": "Bearer runtime-token"}


def test_rejected_credentials_are_authentication_not_transport() -> None:
    assert status_failure_kind(401) is FailureKind.AUTHENTICATION
    assert status_failure_kind(403) is FailureKind.AUTHENTICATION
    assert status_failure_kind(503) is FailureKind.TRANSPORT
