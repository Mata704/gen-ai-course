"""Remote access demo: the tickets server over Streamable HTTP with bearer tokens.

Terminal 1 (server):
    uv run python -m meridian.mcp_servers.http_demo serve

Terminal 2 (client, once per token):
    uv run python -m meridian.mcp_servers.http_demo client --token none
    uv run python -m meridian.mcp_servers.http_demo client --token first-line
    uv run python -m meridian.mcp_servers.http_demo client --token incident-manager

Each token carries different scopes. The demo shows three different answers:
no token (the transport refuses the connection), a token without the scope
(the server refuses the call) and a token with the scope (the call succeeds).
Tokens are static and printed here on purpose: this is a classroom demo, not
an authorization server.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from fastmcp import Client
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from meridian.mcp_servers import tickets
from meridian.simulator import Simulator
from meridian.tools import MeridianTools

SCENARIO = "sessions/course-02-agentic-ai/03-mcp-integration/cases/s03-alert-and-ticket.yaml"
URL = "http://127.0.0.1:8765/mcp"
TOKENS = {
    "first-line": {"token": "demo-first-line", "scopes": ["tickets:read", "tickets:comment"]},
    "incident-manager": {"token": "demo-incident-manager", "scopes": ["tickets:read", "tickets:comment", "tickets:create", "tickets:transition"]},
}


def serve(port: int) -> None:
    verifier = StaticTokenVerifier(
        tokens={entry["token"]: {"client_id": name, "scopes": entry["scopes"]} for name, entry in TOKENS.items()},
    )
    server = tickets.build(MeridianTools(Simulator(SCENARIO)), auth=verifier)
    server.run(transport="http", host="127.0.0.1", port=port, show_banner=False)


async def client(token_name: str, url: str) -> None:
    token = TOKENS.get(token_name, {}).get("token")
    print(f"Connecting to {url} with token: {token_name}")
    try:
        async with Client(url, auth=token) as session:
            names = [tool.name for tool in await session.list_tools()]
            print(f"  list_tools: {len(names)} tools")
            for name, arguments in [("search_issues", {"text": "gateway"}), ("transition_issue", {"key": "MRX-2210", "status": "In Progress"})]:
                result = await session.call_tool(name, arguments, raise_on_error=False)
                text = result.content[0].text if result.content else ""
                print(f"  {name}: {json.dumps(json.loads(text) if text.startswith('{') else text)[:150]}")
    except Exception as error:  # noqa: BLE001 - show the refusal as the demo output
        print(f"  refused before any tool call ({type(error).__name__}). The server log shows 401 Unauthorized: no valid token.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["serve", "client"])
    parser.add_argument("--token", default="none", choices=["none", *TOKENS])
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.port)
    else:
        asyncio.run(client(args.token, URL.replace("8765", str(args.port))))


if __name__ == "__main__":
    main()
