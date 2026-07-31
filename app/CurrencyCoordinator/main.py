"""AgentCore Runtime entrypoint: remote Strands currency agent over A2A."""

import json
from decimal import Decimal

from bedrock_agentcore.runtime import serve_a2a
from strands import Agent, tool
from strands.multiagent.a2a.executor import StrandsA2AExecutor

from coordinator.mcp_stdio import McpStdioExchangeRateTool
from coordinator.models import ConversionRequest
from model.load import load_model

SYSTEM_PROMPT = (
    "You are the Bedrock remote currency specialist in a cross-framework "
    "benchmark. Always call convert_currency. Copy its JSON exactly and never "
    "perform or verify arithmetic yourself. Refuse non-currency requests."
)


@tool
async def convert_currency(
    amount: str, source_currency: str, target_currencies: list[str]
) -> str:
    """Return exact live currency quotes for the requested targets."""
    request = ConversionRequest(
        amount=Decimal(amount),
        source_currency=source_currency,
        target_currencies=target_currencies,
    )
    quotes = await McpStdioExchangeRateTool().convert(request)
    return json.dumps(
        [
            {
                "source_currency": quote.source_currency,
                "target_currency": quote.target_currency,
                "rate": str(quote.rate),
                "converted_amount": str(quote.converted_amount),
            }
            for quote in quotes
        ]
    )


agent = Agent(model=load_model(), system_prompt=SYSTEM_PROMPT, tools=[convert_currency])


if __name__ == "__main__":
    serve_a2a(StrandsA2AExecutor(agent))
