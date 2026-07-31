"""Prove the Foundry A2A client path without an Azure subscription.

Foundry differs from the ADK agent in four ways that all live on the client
side: the agent card sits at ``agentCard/v1.0`` instead of the well-known
path, every request (card included) needs an Entra bearer token, the card
already carries its real public URL, and v1.0 must be pinned or Foundry serves
v0.3. This test serves that shape locally with the a2a-sdk's own server routes,
so a regression in any of the four fails here rather than after a deployment.

It does not test Foundry itself — only that the client speaks the shape
Foundry documents.
"""

import asyncio
import threading
from decimal import Decimal

import pytest

from coordinator.a2a_peers import FOUNDRY_PEER
from coordinator.a2a_remote import A2ARemoteCurrencyAgent
from coordinator.entra_auth import StaticTokenProvider
from coordinator.errors import AdapterError, FailureKind
from coordinator.models import ConversionRequest

pytest.importorskip("uvicorn")
pytest.importorskip("starlette")

import uvicorn  # noqa: E402
from a2a.helpers import new_text_message  # noqa: E402
from a2a.server.agent_execution import AgentExecutor  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.routes import create_jsonrpc_routes  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore  # noqa: E402
from a2a.types.a2a_pb2 import AgentCard, Role  # noqa: E402
from google.protobuf.json_format import ParseDict  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402

# The path shape Foundry publishes: …/agents/{agent}/endpoint/protocols/a2a
BASE_PATH = "/api/projects/proj/agents/currency-a2a-agent/endpoint/protocols/a2a"
CARD_PATH = f"{BASE_PATH}/agentCard/v1.0"
TOKEN = "test-entra-token"
PORT = 18808
REPLY = (
    '{"source_currency": "USD", "target_currency": "EUR", "rate": 0.85, "converted_amount": 85}\n'
    '{"source_currency": "USD", "target_currency": "JPY", "rate": 150, "converted_amount": 15000}'
)


def card_document(port: int) -> dict:
    return {
        "name": "currency-a2a-agent",
        "description": "Foundry-shaped benchmark peer",
        "version": "1.0",
        "supportedInterfaces": [
            {
                "url": f"http://127.0.0.1:{port}{BASE_PATH}",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "currency-conversion",
                "name": "Currency conversion",
                "description": "Converts an amount between currencies",
                "tags": ["currency"],
            }
        ],
    }


class QuoteExecutor(AgentExecutor):
    """Replies with the benchmark's one-JSON-object-per-target contract."""

    async def execute(self, context, event_queue) -> None:
        await event_queue.enqueue_event(new_text_message(REPLY, role=Role.ROLE_AGENT))

    async def cancel(self, context, event_queue) -> None:
        raise NotImplementedError


def build_app(port: int, seen: dict[str, dict[str, str]]) -> Starlette:
    document = card_document(port)
    handler = DefaultRequestHandler(
        agent_executor=QuoteExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=ParseDict(document, AgentCard()),
    )

    async def agent_card_route(request):
        return JSONResponse(document)

    async def require_bearer(request, call_next):
        seen[request.url.path] = dict(request.headers)
        if request.headers.get("authorization") != f"Bearer {TOKEN}":
            # Foundry rejects anonymous callers at every A2A URL, card included.
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    routes = [Route(CARD_PATH, agent_card_route, methods=["GET"])]
    routes.extend(create_jsonrpc_routes(handler, rpc_url=BASE_PATH))
    return Starlette(
        routes=routes,
        middleware=[Middleware(BaseHTTPMiddleware, dispatch=require_bearer)],
    )


class FoundryShapedServer:
    def __init__(self, port: int = PORT) -> None:
        self.port = port
        self.seen: dict[str, dict[str, str]] = {}
        self._server = uvicorn.Server(
            uvicorn.Config(
                build_app(port, self.seen), host="127.0.0.1", port=port, log_level="warning"
            )
        )

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}{BASE_PATH}"

    async def __aenter__(self) -> "FoundryShapedServer":
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        for _ in range(200):
            if self._server.started:
                return self
            await asyncio.sleep(0.05)
        raise RuntimeError("the Foundry-shaped test server did not start")

    async def __aexit__(self, *exc_info) -> None:
        self._server.should_exit = True
        await asyncio.to_thread(self._thread.join, 10)


def conversion_request() -> ConversionRequest:
    return ConversionRequest(
        amount=Decimal(100), source_currency="USD", target_currencies=["EUR", "JPY"]
    )


@pytest.mark.asyncio
async def test_authenticated_call_through_the_foundry_card_path() -> None:
    async with FoundryShapedServer() as server:
        agent = A2ARemoteCurrencyAgent(
            server.endpoint,
            peer=FOUNDRY_PEER,
            token_provider=StaticTokenProvider(TOKEN),
            timeout_s=30,
        )
        quotes = await agent.convert(conversion_request())

        assert [quote.target_currency for quote in quotes] == ["EUR", "JPY"]
        assert quotes[0].rate == Decimal("0.85")
        assert all(quote.source == "hosted-foundry-a2a" for quote in quotes)

        # The token and the pinned version must reach the card fetch and the
        # JSONRPC call; missing either is a deployment-time-only failure.
        for path in (CARD_PATH, BASE_PATH):
            assert server.seen[path]["authorization"] == f"Bearer {TOKEN}"
            assert server.seen[path]["a2a-version"] == "1.0"


@pytest.mark.asyncio
async def test_rejected_token_is_reported_as_authentication() -> None:
    async with FoundryShapedServer(port=PORT + 1) as server:
        agent = A2ARemoteCurrencyAgent(
            server.endpoint,
            peer=FOUNDRY_PEER,
            token_provider=StaticTokenProvider("wrong-token"),
            timeout_s=30,
        )

        with pytest.raises(AdapterError) as excinfo:
            await agent.convert(conversion_request())

    # The card resolver hides the HTTP status inside its own error type; if
    # that unwrapping regresses, a bad credential looks like a protocol bug.
    assert excinfo.value.kind is FailureKind.AUTHENTICATION
