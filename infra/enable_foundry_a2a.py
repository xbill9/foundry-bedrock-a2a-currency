"""Enable incoming A2A on the Foundry agent and publish its agent card.

Foundry hosted agents do not serve A2A until the agent is PATCHed with an
agent card and an ``a2a`` protocol configuration. The portal cannot do this
yet, and the Python SDK cannot set the card, so this uses the REST API for
both in one call.

    export FOUNDRY_PROJECT_ENDPOINT="https://<account>.services.ai.azure.com/api/projects/<project>"
    export FOUNDRY_AGENT_NAME="currency-a2a-agent"
    python3 -m infra.enable_foundry_a2a

Authenticates with the ambient Azure credential chain (``az login`` locally).
The caller needs Foundry User or higher on the project. On success it prints
the A2A base URL to set as ``CURRENCY_FOUNDRY_A2A_ENDPOINT``.

Docs: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/enable-agent-to-agent-endpoint
"""

import json
import os
import sys

import httpx

API_VERSION = "v1"
SCOPE = "https://ai.azure.com/.default"

AGENT_CARD = {
    "description": (
        "Answers currency conversion questions with one structured decimal quote "
        "per target currency, sourced from live exchange rates over MCP."
    ),
    "version": "1.0",
    "skills": [
        {
            "id": "currency-conversion",
            "name": "Currency conversion",
            "description": (
                "Converts an amount between ISO 4217 currencies and returns the rate, "
                "converted amount, and observation time as JSON."
            ),
        }
    ],
}


def a2a_base_url(project_endpoint: str, agent_name: str) -> str:
    return f"{project_endpoint.rstrip('/')}/agents/{agent_name}/endpoint/protocols/a2a"


def agent_card_url(project_endpoint: str, agent_name: str) -> str:
    return f"{a2a_base_url(project_endpoint, agent_name)}/agentCard/v1.0"


def build_patch_body(card: dict | None = None) -> dict:
    """Agent card plus the protocol configuration, in one PATCH body.

    ``responses`` is repeated deliberately: the protocol configuration is
    replaced wholesale, and dropping it would remove the protocol that
    incoming A2A depends on.
    """
    return {
        "agent_card": card or AGENT_CARD,
        "agent_endpoint": {"protocol_configuration": {"responses": {}, "a2a": {}}},
    }


def get_token() -> str:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential().get_token(SCOPE).token


def main() -> int:
    project_endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    agent_name = os.environ.get("FOUNDRY_AGENT_NAME", "currency-a2a-agent")
    if not project_endpoint:
        print(__doc__, file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"}
    agent_url = f"{project_endpoint.rstrip('/')}/agents/{agent_name}?api-version={API_VERSION}"
    with httpx.Client(timeout=60) as client:
        response = client.patch(agent_url, headers=headers, json=build_patch_body())
        if response.is_error:
            print(f"PATCH {agent_url} failed: {response.status_code} {response.text}",
                  file=sys.stderr)
            return 1
        card_url = agent_card_url(project_endpoint, agent_name)
        card_response = client.get(card_url, headers=headers)
        if card_response.is_error:
            print(
                f"A2A was enabled but the card at {card_url} is not readable: "
                f"{card_response.status_code} {card_response.text}",
                file=sys.stderr,
            )
            return 1
        card = card_response.json()

    print(json.dumps(card, indent=2))
    print(
        "\nIncoming A2A is enabled. Point the coordinator at it with:\n"
        f'  export CURRENCY_FOUNDRY_A2A_ENDPOINT="{a2a_base_url(project_endpoint, agent_name)}"\n'
        "  export CURRENCY_A2A_PEER=foundry\n"
        "Callers also need the Foundry Agent Consumer role on this project.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
