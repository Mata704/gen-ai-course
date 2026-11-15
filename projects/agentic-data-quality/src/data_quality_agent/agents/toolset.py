"""Expose approved tool metadata while keeping execution behind the gateway."""

from collections.abc import Callable
from typing import Any

from pydantic_ai import Tool

from data_quality_agent.tools import ToolGateway, tools_for


def evidence_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ("ref", "tool_ref") and isinstance(item, str):
                refs.add(item)
            else:
                refs.update(evidence_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(evidence_refs(item))
    return refs


def build_tools(
    gateway: ToolGateway,
    observed: set[str],
    used: set[str],
    on_tool: Callable[[str], None],
) -> list[Tool[None]]:
    platform = gateway.platform
    remote = {tool.name: tool for tool in platform.listed} if platform else {}
    selected: list[Tool[None]] = []

    def forward(name: str) -> Callable[..., Any]:
        async def call(**arguments: Any) -> dict[str, Any]:
            result = await gateway.call(name, arguments)
            if "error" not in result and result.get("status") != "blocked":
                observed.update(evidence_refs(result))
                used.add(name)
            on_tool(f"{name}: {result.get('error', result.get('reason', result.get('tool_ref', 'ok')))}")
            return result

        return call

    for spec in tools_for(gateway.session.agent):
        if spec.source == "local":
            local = Tool(getattr(gateway.tools, spec.name), takes_ctx=False)
            description, schema = local.description, local.function_schema.json_schema
        else:
            if platform is None or spec.name not in platform.pinned:
                continue
            description = platform.descriptions[spec.name]
            schema = remote[spec.name].input_schema
        selected.append(Tool.from_schema(
            forward(spec.name), name=spec.name, description=description, json_schema=schema,
        ))
    return selected
