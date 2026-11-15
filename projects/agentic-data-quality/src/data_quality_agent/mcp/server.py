"""MCP server of the Orders Platform (stdio): read-only access to an external data source.

The server stands for a system this project does not own, so it knows nothing about our agents:
it lists all of its tools. Which agent may call which tool, the description pinning and the audit
are enforced on our side, by the gateway that calls this server as an MCP client.

    uv run --locked data-quality-mcp
"""

from __future__ import annotations

import argparse
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.tools import Tool
from mcp.types import ToolAnnotations

from data_quality_agent.mcp.platform import PLATFORM_DATABASE, PLATFORM_TOOLS, PlatformTools

SERVER_NAME = "orders-platform"
INSTRUCTIONS = (
    "Read-only data published by the team that produces the orders data: data contracts, "
    "announced schema changes, source system status and incidents, and the customer master."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)


def build_server(database_path: str | Path = PLATFORM_DATABASE) -> FastMCP:
    tools = PlatformTools(database_path)
    server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, version="1.0.0")
    for name in PLATFORM_TOOLS:
        server.add_tool(Tool.from_function(getattr(tools, name), name=name, annotations=READ_ONLY))
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP server (stdio) of the read-only Orders Platform.")
    parser.add_argument(
        "--database", type=Path, default=PLATFORM_DATABASE,
        help="Platform SQLite file, opened read-only (defaults to the snapshot shipped with the package).",
    )
    args = parser.parse_args()
    build_server(args.database).run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
