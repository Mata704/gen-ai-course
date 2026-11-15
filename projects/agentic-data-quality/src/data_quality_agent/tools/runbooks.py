"""Runbooks are the skills of the agents: short procedures loaded only when they apply."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RUNBOOKS_DIR = Path(__file__).parents[1] / "runbooks"


@dataclass(frozen=True)
class Runbook:
    runbook_id: str
    title: str
    version: int
    applies_to: frozenset[str]
    body: str

    @property
    def ref(self) -> str:
        return f"runbook:{self.runbook_id}@v{self.version}"


def _parse(path: Path) -> Runbook:
    text = path.read_text(encoding="utf-8")
    _, header, body = text.split("---", 2)
    fields = dict(line.split(":", 1) for line in header.strip().splitlines())
    fields = {key.strip(): value.strip() for key, value in fields.items()}
    return Runbook(
        runbook_id=fields["id"],
        title=fields["title"],
        version=int(fields["version"]),
        applies_to=frozenset(item.strip() for item in fields["applies_to"].split(",")),
        body=body.strip(),
    )


class RunbookLibrary:
    def __init__(self, directory: Path = RUNBOOKS_DIR) -> None:
        self.runbooks = [_parse(path) for path in sorted(directory.glob("*.md"))]

    def for_rule_kind(self, kind: str) -> Runbook | None:
        return self._find(f"rule:{kind}")

    def for_incident_kind(self, kind: str) -> Runbook | None:
        return self._find(f"incident:{kind}")

    def _find(self, key: str) -> Runbook | None:
        return next((runbook for runbook in self.runbooks if key in runbook.applies_to), None)
