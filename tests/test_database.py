"""Tests for SQLite database persistence, history, and audit logging."""

import pytest
from db.database import IncidentDatabase
from agents.models import IncidentState, AgentStep, AgentStatus


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_db.db"
    return IncidentDatabase(db_path=str(db_file))


def test_incident_lifecycle_persistence(db):
    state = IncidentState(
        incident_id="inc-test-001",
        incident_type="oom_crash",
        log_source="scenarios/oom_crash.log",
        raw_logs="sample logs",
        pipeline_status="running",
    )
    db.save_incident(state)

    retrieved = db.get_incident("inc-test-001")
    assert retrieved is not None
    assert retrieved["id"] == "inc-test-001"
    assert retrieved["incident_type"] == "oom_crash"
    assert retrieved["pipeline_status"] == "running"


def test_audit_logging(db):
    db.log_event(
        incident_id="inc-test-002",
        event_type="safety_rejection",
        agent_name="safety_checker",
        message="Rejected high risk fix",
        details={"risk": "HIGH"},
    )
    logs = db.get_audit_log("inc-test-002")
    assert len(logs) == 1
    assert logs[0]["event_type"] == "safety_rejection"
    assert logs[0]["agent_name"] == "safety_checker"


def test_database_stats(db):
    state1 = IncidentState(incident_id="inc-1", incident_type="oom_crash", pipeline_status="completed")
    state2 = IncidentState(incident_id="inc-2", incident_type="db_failure", pipeline_status="failed")
    db.save_incident(state1)
    db.save_incident(state2)

    stats = db.get_stats()
    assert stats["total_incidents"] == 2
    assert stats["completed"] == 1
    assert stats["failed"] == 1
