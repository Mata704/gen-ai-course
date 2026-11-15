"""Human approval requests for classifying failed rows; authorization is rechecked on decision."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Literal

from data_quality_agent.harness.policies import PolicyDenied, check_failed_record_disposition
from data_quality_agent.persistence.database import Database
from data_quality_agent.persistence.models import FailedRecordApproval

Disposition = Literal["released", "discarded"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def request(
        self, *, source_run_id: str, position: int, target_status: Disposition,
        reason: str, requested_by: str, identity_attested: bool,
    ) -> int:
        if not reason.strip() or not requested_by.strip():
            raise ValueError("Indica quem pede a decisão e o respetivo motivo.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para criar o pedido.")
        try:
            with self.database.transaction() as connection:
                record = connection.execute(
                    "SELECT status FROM failed_records WHERE source_run_id = ? AND position = ?",
                    (source_run_id, position),
                ).fetchone()
                if record is None:
                    raise PolicyDenied("The failed record does not exist.")
                check_failed_record_disposition(
                    current_status=record["status"], target_status=target_status,
                )
                cursor = connection.execute(
                    "INSERT INTO failed_record_approvals "
                    "(source_run_id, position, target_status, reason, requested_by, requester_attested, "
                    "status, requested_at) VALUES (?, ?, ?, ?, ?, 1, 'pending', ?)",
                    (source_run_id, position, target_status, reason.strip(), requested_by.strip(), _now()),
                )
        except sqlite3.IntegrityError as error:
            raise PolicyDenied("A pending approval already exists for this failed record.") from error
        return int(cursor.lastrowid)

    def approve(
        self, approval_id: int, *, decided_by: str, identity_attested: bool,
    ) -> FailedRecordApproval:
        if not decided_by.strip():
            raise ValueError("Indica quem aprova a decisão.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para aprovar o pedido.")
        with self.database.transaction() as connection:
            approval = connection.execute(
                "SELECT * FROM failed_record_approvals WHERE approval_id = ?", (approval_id,),
            ).fetchone()
            if approval is None or approval["status"] != "pending":
                raise PolicyDenied("The approval request is missing or is no longer pending.")
            if approval["requested_by"].casefold() == decided_by.strip().casefold():
                raise PolicyDenied("A different person must approve the request.")
            record = connection.execute(
                "SELECT status FROM failed_records WHERE source_run_id = ? AND position = ?",
                (approval["source_run_id"], approval["position"]),
            ).fetchone()
            if record is None:
                raise PolicyDenied("The failed record no longer exists.")
            check_failed_record_disposition(
                current_status=record["status"], target_status=approval["target_status"],
            )
            now = _now()
            changed = connection.execute(
                "UPDATE failed_records SET status = ? WHERE source_run_id = ? AND position = ? AND status = 'held'",
                (approval["target_status"], approval["source_run_id"], approval["position"]),
            )
            if changed.rowcount != 1:
                raise PolicyDenied("The failed record changed while the approval was being processed.")
            connection.execute(
                "UPDATE failed_record_approvals SET status = 'executed', decided_by = ?, decider_attested = 1, "
                "finished_at = ? "
                "WHERE approval_id = ? AND status = 'pending'",
                (decided_by.strip(), now, approval_id),
            )
            row = connection.execute(
                "SELECT * FROM failed_record_approvals WHERE approval_id = ?", (approval_id,),
            ).fetchone()
        return FailedRecordApproval.model_validate(dict(row))

    def reject(self, approval_id: int, *, decided_by: str, identity_attested: bool) -> None:
        if not decided_by.strip():
            raise ValueError("Indica quem rejeita o pedido.")
        if identity_attested is not True:
            raise PolicyDenied("Confirma na interface que estás autenticado para rejeitar o pedido.")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT requested_by, status FROM failed_record_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None or row["status"] != "pending":
                raise PolicyDenied("The approval request is missing or is no longer pending.")
            if row["requested_by"].casefold() == decided_by.strip().casefold():
                raise PolicyDenied("A different person must decide the request.")
            connection.execute(
                "UPDATE failed_record_approvals SET status = 'rejected', decided_by = ?, decider_attested = 1, "
                "finished_at = ? "
                "WHERE approval_id = ? AND status = 'pending'",
                (decided_by.strip(), _now(), approval_id),
            )

    def list_for_incident(self, incident_id: str) -> list[FailedRecordApproval]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT p.* FROM failed_record_approvals p "
                "JOIN incident_attempts a ON a.run_id = p.source_run_id "
                "WHERE a.incident_id = ? ORDER BY p.approval_id",
                (incident_id,),
            ).fetchall()
        return [FailedRecordApproval.model_validate(dict(row)) for row in rows]
