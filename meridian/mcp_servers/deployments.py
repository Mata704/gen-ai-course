"""Simulated deployment platform exposed as an MCP server.

Deployments and configuration changes are the simulator's changes. A rollback
goes through the same executor as every other action (audit log, idempotency
keys, approvals for critical components).
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from meridian.mcp_servers._base import ServerBuilder, settings_for
from meridian.tools import MeridianTools

DEFAULTS = {
    "version": "1.12.0",
    "publisher": "platform-team",
    "instructions": "Meridian deployment platform: services, deployments and configuration changes, pipelines and rollbacks.",
    "scopes": ["deployments:read", "deployments:rollback", "deployments:restart"],
}


def build(tools: MeridianTools, auth: Any = None) -> FastMCP:
    settings = settings_for(tools, "deployments", DEFAULTS)
    builder = ServerBuilder(tools, settings, auth)
    sim = tools.sim

    def _deployment(change: Any) -> dict[str, Any]:
        return {
            "deployment_id": change.change_id,
            "service": change.component,
            "kind": change.kind,
            "description": change.description,
            "deployed_at": sim.clock.timestamp(change.at),
            "version_before": change.version_before,
            "version_after": change.version_after,
            "state": "active" if change.active else f"rolled back at {sim.clock.timestamp(change.rolled_back_at)}",
        }

    def list_deployments(service: str | None = None, environment: str = "production", limit: int = 10) -> dict[str, Any]:
        changes = sorted(sim.state.changes, key=lambda change: change.at, reverse=True)
        items = [_deployment(change) for change in changes if service is None or change.component == service]
        return {"environment": environment, "total": len(items), "items": items[:limit]}

    def get_deployment(deployment_id: str) -> dict[str, Any]:
        return _deployment(sim.state.change(deployment_id))

    def get_deployment_diff(deployment_id: str) -> dict[str, Any]:
        change = sim.state.change(deployment_id)
        if change.kind == "deploy":
            diff = f"version {change.version_before} -> {change.version_after}"
        else:
            diff = change.description
        return {"deployment_id": deployment_id, "diff": diff}

    def list_services() -> dict[str, Any]:
        return {"items": [{"service": name, "version": component.version, "critical": component.critical} for name, component in sim.state.components.items()]}

    def get_service(service: str) -> dict[str, Any]:
        component = sim.state.component(service)
        return {"service": service, "version": component.version, "replicas": len(component.instances), "critical": component.critical}

    def list_environments() -> dict[str, Any]:
        return {"items": ["production", "staging", "dr"]}

    def get_pipeline_status(service: str) -> dict[str, Any]:
        sim.state.component(service)
        return {"service": service, "pipeline": "idle", "last_run": "succeeded"}

    def list_feature_flags(service: str) -> dict[str, Any]:
        sim.state.component(service)
        return {"service": service, "flags": []}

    def rollback_deployment(deployment_id: str, idempotency_key: str | None = None, confirmation_ref: str | None = None) -> dict[str, Any]:
        return sim.executor.execute("rollback_change", deployment_id, idempotency_key=idempotency_key, actor=tools.actor, confirmation_ref=confirmation_ref)

    def restart_workload(service: str, instance: str | None = None, idempotency_key: str | None = None, confirmation_ref: str | None = None) -> dict[str, Any]:
        if instance:
            return sim.executor.execute("restart_instance", instance, idempotency_key=idempotency_key, actor=tools.actor, confirmation_ref=confirmation_ref)
        return sim.executor.execute("restart_service", service, idempotency_key=idempotency_key, actor=tools.actor, confirmation_ref=confirmation_ref)

    def promote_release(service: str, version: str) -> dict[str, Any]:
        return {"service": service, "version": version, "status": "queued"}

    def pause_pipeline(service: str) -> dict[str, Any]:
        return {"service": service, "pipeline": "paused"}

    builder.add(
        list_deployments,
        "List deployments and configuration changes in an environment, most recent first. Each item has deployment_id, "
        "service, kind (deploy or config), description, time, versions and state (active or rolled back).",
        scope="deployments:read",
    )
    builder.add(get_deployment, "Get one deployment or configuration change by id (e.g. CHG-4310).", scope="deployments:read")
    builder.add(get_deployment_diff, "Get what a deployment changed.", scope="deployments:read")
    builder.add(list_services, "List services with their current version.", scope="deployments:read")
    builder.add(get_service, "Get a service: version, replicas and whether it is critical.", scope="deployments:read")
    builder.add(list_environments, "List environments.", scope="deployments:read")
    builder.add(get_pipeline_status, "Get the status of a service's delivery pipeline.", scope="deployments:read")
    builder.add(list_feature_flags, "List the feature flags of a service.", scope="deployments:read")
    builder.add(
        rollback_deployment,
        "Roll back a deployment or configuration change. Critical services need a confirmation_ref from an approval. "
        "Pass an idempotency_key so that a repeated request does not roll back twice.",
        scope="deployments:rollback",
    )
    builder.add(
        restart_workload,
        "Restart a service, or one instance of it when `instance` is given. Critical services need a confirmation_ref. "
        "Pass an idempotency_key so that a repeated request does not restart twice.",
        scope="deployments:restart",
    )
    builder.add(promote_release, "Promote a release to production.", scope="deployments:promote")
    builder.add(pause_pipeline, "Pause the delivery pipeline of a service.", scope="deployments:promote")
    return builder.server
