"""Invoke the Foundry-hosted master over the Responses protocol.

Usage:
    export FOUNDRY_RESPONSES_ENDPOINT="$(cd foundry_agent && azd env get-value \
AGENT_CURRENCY_COORDINATOR_RESPONSES_ENDPOINT)"
    python3 -m evaluations.invoke_hosted \
      "Convert 100 USD to EUR in verified mode."
"""

import os
import sys

import httpx


def extract_output_text(payload: dict) -> list[str]:
    """Return every non-empty Responses API output-text part."""
    texts: list[str] = []
    for item in payload.get("output", []):
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    return texts


def response_diagnostic(payload: dict) -> dict:
    """Return non-sensitive response metadata for an empty-output failure."""
    return {
        "status": payload.get("status"),
        "error": payload.get("error"),
        "incomplete_details": payload.get("incomplete_details"),
        "output_types": [
            item.get("type") for item in payload.get("output", []) if isinstance(item, dict)
        ],
    }


def main() -> int:
    from azure.identity import DefaultAzureCredential

    endpoint = os.environ.get("FOUNDRY_RESPONSES_ENDPOINT")
    if not endpoint or len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
    response = httpx.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        json={"input": sys.argv[1], "stream": False},
        timeout=240,
    )
    response.raise_for_status()
    payload = response.json()
    texts = extract_output_text(payload)
    if not texts:
        print(
            f"Hosted response contained no output text: {response_diagnostic(payload)}",
            file=sys.stderr,
        )
        return 1
    for output_text in texts:
        print(output_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
