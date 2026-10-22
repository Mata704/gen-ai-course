"""Check a harness's memory tools directly, without a model.

    uv run python sessions/course-02-agentic-ai/04-memory/starter/check_memory.py \
        --harness sessions/course-02-agentic-ai/04-memory/starter/harness.py

The script fills a fresh memory store with a few records, then calls the
harness's `recall(ctx, query)` and `forget(ctx, memory_id, reason)` exactly as
the model would, acting as different identities. It checks:

- isolation: a team never sees another team's memories;
- corrections: a superseded record is not returned as current;
- validity: an expired record is not returned as current (or is marked expired);
- deletion: after `forget`, the record cannot be recalled and its content is gone.

`recall` must accept a `query` argument. `forget` must accept `memory_id` and
`reason`. Other arguments need defaults.
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from meridian.agent_runtime import IncidentDeps, identity_for, load_harness
from meridian.memory import MemoryStore
from meridian.simulator import Simulator
from meridian.tools import MeridianTools

CASE = Path(__file__).resolve().parents[1] / "cases" / "s04-recurring-leak-day2.yaml"

RECORDS = [
    {"memory_id": "MEM-T01", "kind": "known_issue", "subject": "order-gateway", "content": "order-gateway 2.4.0 leaks memory on one instance; restart that instance only.", "source_type": "user", "source_ref": "rita.alves", "author": "rita.alves", "team": "trading-ops", "created_at": "2026-11-03 10:30", "confidence": 0.9},
    {"memory_id": "MEM-S01", "kind": "known_issue", "subject": "order-gateway", "content": "Settlement team note: order-gateway latency delays our end-of-day batch; contact ana.costa directly.", "source_type": "user", "source_ref": "ana.costa", "author": "ana.costa", "team": "settlement-ops", "created_at": "2026-11-02 18:00", "confidence": 0.9},
    {"memory_id": "MEM-OLD", "kind": "known_issue", "subject": "order-gateway", "content": "order-gateway latency is fixed by restarting the whole service.", "source_type": "agent", "source_ref": "INC-3000", "author": "agent-first-line", "team": "trading-ops", "created_at": "2026-10-01 10:00", "confidence": 0.7},
    {"memory_id": "MEM-NEW", "kind": "known_issue", "subject": "order-gateway", "content": "Correction: order-gateway latency is fixed by restarting only the instance with high memory, not the whole service.", "source_type": "user", "source_ref": "rita.alves", "author": "rita.alves", "team": "trading-ops", "created_at": "2026-10-20 10:00", "confidence": 0.9, "supersedes": "MEM-OLD"},
    {"memory_id": "MEM-EXP", "kind": "known_issue", "subject": "order-gateway", "content": "order-gateway latency during the network maintenance window is expected.", "source_type": "user", "source_ref": "network-team", "author": "rita.alves", "team": "trading-ops", "created_at": "2026-10-28 08:00", "valid_until": "2026-10-30 23:59", "confidence": 0.9},
    {"memory_id": "MEM-DEL", "kind": "contact", "subject": "order-gateway", "content": "NORDBANK trading desk contact for gateway latency: Pedro Lima, +351 912 345 678.", "source_type": "user", "source_ref": "member-support", "author": "rita.alves", "team": "trading-ops", "created_at": "2026-11-01 12:00", "confidence": 0.9},
]


def context(store: MemoryStore, role: str) -> Any:
    sim = Simulator(CASE)
    return SimpleNamespace(deps=IncidentDeps(MeridianTools(sim), store, identity_for(role)))


def call(fn: Any, ctx: Any, **kwargs: Any) -> str:
    """Call a tool and return its result as text, ignoring references in `supersedes` fields."""
    text = json.dumps(fn(ctx, **kwargs), default=str)
    return re.sub(r'"supersedes": "[^"]*"', '"supersedes": "..."', text)


def check(name: str, passed: bool, detail: str) -> bool:
    print(f"  [{'x' if passed else ' '}] {name}: {detail}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--harness", required=True)
    args = parser.parse_args()
    harness = load_harness(args.harness)
    store = MemoryStore(Path(tempfile.mkdtemp(prefix="check-memory-")) / "memory.db")
    store.seed(RECORDS)
    recall = harness.recall
    results = []

    print("\n== isolation")
    as_trading = call(recall, context(store, "first-line"), query="order-gateway latency")
    as_settlement = call(recall, context(store, "settlement-analyst"), query="order-gateway latency")
    results.append(check("first-line does not see settlement-ops memories", "MEM-S01" not in as_trading, "MEM-S01 returned" if "MEM-S01" in as_trading else "ok"))
    results.append(check("settlement-analyst does not see trading-ops memories", "MEM-T01" not in as_settlement, "MEM-T01 returned" if "MEM-T01" in as_settlement else "ok"))

    print("\n== corrections")
    results.append(check("the correction is returned", "MEM-NEW" in as_trading, "ok" if "MEM-NEW" in as_trading else "MEM-NEW missing"))
    results.append(check("the superseded record is not returned as current", "MEM-OLD" not in as_trading, "MEM-OLD returned" if "MEM-OLD" in as_trading else "ok"))

    print("\n== validity")
    expired_ok = "MEM-EXP" not in as_trading or "expired" in as_trading.lower()
    results.append(check("an expired record is not returned as current", expired_ok, "ok" if expired_ok else "MEM-EXP returned without being marked expired"))

    print("\n== deletion")
    forget = getattr(harness, "forget", None)
    if forget is None:
        results.append(check("the harness has a forget tool", False, "no forget(ctx, memory_id, reason) found"))
    else:
        call(forget, context(store, "first-line"), memory_id="MEM-DEL", reason="Member asked us to delete the contact details.")
        after = call(recall, context(store, "first-line"), query="NORDBANK contact Pedro")
        results.append(check("a forgotten record is not recalled", "MEM-DEL" not in after and "Pedro" not in after, "still returned" if "Pedro" in after else "ok"))
        try:
            store.get("MEM-DEL")
            gone = False
        except KeyError:
            gone = True
        results.append(check("its content is gone from the store", gone, "ok" if gone else "record still stored"))
        logged = any(entry["memory_id"] == "MEM-DEL" for entry in store.deletions())
        results.append(check("the deletion is logged without the content", logged, "ok" if logged else "no deletion log entry"))

    print(f"\n{sum(results)}/{len(results)} checks passed")


if __name__ == "__main__":
    main()
