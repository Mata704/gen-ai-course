"""Approval flow and active, bounded overrides for dataset-level rule thresholds."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from data_quality_agent.harness.policies import PolicyDenied, check_rule_threshold_change
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import PipelineRuleApproval, RuleThreshold
from data_quality_agent.simulator.models import PipelineDefinition, QualityRule


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RuleChangeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def request(
        self, *, incident_id: str, pipeline: PipelineDefinition, rule_id: str,
        attribute: RuleThreshold, proposed_value: int, reason: str, requested_by: str,
        identity_attested: bool,
    ) -> int:
        if not reason.strip() or not requested_by.strip():
            raise ValueError("Indica quem pede a alteração e o respetivo motivo.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para pedir a alteração.")
        if pipeline.pipeline_id != self._incident_pipeline(incident_id):
            raise PolicyDenied("The proposed rule does not belong to this incident's pipeline.")
        rule = self._rule(pipeline, rule_id)
        check_rule_threshold_change(rule=rule, attribute=attribute, value=proposed_value)
        current_value = getattr(rule, attribute)
        if current_value is None:
            raise PolicyDenied("The selected rule has no configured value for this threshold.")
        if proposed_value == current_value:
            raise PolicyDenied("The proposed threshold is already active.")
        try:
            with self.database.transaction() as connection:
                cursor = connection.execute(
                    "INSERT INTO pipeline_rule_approvals "
                    "(incident_id, pipeline_id, rule_id, attribute, previous_value, proposed_value, reason, "
                    "requested_by, requester_attested, status, requested_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?)",
                    (incident_id, pipeline.pipeline_id, rule_id, attribute, current_value, proposed_value,
                     reason.strip(), requested_by.strip(), _now()),
                )
        except sqlite3.IntegrityError as error:
            raise PolicyDenied("A pending request already exists for this rule threshold.") from error
        return int(cursor.lastrowid)

    def approve(
        self, approval_id: int, *, pipeline: PipelineDefinition, decided_by: str, identity_attested: bool,
    ) -> PipelineRuleApproval:
        if not decided_by.strip():
            raise ValueError("Indica quem aprova a alteração.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para aprovar a alteração.")
        with self.database.transaction() as connection:
            approval = connection.execute(
                "SELECT * FROM pipeline_rule_approvals WHERE approval_id = ?", (approval_id,),
            ).fetchone()
            if approval is None or approval["status"] != "pending":
                raise PolicyDenied("The rule-change request is missing or is no longer pending.")
            if approval["requested_by"].casefold() == decided_by.strip().casefold():
                raise PolicyDenied("A different person must approve the rule change.")
            if pipeline.pipeline_id != approval["pipeline_id"]:
                raise PolicyDenied("The pipeline changed; create a new rule-change request.")
            rule = self._rule(pipeline, approval["rule_id"])
            check_rule_threshold_change(
                rule=rule, attribute=approval["attribute"], value=approval["proposed_value"],
            )
            current_value = getattr(rule, approval["attribute"])
            if current_value != approval["previous_value"]:
                raise PolicyDenied("The rule changed since the request; create a new request.")
            now = _now()
            connection.execute(
                "INSERT INTO pipeline_rule_overrides "
                "(pipeline_id, rule_id, attribute, value, approval_id, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (pipeline_id, rule_id, attribute) DO UPDATE SET value = excluded.value, "
                "approval_id = excluded.approval_id, updated_at = excluded.updated_at",
                (approval["pipeline_id"], approval["rule_id"], approval["attribute"],
                 approval["proposed_value"], approval_id, now),
            )
            connection.execute(
                "UPDATE pipeline_rule_approvals SET status = 'executed', decided_by = ?, "
                "decider_attested = 1, finished_at = ? WHERE approval_id = ? AND status = 'pending'",
                (decided_by.strip(), now, approval_id),
            )
            row = connection.execute(
                "SELECT * FROM pipeline_rule_approvals WHERE approval_id = ?", (approval_id,),
            ).fetchone()
        return PipelineRuleApproval.model_validate(dict(row))

    def reject(self, approval_id: int, *, decided_by: str, identity_attested: bool) -> None:
        if not decided_by.strip():
            raise ValueError("Indica quem rejeita o pedido.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para rejeitar o pedido.")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT requested_by, status FROM pipeline_rule_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None or row["status"] != "pending":
                raise PolicyDenied("The rule-change request is missing or is no longer pending.")
            if row["requested_by"].casefold() == decided_by.strip().casefold():
                raise PolicyDenied("A different person must decide the rule change.")
            connection.execute(
                "UPDATE pipeline_rule_approvals SET status = 'rejected', decided_by = ?, "
                "decider_attested = 1, finished_at = ? WHERE approval_id = ? AND status = 'pending'",
                (decided_by.strip(), _now(), approval_id),
            )

    def list_for_incident(self, incident_id: str) -> list[PipelineRuleApproval]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM pipeline_rule_approvals WHERE incident_id = ? ORDER BY approval_id",
                (incident_id,),
            ).fetchall()
        return [PipelineRuleApproval.model_validate(dict(row)) for row in rows]

    def apply_overrides(self, pipeline: PipelineDefinition) -> PipelineDefinition:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT rule_id, attribute, value FROM pipeline_rule_overrides WHERE pipeline_id = ?",
                (pipeline.pipeline_id,),
            ).fetchall()
        overrides = {(row["rule_id"], row["attribute"]): row["value"] for row in rows}
        rules: list[QualityRule] = []
        for rule in pipeline.rules:
            changes = {
                attribute: value
                for (rule_id, attribute), value in overrides.items()
                if rule_id == rule.rule_id
            }
            if changes:
                for attribute, value in changes.items():
                    check_rule_threshold_change(rule=rule, attribute=attribute, value=value)
                rule = QualityRule.model_validate({**rule.model_dump(), **changes})
            rules.append(rule)
        known_rule_ids = {rule.rule_id for rule in rules}
        unknown = {rule_id for rule_id, _ in overrides if rule_id not in known_rule_ids}
        if unknown:
            raise RuntimeError(f"Approved rule overrides no longer match the pipeline: {sorted(unknown)}.")
        return pipeline.model_copy(update={"rules": rules})

    def _incident_pipeline(self, incident_id: str) -> str:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT r.pipeline_id FROM incident_workflows w "
                "JOIN pipeline_runs r ON r.run_id = w.incident_id WHERE w.incident_id = ?",
                (incident_id,),
            ).fetchone()
        if row is None:
            raise PolicyDenied("The incident does not exist.")
        return row["pipeline_id"]

    @staticmethod
    def _rule(pipeline: PipelineDefinition, rule_id: str) -> QualityRule:
        rule = next((candidate for candidate in pipeline.rules if candidate.rule_id == rule_id), None)
        if rule is None:
            raise PolicyDenied("The selected rule does not exist in the active pipeline.")
        return rule
