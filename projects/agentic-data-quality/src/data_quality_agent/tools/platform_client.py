"""MCP client for the Orders Platform, with tool pinning (course session 03).

An external server can change a tool's description or parameters at any time, and the description
is what the model reads. Every tool we accept was reviewed once and its fingerprint (name,
description and input schema) stored in `mcp_lock.json`. On connect, a tool that is new or whose
fingerprint changed is rejected until someone reviews it and updates the lock:

    uv run --locked data-quality-mcp-lock                 # show each tool and whether it is pinned
    uv run --locked data-quality-mcp-lock --update-lock   # accept the current tools after review
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import TracebackType
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

MCP_LOCK = Path(__file__).with_name("mcp_lock.json")


class RemoteToolError(RuntimeError):
    """The MCP server answered the call with an error."""


def default_transport(database: str | Path | None = None) -> StdioTransport:
    """Start the platform server as a child process over stdio, with the current interpreter."""
    args = ["-m", "data_quality_agent.mcp.server"]
    if database is not None:
        args += ["--database", str(database)]
    return StdioTransport(command=sys.executable, args=args)


def fingerprint(tool: Any) -> str:
    content = {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode("utf-8")).hexdigest()


def read_lock(path: Path = MCP_LOCK) -> dict[str, str]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


class PlatformClient:
    """Async context manager: connects, pins the tools against the lock, then forwards calls."""

    def __init__(self, transport: Any = None, *, lock_path: Path = MCP_LOCK) -> None:
        self._client = Client(transport if transport is not None else default_transport())
        self.lock_path = lock_path
        self.descriptions: dict[str, str] = {}
        self.rejected: dict[str, str] = {}
        self.listed: list[Any] = []

    @property
    def pinned(self) -> set[str]:
        return set(self.descriptions)

    async def __aenter__(self) -> PlatformClient:
        await self._client.__aenter__()
        self.listed = await self._client.list_tools()
        lock = read_lock(self.lock_path)
        for tool in self.listed:
            expected = lock.get(tool.name)
            if expected is None:
                self.rejected[tool.name] = "not reviewed yet (missing from the MCP lock)"
            elif expected != fingerprint(tool):
                self.rejected[tool.name] = "description or parameters changed since it was reviewed"
            else:
                self.descriptions[tool.name] = tool.description or ""
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None,
    ) -> None:
        await self._client.__aexit__(exc_type, exc, tb)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._client.call_tool(name, arguments, raise_on_error=False)
        if result.is_error:
            text = " ".join(getattr(block, "text", "") for block in result.content).strip()
            raise RemoteToolError(text or f"Tool '{name}' failed on the MCP server.")
        return result.structured_content or {}


async def update_lock(transport: Any = None, path: Path = MCP_LOCK) -> dict[str, str]:
    """Record the current tools of the server as reviewed. Run only after reading their descriptions."""
    async with Client(transport if transport is not None else default_transport()) as client:
        lock = {tool.name: fingerprint(tool) for tool in await client.list_tools()}
    path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return lock


def main() -> None:
    parser = argparse.ArgumentParser(description="Show or pin the tools of the Orders Platform MCP server.")
    parser.add_argument("--update-lock", action="store_true", help="Accept the current tools into the lock.")
    args = parser.parse_args()

    async def run() -> None:
        if args.update_lock:
            print(f"Pinned {len(await update_lock())} tools in {MCP_LOCK}")
            return
        async with PlatformClient() as platform:
            for tool in platform.listed:
                state = "pinned" if tool.name in platform.pinned else f"REJECTED: {platform.rejected[tool.name]}"
                print(f"{tool.name}: {state}\n  {tool.description}\n")

    asyncio.run(run())


if __name__ == "__main__":
    main()
