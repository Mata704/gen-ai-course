"""Signals derived from the simulator state: metrics, logs, alerts and tickets.

Agents never read the state directly. They only see these signals, through the
tools in `meridian.tools`.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from meridian.clock import SimClock
from meridian.model import DATA_DIR, ExchangeState

LOG_TEMPLATES_FILE = DATA_DIR / "log_templates.yaml"

LATENCY_ALERT_MS = 100.0
ERROR_ALERT_RATE = 0.05
MEMORY_ALERT_PCT = 90.0
QUEUE_ALERT_DEPTH = 500.0
OPEN_AFTER_TICKS = 2
RESOLVE_AFTER_TICKS = 3

MEMBERS = ["NORDBANK", "ATLAS-SEC", "PRAIA-CAP", "VALE-INV", "ORION-BRK"]
SYMBOLS = ["MRX-ALFA", "MRX-BETA", "MRX-GAMA", "MRX-DELT"]


def _fill(template: str, rng: random.Random, **values: Any) -> str:
    defaults = {
        "member": rng.choice(MEMBERS),
        "order_id": f"O{rng.randint(100000, 999999)}",
        "side": rng.choice(["buy", "sell"]),
        "active": rng.randint(5, 40),
        "idle": rng.randint(0, 20),
        "symbol": rng.choice(SYMBOLS),
        "depth": rng.randint(3, 50),
        "qty": rng.randint(1, 500),
        "seq": rng.randint(10000, 99999),
        "client": f"10.4.{rng.randint(1, 9)}.{rng.randint(10, 250)}",
        "attempt": rng.randint(1, 3),
        "took": rng.randint(80, 900),
        "reason": "internal error",
    }
    defaults.update(values)
    return template.format(**defaults)


@dataclass
class MetricStore:
    history: list[dict[str, Any]] = field(default_factory=list)

    def record(self, state: ExchangeState, clock: SimClock) -> None:
        snapshot: dict[str, Any] = {"tick": state.tick, "time": clock.label(state.tick), "components": {}}
        for name, component in state.components.items():
            snapshot["components"][name] = {
                "latency_ms": component.latency_ms,
                "error_rate": component.error_rate,
                "queue_depth": component.queue_depth,
                "cpu_pct": round(max(instance.cpu_pct for instance in component.instances), 1),
                "memory_pct": round(max(instance.memory_pct for instance in component.instances), 1),
                "disk_pct": round(component.disk_pct, 1),
                "version": component.version,
                "instances": {
                    instance.instance_id: {
                        "status": instance.status,
                        "memory_pct": round(instance.memory_pct, 1),
                        "cpu_pct": round(instance.cpu_pct, 1),
                        "latency_ms": round(instance.latency_ms, 1),
                    }
                    for instance in component.instances
                },
            }
        self.history.append(snapshot)

    def series(self, component: str, last_ticks: int) -> list[dict[str, Any]]:
        readings = []
        for snapshot in self.history[-last_ticks:]:
            values = snapshot["components"][component]
            readings.append({"tick": snapshot["tick"], "time": snapshot["time"], **values})
        return readings


@dataclass
class LogStore:
    rng: random.Random
    background_per_tick: int = 3
    lines: list[dict[str, Any]] = field(default_factory=list)
    templates: dict[str, Any] = field(default_factory=lambda: yaml.safe_load(LOG_TEMPLATES_FILE.read_text(encoding="utf-8")))

    def add(self, state: ExchangeState, clock: SimClock, component: str, level: str, message: str, instance: str | None = None) -> None:
        seq = len(self.lines) + 1
        self.lines.append(
            {
                "seq": seq,
                "tick": state.tick,
                "time": clock.label(state.tick),
                "component": component,
                "instance": instance or f"{component}-1",
                "level": level,
                "message": message,
                "ref": f"logs/{component}/{seq}",
            }
        )

    def _template(self, key: str, **values: Any) -> str:
        return _fill(self.rng.choice(self.templates[key]), self.rng, **values)

    def generate(self, state: ExchangeState, clock: SimClock, reasons: dict[str, str]) -> None:
        names = list(state.components)
        for _ in range(self.background_per_tick):
            name = self.rng.choice(names)
            template = self.rng.choice(self.templates["background"][name])
            message = _fill(template, self.rng)
            component = state.components[name]
            instance = self.rng.choice(component.instances).instance_id
            self.add(state, clock, name, message.split()[0], message, instance)

        for event in [event for event in state.events if event["tick"] == state.tick]:
            component = state.components[event["component"]]
            if event["type"] == "instance_crash":
                self.add(state, clock, component.name, "ERROR", self._template("memory_crash"), event["instance"])
            elif event["type"] == "instance_restart":
                self.add(state, clock, component.name, "INFO", self._template("restart", version=component.version), event["instance"])
            elif event["type"] == "instance_ready":
                self.add(state, clock, component.name, "INFO", self._template("ready"), event["instance"])

        for name, component in state.components.items():
            for dependency in component.depends_on:
                link = state.link(name, dependency)
                if link.state == "down":
                    for _ in range(2):
                        self.add(state, clock, name, "ERROR", self._template("dependency_down", target=dependency))
                elif link.state == "degraded":
                    self.add(state, clock, name, "WARN", self._template("dependency_degraded", target=dependency))
            for instance in component.running_instances():
                if instance.memory_pct > MEMORY_ALERT_PCT:
                    self.add(state, clock, name, "WARN", self._template("memory_pressure", memory=round(instance.memory_pct)), instance.instance_id)
                if instance.cpu_pct > 90:
                    self.add(state, clock, name, "WARN", self._template("cpu_pressure", cpu=round(instance.cpu_pct)), instance.instance_id)
            if name in reasons and component.error_rate > ERROR_ALERT_RATE:
                self.add(state, clock, name, "ERROR", self._template("error_rate", reason=reasons[name]))
            if component.queue_depth > 300 and state.tick % 3 == 0:
                self.add(state, clock, name, "WARN", self._template("queue_backlog", queue=round(component.queue_depth)))


@dataclass
class Alert:
    alert_id: str
    rule: str
    component: str
    opened_tick: int
    opened_at: str
    instance: str | None = None
    state: str = "open"
    resolved_tick: int | None = None
    auto_resolve: bool = True
    notification: str = "delivered"

    def public(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule": self.rule,
            "component": self.component,
            "instance": self.instance,
            "state": self.state,
            "opened_at": self.opened_at,
            "opened_tick": self.opened_tick,
            "resolved_tick": self.resolved_tick,
            "source": "monitoring",
            "notification": self.notification,
        }


@dataclass
class AlertStore:
    next_number: int = 1000
    alerts: list[Alert] = field(default_factory=list)
    _above: dict[tuple[str, str, str | None], int] = field(default_factory=dict)
    _below: dict[tuple[str, str, str | None], int] = field(default_factory=dict)

    def new_id(self) -> str:
        self.next_number += 1
        return f"ALR-{self.next_number}"

    def open_alert(self, rule: str, component: str, tick: int, clock: SimClock, instance: str | None = None, auto_resolve: bool = True) -> Alert:
        alert = Alert(self.new_id(), rule, component, tick, clock.label(tick), instance=instance, auto_resolve=auto_resolve)
        self.alerts.append(alert)
        return alert

    def find_open(self, rule: str, component: str, instance: str | None = None) -> Alert | None:
        for alert in self.alerts:
            if alert.state == "open" and alert.rule == rule and alert.component == component and alert.instance == instance and alert.auto_resolve:
                return alert
        return None

    def _check(self, key: tuple[str, str, str | None], firing: bool, tick: int, clock: SimClock) -> None:
        rule, component, instance = key
        if firing:
            self._above[key] = self._above.get(key, 0) + 1
            self._below[key] = 0
            if self._above[key] >= OPEN_AFTER_TICKS and self.find_open(rule, component, instance) is None:
                self.open_alert(rule, component, tick, clock, instance)
        else:
            self._above[key] = 0
            self._below[key] = self._below.get(key, 0) + 1
            alert = self.find_open(rule, component, instance)
            if alert is not None and self._below[key] >= RESOLVE_AFTER_TICKS:
                alert.state = "resolved"
                alert.resolved_tick = tick

    def evaluate(self, state: ExchangeState, clock: SimClock) -> None:
        for name, component in state.components.items():
            self._check(("latency_high", name, None), component.latency_ms > LATENCY_ALERT_MS, state.tick, clock)
            self._check(("error_rate_high", name, None), component.error_rate > ERROR_ALERT_RATE, state.tick, clock)
            self._check(("queue_backlog", name, None), component.queue_depth > QUEUE_ALERT_DEPTH, state.tick, clock)
            for instance in component.instances:
                self._check(
                    ("memory_pressure", name, instance.instance_id),
                    instance.status == "running" and instance.memory_pct > MEMORY_ALERT_PCT,
                    state.tick,
                    clock,
                )


@dataclass
class TicketStore:
    tickets: list[dict[str, Any]] = field(default_factory=list)

    def add(self, ticket: dict[str, Any]) -> None:
        self.tickets.append(ticket)
