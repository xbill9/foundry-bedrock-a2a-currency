import json

import pytest

from coordinator.hosted_tool import run_currency_benchmark


def test_hosted_tool_description_does_not_label_all_results_as_fixtures() -> None:
    description = run_currency_benchmark.__doc__ or ""

    assert "using deterministic local fixture rates" not in description
    assert "source fields identify live versus" in description


@pytest.mark.asyncio
async def test_hosted_tool_returns_structured_verified_result() -> None:
    payload = json.loads(
        await run_currency_benchmark("100", "usd", ["cad", "eur"], "verified")
    )

    assert payload["mode"] == "verified"
    assert len(payload["results"]) == 2
    assert payload["results"][0]["agreed"] is True


@pytest.mark.asyncio
async def test_hosted_tool_returns_structured_validation_error() -> None:
    payload = json.loads(await run_currency_benchmark("-1", "USD", ["CAD"]))

    assert payload["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_hosted_tool_rejects_an_unknown_a2a_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURRENCY_A2A_PEER", "openai")

    payload = json.loads(await run_currency_benchmark("100", "USD", ["EUR"], "a2a_only"))

    # A typo in the runtime configuration must be a legible error, not a
    # silent fall-through to fixture rates labeled as a live remote agent.
    assert payload["error"] == "invalid_configuration"


@pytest.mark.asyncio
async def test_hosted_tool_falls_back_to_fixtures_without_an_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CURRENCY_A2A_PEER", "foundry")
    monkeypatch.delenv("CURRENCY_FOUNDRY_A2A_ENDPOINT", raising=False)

    payload = json.loads(await run_currency_benchmark("100", "USD", ["EUR"], "a2a_only"))

    assert payload["results"][0]["primary"]["source"] == "hosted-local-a2a"
