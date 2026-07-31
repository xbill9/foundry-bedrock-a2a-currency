import httpx
import pytest

from coordinator.oauth_auth import ClientCredentialsTokenProvider


@pytest.mark.asyncio
async def test_client_credentials_token_is_cached() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"access_token": "jwt", "expires_in": 3600},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ClientCredentialsTokenProvider(
            "https://auth.example/token",
            "client",
            "secret",
            scope="currency/invoke",
            client=client,
        )
        assert await provider.token() == "jwt"
        assert await provider.token() == "jwt"

    assert len(requests) == 1
    assert b"grant_type=client_credentials" in requests[0].content
    assert b"scope=currency%2Finvoke" in requests[0].content
    assert requests[0].headers["Authorization"].startswith("Basic ")
