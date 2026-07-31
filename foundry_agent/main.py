"""Microsoft Foundry hosted master for the currency benchmark.

The model only collects intent and calls the framework-independent benchmark
tool. Decimal arithmetic and quote comparison remain deterministic; the remote
A2A currency specialist runs on Bedrock AgentCore.
"""

import os

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.identity import DefaultAzureCredential

from coordinator.hosted_tool import run_currency_benchmark

INSTRUCTION = (
    "You are the master coordinator for a currency interoperability benchmark, "
    "not a general chatbot. For every conversion call run_currency_benchmark "
    "exactly once. Never calculate or verify arithmetic yourself. Preserve the "
    "tool's amounts, rates, timestamps, source labels, failures, and warnings "
    "exactly. Ask only for a missing amount, source currency, or target currency."
)


def build_agent() -> Agent:
    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=DefaultAzureCredential(),
    )
    return Agent(
        client=client,
        name="currency-coordinator",
        description="Coordinates the Foundry-to-Bedrock currency benchmark.",
        instructions=INSTRUCTION,
        tools=[tool(run_currency_benchmark)],
        default_options={"store": False},
    )


def main() -> None:
    ResponsesHostServer(build_agent()).run()


if __name__ == "__main__":
    main()
