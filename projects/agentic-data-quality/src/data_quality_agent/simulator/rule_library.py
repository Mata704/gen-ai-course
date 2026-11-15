"""General quality rules shared by every pipeline, and how each pipeline adjusts them.

General rules check the dataset as a whole (schema, volume, freshness): field-level rules depend on
each pipeline's columns, so they are always the pipeline's own.
"""

from __future__ import annotations

from pathlib import Path

from data_quality_agent.simulator.models import (
    GeneralRuleLibrary,
    PipelineConfig,
    PipelineDefinition,
    RuleKind,
)

GENERAL_RULES_FILE = Path(__file__).parent / "rules" / "general.json"

DATASET_LEVEL_KINDS = {RuleKind.SCHEMA, RuleKind.MIN_ROWS, RuleKind.FRESHNESS}
# Which rule kind each adjustable threshold belongs to.
THRESHOLD_KINDS = {"minimum_count": RuleKind.MIN_ROWS, "maximum_delay_minutes": RuleKind.FRESHNESS}


def load_general_rules(path: str | Path = GENERAL_RULES_FILE) -> GeneralRuleLibrary:
    library = GeneralRuleLibrary.model_validate_json(Path(path).read_text(encoding="utf-8"))
    for rule in library.rules:
        if rule.kind not in DATASET_LEVEL_KINDS:
            raise ValueError(f"General rule '{rule.rule_id}' must check the whole dataset, not '{rule.kind.value}'.")
    return library


def resolve_pipeline(config: PipelineConfig, library: GeneralRuleLibrary) -> PipelineDefinition:
    """Effective rules of a pipeline: the general rules (adjusted or disabled) followed by its own."""
    general_ids = {rule.rule_id for rule in library.rules}
    unknown = sorted(set(config.general_rules) - general_ids)
    if unknown:
        raise ValueError(f"Pipeline '{config.pipeline_id}' adjusts unknown general rules: {', '.join(unknown)}.")
    clashes = sorted({rule.rule_id for rule in config.rules} & general_ids)
    if clashes:
        raise ValueError(
            f"Pipeline '{config.pipeline_id}' redefines general rules {', '.join(clashes)}; adjust them instead."
        )

    rules = []
    disabled: dict[str, str] = {}
    for rule in library.rules:
        adjustment = config.general_rules.get(rule.rule_id)
        if adjustment is None:
            rules.append(rule.model_copy(update={"origin": "general"}))
            continue
        if not adjustment.enabled:
            disabled[rule.rule_id] = adjustment.reason
            continue
        changes = adjustment.model_dump(exclude_none=True, exclude={"reason", "enabled"})
        if not changes:
            raise ValueError(f"Adjustment of general rule '{rule.rule_id}' changes nothing.")
        for threshold in changes.keys() & THRESHOLD_KINDS.keys():
            if THRESHOLD_KINDS[threshold] != rule.kind:
                raise ValueError(f"General rule '{rule.rule_id}' ({rule.kind.value}) has no '{threshold}'.")
        rules.append(rule.model_copy(update={
            **{name: getattr(adjustment, name) for name in changes},
            "origin": "general",
            "adjustment_reason": adjustment.reason,
        }))
    rules.extend(rule.model_copy(update={"origin": "pipeline"}) for rule in config.rules)

    return PipelineDefinition(
        **config.model_dump(exclude={"general_rules", "rules"}),
        rules=rules,
        disabled_general_rules=disabled,
    )
