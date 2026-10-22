"""Simulated monitoring platform (LogicMonitor-like) exposed as an MCP server.

Devices are the exchange components. Datasources map to the simulator metrics.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from meridian.mcp_servers._base import ServerBuilder, settings_for
from meridian.tools import MeridianTools

DEFAULTS = {
    "version": "2.9.4",
    "publisher": "observability-team",
    "instructions": "Meridian monitoring: devices, alerts, datapoints, logs, dashboards and scheduled downtime (SDT).",
    "scopes": ["monitoring:read", "monitoring:ack"],
}

SEVERITY = {"latency_high": "error", "error_rate_high": "critical", "queue_backlog": "warning", "memory_pressure": "error"}
DATAPOINT = {"latency_high": ("Latency", "latency_ms", 100), "error_rate_high": ("Errors", "error_rate", 0.05), "queue_backlog": ("Queue", "queue_depth", 500), "memory_pressure": ("Memory", "memory_pct", 90)}
DATASOURCES = {"Latency": ["latency_ms"], "Errors": ["error_rate"], "Queue": ["queue_depth"], "CPU": ["cpu_pct"], "Memory": ["memory_pct"], "Disk": ["disk_pct"]}
DASHBOARDS = [
    {"id": "DB-1", "name": "Trading overview", "widgets": 14},
    {"id": "DB-2", "name": "Order flow", "widgets": 9},
    {"id": "DB-3", "name": "Settlement batch", "widgets": 6},
    {"id": "DB-4", "name": "Infrastructure capacity", "widgets": 21},
]
COLLECTORS = [{"id": "COL-1", "name": "lisbon-dc-1", "status": "ok"}, {"id": "COL-2", "name": "lisbon-dc-2", "status": "ok"}]
RULES = [
    {"rule": "latency_high", "datapoint": "Latency", "threshold": "> 100 ms for 2 polls", "escalation_chain": "trading-ops"},
    {"rule": "error_rate_high", "datapoint": "Errors", "threshold": "> 5% for 2 polls", "escalation_chain": "trading-ops"},
    {"rule": "queue_backlog", "datapoint": "Queue", "threshold": "> 500 for 2 polls", "escalation_chain": "trading-ops"},
    {"rule": "memory_pressure", "datapoint": "Memory", "threshold": "> 90% for 2 polls", "escalation_chain": "infra"},
]


def build(tools: MeridianTools, auth: Any = None) -> FastMCP:
    settings = settings_for(tools, "monitoring", DEFAULTS)
    builder = ServerBuilder(tools, settings, auth)
    sim = tools.sim

    def _alert(alert: Any) -> dict[str, Any]:
        datasource, metric, threshold = DATAPOINT.get(alert.rule, ("Unknown", None, None))
        component = sim.state.component(alert.component)
        value = getattr(component, metric) if metric and metric != "memory_pct" else None
        if metric == "memory_pct" and alert.instance:
            value = round(sim.state.instance(alert.instance)[1].memory_pct, 1)
        return {
            "id": f"LMA{alert.alert_id.split('-')[1]}",
            "internal_id": alert.alert_id,
            "type": "dataSourceAlert",
            "severity": SEVERITY.get(alert.rule, "warning"),
            "device": alert.component,
            "instance": alert.instance,
            "datasource": datasource,
            "datapoint": alert.rule,
            "current_value": value,
            "threshold": threshold,
            "start_on": alert.opened_at,
            "cleared": alert.state != "open",
            "acked": alert.acked,
            "ack_comment": alert.ack_comment,
        }

    def _find(alert_id: str) -> Any:
        for alert in sim.alerts.alerts:
            if alert_id in (alert.alert_id, f"LMA{alert.alert_id.split('-')[1]}"):
                return alert
        raise KeyError(f"Unknown alert: {alert_id}")

    def list_alerts(severity: str | None = None, device: str | None = None, cleared: bool = False, size: int = 50) -> dict[str, Any]:
        alerts = [
            _alert(alert)
            for alert in sim.alerts.alerts
            if (alert.state != "open") == cleared and (device is None or alert.component == device) and (severity is None or SEVERITY.get(alert.rule) == severity)
        ]
        return {"total": len(alerts), "items": alerts[:size]}

    def get_alert(alert_id: str) -> dict[str, Any]:
        return _alert(_find(alert_id))

    def ack_alert(alert_id: str, comment: str) -> dict[str, Any]:
        alert = _find(alert_id)
        alert.acked, alert.ack_comment = True, comment
        return {"id": alert_id, "acked": True}

    def get_device(device: str) -> dict[str, Any]:
        component = sim.state.component(device)
        return {
            "device": device,
            "display_name": device,
            "critical": component.critical,
            "version": component.version,
            "instances": [instance.instance_id for instance in component.instances],
            "depends_on": [link.target for link in sim.state.links if link.source == device],
            "collector": "COL-1",
        }

    def list_devices(group: str | None = None) -> dict[str, Any]:
        return {"items": [{"device": name, "critical": component.critical} for name, component in sim.state.components.items()]}

    def get_device_datapoints(device: str, datasource: str = "all", minutes: int = 5) -> dict[str, Any]:
        sim.state.component(device)
        keys = [key for values in DATASOURCES.values() for key in values] if datasource == "all" else DATASOURCES.get(datasource)
        if keys is None:
            raise KeyError(f"Unknown datasource {datasource!r}; use one of {', '.join(DATASOURCES)} or 'all'")
        readings = sim.metrics.series(device, max(1, min(minutes, 30)))
        return {
            "device": device,
            "datasource": datasource,
            "poll_interval": "1 minute",
            "values": [{"time": reading["time"], **{key: reading[key] for key in keys}} for reading in readings],
            "source_ref": f"metrics/{device}/{readings[-1]['tick']}",
        }

    def get_instance_datapoints(device: str, instance: str, minutes: int = 5) -> dict[str, Any]:
        readings = sim.metrics.series(device, max(1, min(minutes, 30)))
        if instance not in readings[-1]["instances"]:
            raise KeyError(f"Unknown instance {instance} on {device}")
        return {"device": device, "instance": instance, "values": [{"time": reading["time"], **reading["instances"][instance]} for reading in readings]}

    def search_logs(device: str | None = None, query: str | None = None, level: str | None = None, size: int = 100) -> dict[str, Any]:
        lines = [
            line
            for line in sim.logs.lines
            if (device is None or line["component"] == device)
            and (query is None or query.lower() in line["message"].lower())
            and (level is None or line["level"] == level.upper())
        ]
        return {"total": len(lines), "items": lines[-size:]}

    def list_dashboards() -> dict[str, Any]:
        return {"items": DASHBOARDS}

    def get_dashboard(dashboard_id: str) -> dict[str, Any]:
        for dashboard in DASHBOARDS:
            if dashboard["id"] == dashboard_id:
                return {**dashboard, "devices": list(sim.state.components)}
        raise KeyError(f"Unknown dashboard: {dashboard_id}")

    def list_reports() -> dict[str, Any]:
        return {"items": [{"id": "REP-1", "name": "Weekly availability"}, {"id": "REP-2", "name": "Alert volume by team"}]}

    def list_collectors() -> dict[str, Any]:
        return {"items": COLLECTORS}

    def get_collector_status(collector_id: str) -> dict[str, Any]:
        for collector in COLLECTORS:
            if collector["id"] == collector_id:
                return {**collector, "last_poll": sim.clock.label(sim.state.tick)}
        raise KeyError(f"Unknown collector: {collector_id}")

    def list_alert_rules() -> dict[str, Any]:
        return {"items": RULES}

    def list_escalation_chains() -> dict[str, Any]:
        return {"items": [{"name": "trading-ops", "stages": ["agent-first-line", "rita.alves", "joao.matos"]}, {"name": "infra", "stages": ["infra-on-call"]}]}

    def list_sdts(device: str | None = None) -> dict[str, Any]:
        items = [{"device": name, "until": sim.clock.label(until)} for name, until in sim.alerts.suppressed_until.items() if device in (None, name)]
        return {"items": items}

    def create_sdt(device: str, minutes: int, comment: str) -> dict[str, Any]:
        sim.state.component(device)
        sim.alerts.suppressed_until[device] = sim.state.tick + minutes
        return {"device": device, "until": sim.clock.label(sim.state.tick + minutes), "comment": comment}

    def get_audit_log(size: int = 20) -> dict[str, Any]:
        entries = [{"time": record.time, "user": record.actor, "action": f"{record.action} {record.target}", "outcome": record.outcome} for record in sim.executor.audit]
        return {"items": entries[-size:]}

    builder.add(
        list_alerts,
        "List alerts. severity: warning, error or critical. cleared=false returns active alerts. Each item has id, severity, "
        "device, datasource, datapoint, current_value, threshold, start time and ack state. Large estates can return hundreds "
        "of alerts; use device and severity filters.",
        scope="monitoring:read",
    )
    builder.add(get_alert, "Get one alert by id (LMA... or ALR-...), with its current value and threshold.", scope="monitoring:read")
    builder.add(ack_alert, "Acknowledge an alert with a comment. Acknowledging stops escalation for this alert but does not clear it.", scope="monitoring:ack")
    builder.add(get_device, "Get a monitored device (an exchange component): version, instances, dependencies and collector.", scope="monitoring:read")
    builder.add(list_devices, "List monitored devices, optionally by group.", scope="monitoring:read")
    builder.add(
        get_device_datapoints,
        "Get recent datapoints for a device, one value per minute. datasource: Latency, Errors, Queue, CPU, Memory, Disk or "
        "'all'. minutes: 1 to 30. Values are the worst instance for CPU and Memory.",
        scope="monitoring:read",
    )
    builder.add(get_instance_datapoints, "Get recent datapoints for one instance of a device (status, memory, CPU, latency).", scope="monitoring:read")
    builder.add(search_logs, "Search collected logs (LM Logs). Filters: device, query (substring), level. Returns the most recent matches.", scope="monitoring:read")
    builder.add(list_dashboards, "List dashboards.", scope="monitoring:read")
    builder.add(get_dashboard, "Get a dashboard definition.", scope="monitoring:read")
    builder.add(list_reports, "List scheduled reports.", scope="monitoring:read")
    builder.add(list_collectors, "List collectors and their status.", scope="monitoring:read")
    builder.add(get_collector_status, "Get the status of one collector, including the time of its last poll.", scope="monitoring:read")
    builder.add(list_alert_rules, "List alert rules: datapoint, threshold and escalation chain.", scope="monitoring:read")
    builder.add(list_escalation_chains, "List escalation chains and their stages.", scope="monitoring:read")
    builder.add(list_sdts, "List scheduled downtime (SDT) windows. Devices in SDT do not open new alerts.", scope="monitoring:read")
    builder.add(
        create_sdt,
        "Put a device in scheduled downtime (SDT) for a number of minutes: no new alerts are opened for it during that time. "
        "Use for planned maintenance.",
        scope="monitoring:sdt",
    )
    builder.add(get_audit_log, "Get recent operational actions recorded by the platform (who, what, outcome).", scope="monitoring:read")
    return builder.server
