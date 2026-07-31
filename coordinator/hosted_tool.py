"""Function tool exposed to the hosted coordinator.

Defaults to deterministic fixture adapters so it runs without credentials.
In the production topology the Foundry coordinator sets
``CURRENCY_A2A_PEER=bedrock`` and ``CURRENCY_BEDROCK_A2A_ENDPOINT``.
"""

import json
import os
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from coordinator.local_adapters import DeterministicCurrencyAdapter
from coordinator.models import BenchmarkMode, ConversionRequest
from coordinator.providers import StaticRateProvider
from coordinator.service import CurrencyCoordinator


async def run_currency_benchmark(
    amount: str,
    source_currency: str,
    target_currencies: list[str],
    mode: str = "verified",
) -> str:
    """Run one currency interoperability benchmark mode.

    Args:
        amount: Positive decimal monetary amount, passed as a string.
        source_currency: Three-letter source currency code.
        target_currencies: One or more three-letter target currency codes.
        mode: mcp_only, a2a_only, or verified.

    Returns:
        A structured JSON result whose source fields identify live versus
        deterministic-fixture adapters. Treat only sources containing
        "deterministic-fixture" or "hosted-local" as non-live.
    """
    try:
        request = ConversionRequest(
            amount=Decimal(amount),
            source_currency=source_currency,
            target_currencies=target_currencies,
        )
        benchmark_mode = BenchmarkMode(mode)
    except (InvalidOperation, ValidationError, ValueError) as exc:
        return json.dumps({"error": "invalid_request", "detail": str(exc)})

    provider = StaticRateProvider()
    if os.getenv("CURRENCY_RATE_TRANSPORT") == "mcp-stdio":
        from coordinator.mcp_stdio import McpStdioExchangeRateTool

        rate_tool = McpStdioExchangeRateTool()
    else:
        rate_tool = DeterministicCurrencyAdapter(provider, source="hosted-local-mcp")
    timeout_seconds = float(os.getenv("CURRENCY_TIMEOUT_SECONDS", "10"))
    from coordinator.a2a_remote import build_remote_agent

    try:
        remote_agent = build_remote_agent(
            peer=os.getenv("CURRENCY_A2A_PEER"), timeout_s=timeout_seconds
        )
    except ValueError as exc:
        return json.dumps({"error": "invalid_configuration", "detail": str(exc)})
    if remote_agent is None:
        remote_agent = DeterministicCurrencyAdapter(provider, source="hosted-local-a2a")
    coordinator = CurrencyCoordinator(
        rate_tool,
        remote_agent,
        timeout_seconds=timeout_seconds,
    )
    result = await coordinator.run(request, benchmark_mode)
    return result.model_dump_json()
