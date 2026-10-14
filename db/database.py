"""SQLite database for incident history, agent outputs, and audit trail.

Stores the full lifecycle of each incident:
- Incident metadata and raw logs
- Each agent's input/output/timing
- Execution results and postmortems
- Query helpers for the Streamlit UI
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agents.models import AgentStep, IncidentState

logger = logging.getLogger("incident_response.db")

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS incidents (
    id              TEXT PRIMARY KEY,
    incident_type   TEXT NOT NULL,
    log_source      TEXT NOT NULL,
    raw_logs        TEXT,
    auto_approve    INTEGER DEFAULT 0,
    metadata_json   TEXT DEFAULT '{}',
    pipeline_status TEXT DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    completed_at    TEXT,

    -- Agent outputs (stored as JSON strings)
    log_analysis    TEXT,
    root_cause      TEXT,
    fix_proposal    TEXT,
    safety_report   TEXT,
    execution_result TEXT,
    postmortem      TEXT,
    status_update   TEXT
);

CREATE TABLE IF NOT EXISTS agent_steps (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL,
    agent_name      TEXT NOT NULL,
    status          TEXT DEFAULT 'pending',
    input_data      TEXT,
    output_data     TEXT,
    raw_llm_response TEXT,
    error           TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    duration_ms     INTEGER,
    FOREIGN KEY (incident_id) REFERENCES incidents(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    agent_name      TEXT,
    message         TEXT,
    details_json    TEXT,
    FOREIGN KEY (incident_id) REFERENCES incidents(id)
);

CREATE INDEX IF NOT EXISTS idx_steps_incident ON agent_steps(incident_id);
CREATE INDEX IF NOT EXISTS idx_audit_incident ON audit_log(incident_id);
CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at);
"""


class IncidentDatabase:
    """SQLite-backed storage for incidents and their pipeline results."""

    def __init__(self, db_path: str = "db/incidents.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.info("Database initialized at %s", self.db_path)

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            logger.debug("Schema initialized (version %d)", SCHEMA_VERSION)

    # ── Incident CRUD ─────────────────────────────────────────────────

    def save_incident(self, state: IncidentState) -> None:
        """Insert or update an incident from a pipeline IncidentState."""
        from dataclasses import asdict

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO incidents (
                    id, incident_type, log_source, raw_logs, auto_approve,
                    metadata_json, pipeline_status, created_at, completed_at,
                    log_analysis, root_cause, fix_proposal, safety_report,
                    execution_result, postmortem, status_update
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    pipeline_status = excluded.pipeline_status,
                    completed_at = excluded.completed_at,
                    log_analysis = excluded.log_analysis,
                    root_cause = excluded.root_cause,
                    fix_proposal = excluded.fix_proposal,
                    safety_report = excluded.safety_report,
                    execution_result = excluded.execution_result,
                    postmortem = excluded.postmortem,
                    status_update = excluded.status_update
                """,
                (
                    state.incident_id,
                    state.incident_type,
                    state.log_source,
                    state.raw_logs,
                    1 if state.auto_approve else 0,
                    json.dumps(state.metadata, default=str),
                    state.pipeline_status,
                    state.created_at,
                    datetime.now(timezone.utc).isoformat() if state.pipeline_status in ("completed", "failed") else None,
                    json.dumps(asdict(state.log_analysis), default=str) if state.log_analysis else None,
                    json.dumps(asdict(state.root_cause), default=str) if state.root_cause else None,
                    json.dumps(asdict(state.fix_proposal), default=str) if state.fix_proposal else None,
                    json.dumps(asdict(state.safety_report), default=str) if state.safety_report else None,
                    json.dumps(asdict(state.execution_result), default=str) if state.execution_result else None,
                    state.postmortem,
                    state.status_update,
                ),
            )

            # Save agent steps
            for step in state.steps:
                self._save_step(conn, state.incident_id, step)

            # Audit log entry
            self._log_audit(
                conn,
                state.incident_id,
                "pipeline_save",
                message=f"Pipeline state saved (status={state.pipeline_status})",
            )

        logger.info("Incident %s saved to database", state.incident_id)

    def _save_step(self, conn: sqlite3.Connection, incident_id: str, step: AgentStep) -> None:
        """Insert or update an agent step record."""
        # Check if step already exists
        existing = conn.execute(
            "SELECT id FROM agent_steps WHERE incident_id = ? AND agent_name = ?",
            (incident_id, step.agent_name),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE agent_steps SET
                    status = ?, input_data = ?, output_data = ?,
                    raw_llm_response = ?, error = ?,
                    started_at = ?, completed_at = ?, duration_ms = ?
                WHERE incident_id = ? AND agent_name = ?
                """,
                (
                    step.status.value if hasattr(step.status, 'value') else step.status,
                    step.input_data,
                    step.output_data,
                    step.raw_llm_response,
                    step.error,
                    step.started_at,
                    step.completed_at,
                    step.duration_ms,
                    incident_id,
                    step.agent_name,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO agent_steps (
                    incident_id, agent_name, status, input_data, output_data,
                    raw_llm_response, error, started_at, completed_at, duration_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    step.agent_name,
                    step.status.value if hasattr(step.status, 'value') else step.status,
                    step.input_data,
                    step.output_data,
                    step.raw_llm_response,
                    step.error,
                    step.started_at,
                    step.completed_at,
                    step.duration_ms,
                ),
            )

    def get_incident(self, incident_id: str) -> Optional[dict]:
        """Retrieve a single incident by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()

            if row is None:
                return None

            incident = dict(row)
            # Parse JSON fields back into dicts
            for field in ["log_analysis", "root_cause", "fix_proposal",
                          "safety_report", "execution_result", "metadata_json"]:
                if incident.get(field):
                    try:
                        incident[field] = json.loads(incident[field])
                    except (json.JSONDecodeError, TypeError):
                        pass

            # Attach agent steps
            steps = conn.execute(
                "SELECT * FROM agent_steps WHERE incident_id = ? ORDER BY id",
                (incident_id,),
            ).fetchall()
            incident["steps"] = [dict(s) for s in steps]

            return incident

    def list_incidents(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """List incidents ordered by creation time (newest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, incident_type, pipeline_status, created_at, completed_at
                FROM incidents
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_incident_count(self) -> int:
        """Return total number of incidents."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM incidents").fetchone()
            return row["cnt"] if row else 0

    def get_steps_for_incident(self, incident_id: str) -> list[dict]:
        """Get all agent steps for a specific incident."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_steps WHERE incident_id = ? ORDER BY id",
                (incident_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_incident(self, incident_id: str) -> bool:
        """Delete an incident and its related records."""
        with self._connect() as conn:
            conn.execute("DELETE FROM agent_steps WHERE incident_id = ?", (incident_id,))
            conn.execute("DELETE FROM audit_log WHERE incident_id = ?", (incident_id,))
            result = conn.execute("DELETE FROM incidents WHERE id = ?", (incident_id,))
            deleted = result.rowcount > 0
            if deleted:
                logger.info("Incident %s deleted", incident_id)
            return deleted

    # ── Audit Log ─────────────────────────────────────────────────────

    def _log_audit(
        self,
        conn: sqlite3.Connection,
        incident_id: str,
        event_type: str,
        agent_name: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Write an audit log entry."""
        now = datetime.now(datetime.timezone.utc).isoformat() if hasattr(datetime, 'timezone') else datetime.utcnow().isoformat() + "Z"
        conn.execute(
            "INSERT OR IGNORE INTO incidents (id, incident_type, log_source, created_at) VALUES (?, 'audit', 'system', ?)",
            (incident_id, now),
        )
        conn.execute(
            """
            INSERT INTO audit_log (incident_id, timestamp, event_type, agent_name, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                datetime.utcnow().isoformat() + "Z",
                event_type,
                agent_name,
                message,
                json.dumps(details, default=str) if details else None,
            ),
        )

    def log_event(
        self,
        incident_id: str,
        event_type: str,
        agent_name: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Public method to log an audit event."""
        with self._connect() as conn:
            self._log_audit(conn, incident_id, event_type, agent_name, message, details)

    def get_audit_log(self, incident_id: str) -> list[dict]:
        """Retrieve the full audit trail for an incident."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE incident_id = ? ORDER BY timestamp",
                (incident_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Statistics ────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return aggregate statistics for the dashboard."""
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) as cnt FROM incidents").fetchone()["cnt"]
            completed = conn.execute(
                "SELECT COUNT(*) as cnt FROM incidents WHERE pipeline_status = 'completed'"
            ).fetchone()["cnt"]
            failed = conn.execute(
                "SELECT COUNT(*) as cnt FROM incidents WHERE pipeline_status = 'failed'"
            ).fetchone()["cnt"]

            # Average pipeline duration (from steps)
            avg_row = conn.execute(
                """
                SELECT AVG(total_ms) as avg_ms FROM (
                    SELECT incident_id, SUM(duration_ms) as total_ms
                    FROM agent_steps
                    WHERE duration_ms IS NOT NULL
                    GROUP BY incident_id
                )
                """
            ).fetchone()

            # Most common incident types
            type_rows = conn.execute(
                """
                SELECT incident_type, COUNT(*) as cnt
                FROM incidents
                GROUP BY incident_type
                ORDER BY cnt DESC
                LIMIT 5
                """
            ).fetchall()

            return {
                "total_incidents": total,
                "completed": completed,
                "failed": failed,
                "pending": total - completed - failed,
                "avg_pipeline_duration_ms": round(avg_row["avg_ms"]) if avg_row and avg_row["avg_ms"] else 0,
                "incident_types": {r["incident_type"]: r["cnt"] for r in type_rows},
            }
