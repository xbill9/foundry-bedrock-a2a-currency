import tomllib
from pathlib import Path

import yaml


def test_agentcore_requirements_include_async_entra_transport() -> None:
    """The hosted Foundry token provider needs azure-core's aiohttp transport."""
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    )

    assert any(
        line.startswith("aiohttp==")
        for line in requirements.splitlines()
        if line and not line.startswith("#")
    )

    app_manifest = Path(__file__).parents[1] / "app" / "CurrencyCoordinator" / "pyproject.toml"
    app = tomllib.loads(app_manifest.read_text(encoding="utf-8"))
    dependencies = app["project"]["dependencies"]

    assert any(dependency.startswith("aiohttp ") for dependency in dependencies)


def test_foundry_hosted_agent_has_a_concrete_model_name() -> None:
    manifest_path = Path(__file__).parents[1] / "foundry_agent" / "azure.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    service = manifest["services"]["currency-coordinator"]
    environment = service["environmentVariables"]
    values = {item["name"]: item["value"] for item in environment}

    assert values["AZURE_AI_MODEL_DEPLOYMENT_NAME"] == "gpt-5-mini"
    assert values["CURRENCY_A2A_PEER"] == "bedrock"


def test_agentcore_entrypoint_is_the_remote_a2a_agent() -> None:
    entrypoint = (
        Path(__file__).parents[1] / "app" / "CurrencyCoordinator" / "main.py"
    ).read_text(encoding="utf-8")

    assert "serve_a2a(StrandsA2AExecutor(agent))" in entrypoint
    assert "remote currency specialist" in entrypoint


def test_agentcore_a2a_server_uses_the_sdk_version_required_by_runtime() -> None:
    """AgentCore's A2A extra and a2a-sdk 1.x cannot share one bundle."""
    manifest_path = (
        Path(__file__).parents[1] / "app" / "CurrencyCoordinator" / "pyproject.toml"
    )
    dependencies = tomllib.loads(manifest_path.read_text(encoding="utf-8"))["project"][
        "dependencies"
    ]

    assert "bedrock-agentcore[a2a] == 1.19.0" in dependencies
    assert "a2a-sdk[all] == 0.3.26" in dependencies


def test_adk_image_uses_system_python_and_an_explicit_package_layout() -> None:
    root = Path(__file__).parents[1]
    dockerfile = (root / "adk_agent" / "Dockerfile").read_text(encoding="utf-8")
    start = (root / "adk_agent" / "start.sh").read_text(encoding="utf-8")
    manifest = tomllib.loads(
        (root / "adk_agent" / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert "pip3 install --no-cache-dir ." in dockerfile
    assert "python3 mcp_server.py" in start
    assert "python3 -m uvicorn" in start
    assert manifest["tool"]["setuptools"]["py-modules"] == ["agent", "mcp_server"]
