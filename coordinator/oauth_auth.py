"""Cached OAuth 2.0 client-credentials tokens for remote A2A peers."""

import asyncio
import time

import httpx

from coordinator.errors import AdapterError, FailureKind


class ClientCredentialsTokenProvider:
    """Acquire and cache a machine token without exposing SDKs to domain code."""

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        scope: str,
        refresh_margin_seconds: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._scope = scope
        self._refresh_margin = refresh_margin_seconds
        self._client = client
        self._cached: tuple[str, float] | None = None
        self._lock = asyncio.Lock()

    async def token(self) -> str:
        async with self._lock:
            if self._cached and self._cached[1] - self._refresh_margin > time.time():
                return self._cached[0]
            try:
                if self._client is not None:
                    response = await self._request(self._client)
                else:
                    async with httpx.AsyncClient(timeout=15) as client:
                        response = await self._request(client)
                response.raise_for_status()
                payload = response.json()
                token = str(payload["access_token"])
                expires_in = float(payload.get("expires_in", 300))
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
                raise AdapterError(
                    FailureKind.AUTHENTICATION,
                    f"OAuth client-credentials exchange failed: {exc}",
                ) from exc
            self._cached = (token, time.time() + expires_in)
            return token

    async def _request(self, client: httpx.AsyncClient) -> httpx.Response:
        return await client.post(
            self._token_url,
            data={"grant_type": "client_credentials", "scope": self._scope},
            auth=(self._client_id, self._client_secret),
        )

    async def aclose(self) -> None:
        return None
