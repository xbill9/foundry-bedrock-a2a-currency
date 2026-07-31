"""Microsoft Entra bearer tokens for the Foundry incoming-A2A endpoint.

Every Foundry A2A URL — including the agent card — requires an Entra token; key
and anonymous access are not supported. The coordinator runs on AWS AgentCore,
which has no Azure identity of its own, so the token has to come from one of:

1. ``CURRENCY_A2A_BEARER_TOKEN`` — a pre-minted token, for short manual runs
   and tests. Never commit one.
2. ``CURRENCY_AZURE_SECRET_ID`` — an AWS Secrets Manager secret holding the
   service principal (``tenant_id``/``client_id``/``client_secret``). This is
   the hosted path: the AgentCore execution role reads the secret, so no Azure
   secret is ever stored in ``agentcore/agentcore.json``.
3. The ambient Azure credential chain (``az login``, ``AZURE_*`` environment
   variables, managed identity). This is the local-development path.

Token acquisition is cached until shortly before expiry: ``AzureCliCredential``
shells out to ``az`` on every call, which would otherwise be charged to the
measured A2A latency.
"""

import asyncio
import json
import os
import time
from typing import Protocol

from coordinator.errors import AdapterError, FailureKind

DEFAULT_SCOPE = "https://ai.azure.com/.default"
_REFRESH_MARGIN_SECONDS = 300


class TokenProvider(Protocol):
    async def token(self) -> str: ...

    async def aclose(self) -> None: ...


class StaticTokenProvider:
    """Returns a token supplied out of band (env var, test fixture)."""

    def __init__(self, value: str) -> None:
        self._value = value

    async def token(self) -> str:
        return self._value

    async def aclose(self) -> None:
        return None


class EntraTokenProvider:
    """Acquires and caches an Entra access token for a resource scope."""

    def __init__(
        self,
        scope: str = DEFAULT_SCOPE,
        *,
        aws_secret_id: str | None = None,
        refresh_margin_seconds: int = _REFRESH_MARGIN_SECONDS,
    ) -> None:
        self._scope = scope
        self._aws_secret_id = aws_secret_id
        self._refresh_margin = refresh_margin_seconds
        self._credential = None
        self._cached: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        async with self._lock:
            if self._cached and self._cached[1] - self._refresh_margin > time.time():
                return self._cached[0]
            credential = await self._get_credential()
            try:
                access = await credential.get_token(self._scope)
            except Exception as exc:  # azure-identity raises a family of errors
                raise AdapterError(
                    FailureKind.AUTHENTICATION,
                    f"could not acquire an Entra token for {self._scope}: {exc}",
                ) from exc
            self._cached = (access.token, float(access.expires_on))
            return access.token

    async def aclose(self) -> None:
        if self._credential is not None:
            await self._credential.close()
            self._credential = None

    async def _get_credential(self):
        if self._credential is not None:
            return self._credential
        try:
            from azure.identity.aio import ClientSecretCredential, DefaultAzureCredential
        except ImportError as exc:
            raise AdapterError(
                FailureKind.AUTHENTICATION,
                "azure-identity is required to call a Foundry A2A endpoint; "
                "install it or set CURRENCY_A2A_BEARER_TOKEN",
            ) from exc

        if self._aws_secret_id:
            principal = await load_service_principal(self._aws_secret_id)
            self._credential = ClientSecretCredential(**principal)
        else:
            self._credential = DefaultAzureCredential()
        return self._credential


def parse_service_principal(secret_string: str) -> dict[str, str]:
    """Map an AWS Secrets Manager payload onto ClientSecretCredential kwargs.

    Accepts both ``tenant_id``-style and ``AZURE_TENANT_ID``-style keys so the
    same secret can be consumed by this code or exported as environment
    variables.
    """
    try:
        raw = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise AdapterError(
            FailureKind.AUTHENTICATION,
            f"Azure service-principal secret is not JSON: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise AdapterError(
            FailureKind.AUTHENTICATION,
            "Azure service-principal secret must be a JSON object",
        )
    lowered = {str(key).lower().removeprefix("azure_"): value for key, value in raw.items()}
    try:
        return {
            "tenant_id": str(lowered["tenant_id"]),
            "client_id": str(lowered["client_id"]),
            "client_secret": str(lowered["client_secret"]),
        }
    except KeyError as exc:
        raise AdapterError(
            FailureKind.AUTHENTICATION,
            f"Azure service-principal secret is missing {exc.args[0]}",
        ) from exc


async def load_service_principal(secret_id: str) -> dict[str, str]:
    """Read the service principal from AWS Secrets Manager (off the event loop)."""

    def fetch() -> str:
        import boto3

        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION"))
        return client.get_secret_value(SecretId=secret_id)["SecretString"]

    try:
        secret_string = await asyncio.to_thread(fetch)
    except AdapterError:
        raise
    except Exception as exc:  # botocore raises a family of client errors
        raise AdapterError(
            FailureKind.AUTHENTICATION,
            f"could not read Azure credentials from AWS secret {secret_id}: {exc}",
        ) from exc
    return parse_service_principal(secret_string)


_PROVIDERS: dict[tuple[str, str | None], TokenProvider] = {}


def build_token_provider(scope: str = DEFAULT_SCOPE) -> TokenProvider:
    """Pick a token source from the environment (see the module docstring).

    Providers are cached per process. The coordinator builds a fresh remote
    agent for every conversion, and a per-call credential would both discard
    the token cache and leak an unclosed HTTP session on each run.
    """
    if token := os.getenv("CURRENCY_A2A_BEARER_TOKEN"):
        return StaticTokenProvider(token)
    key = (os.getenv("CURRENCY_ENTRA_SCOPE", scope), os.getenv("CURRENCY_AZURE_SECRET_ID"))
    if key not in _PROVIDERS:
        _PROVIDERS[key] = EntraTokenProvider(key[0], aws_secret_id=key[1])
    return _PROVIDERS[key]


async def reset_token_providers() -> None:
    """Drop cached credentials. For tests and for credential rotation."""
    for provider in list(_PROVIDERS.values()):
        await provider.aclose()
    _PROVIDERS.clear()
