from types import SimpleNamespace

import pytest

from coordinator.entra_auth import (
    EntraTokenProvider,
    StaticTokenProvider,
    build_token_provider,
    parse_service_principal,
    reset_token_providers,
)
from coordinator.errors import AdapterError, FailureKind


@pytest.fixture(autouse=True)
def _clear_provider_cache():
    """Providers are cached per process; keep that out of other tests."""
    yield
    import asyncio

    asyncio.run(reset_token_providers())


class FakeCredential:
    """Stands in for an azure-identity credential; counts token requests."""

    def __init__(self, expires_on: float = 2_000_000_000.0) -> None:
        self.calls = 0
        self._expires_on = expires_on

    async def get_token(self, scope: str):
        self.calls += 1
        return SimpleNamespace(token=f"token-{self.calls}", expires_on=self._expires_on)

    async def close(self) -> None:
        return None


def test_parse_service_principal_accepts_both_key_spellings() -> None:
    plain = parse_service_principal('{"tenant_id": "t", "client_id": "c", "client_secret": "s"}')
    prefixed = parse_service_principal(
        '{"AZURE_TENANT_ID": "t", "AZURE_CLIENT_ID": "c", "AZURE_CLIENT_SECRET": "s"}'
    )

    assert plain == {"tenant_id": "t", "client_id": "c", "client_secret": "s"}
    assert prefixed == plain


@pytest.mark.parametrize(
    "payload",
    ['{"tenant_id": "t", "client_id": "c"}', "not json", '["t", "c", "s"]'],
)
def test_malformed_service_principal_is_an_authentication_failure(payload: str) -> None:
    with pytest.raises(AdapterError) as excinfo:
        parse_service_principal(payload)

    assert excinfo.value.kind is FailureKind.AUTHENTICATION


@pytest.mark.asyncio
async def test_token_is_cached_until_it_nears_expiry() -> None:
    provider = EntraTokenProvider()
    credential = FakeCredential()
    provider._credential = credential

    assert await provider.token() == "token-1"
    assert await provider.token() == "token-1"
    # AzureCliCredential shells out to `az` on every call, so a cache miss per
    # conversion would land in the measured A2A latency.
    assert credential.calls == 1


@pytest.mark.asyncio
async def test_expired_token_is_refetched() -> None:
    provider = EntraTokenProvider()
    provider._credential = FakeCredential(expires_on=0.0)

    assert await provider.token() == "token-1"
    assert await provider.token() == "token-2"


@pytest.mark.asyncio
async def test_credential_failure_is_typed_as_authentication() -> None:
    class BrokenCredential(FakeCredential):
        async def get_token(self, scope: str):
            raise RuntimeError("no identity available")

    provider = EntraTokenProvider()
    provider._credential = BrokenCredential()

    with pytest.raises(AdapterError) as excinfo:
        await provider.token()

    assert excinfo.value.kind is FailureKind.AUTHENTICATION


@pytest.mark.asyncio
async def test_env_token_short_circuits_the_credential_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURRENCY_A2A_BEARER_TOKEN", "pre-minted")

    provider = build_token_provider()

    assert isinstance(provider, StaticTokenProvider)
    assert await provider.token() == "pre-minted"


def test_secret_id_selects_the_service_principal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CURRENCY_A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("CURRENCY_AZURE_SECRET_ID", "bedrock-foundry-a2a/sp")

    provider = build_token_provider()

    assert isinstance(provider, EntraTokenProvider)
    assert provider._aws_secret_id == "bedrock-foundry-a2a/sp"


def test_providers_are_reused_per_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CURRENCY_A2A_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("CURRENCY_AZURE_SECRET_ID", "bedrock-foundry-a2a/reuse")

    # A fresh credential per conversion would discard the token cache and leak
    # an unclosed session on every run.
    assert build_token_provider() is build_token_provider()

    monkeypatch.setenv("CURRENCY_AZURE_SECRET_ID", "bedrock-foundry-a2a/other")
    assert build_token_provider() is not build_token_provider("https://other/.default")
