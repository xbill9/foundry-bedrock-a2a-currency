#!/bin/sh
# Cloud Run entry point: colocated MCP rate server + A2A agent.
set -e
python3 mcp_server.py &
sleep 2
exec python3 -m uvicorn agent:a2a_app --host 0.0.0.0 --port "${PORT:-8080}"
