"""Tests for Orchestrator hub-and-spoke execution and loop on rejection."""

import pytest
from pathlib import Path
from agents.llm_client import LLMClient
from db.database import IncidentDatabase
from orchestrator import Orchestrator


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_incidents.db"
    return IncidentDatabase(db_path=str(db_file))


@pytest.fixture
def orchestrator(temp_db):
    llm = LLMClient(provider="mock")
    return Orchestrator(llm_client=llm, db=temp_db, dry_run=True)


def test_orchestrator_initializes_state(orchestrator):
    state = orchestrator.init_incident(
        scenario="oom_crash",
        raw_logs="2026-10-08T02:12:46Z ERROR java.lang.OutOfMemoryError",
    )
    assert state["scenario"] == "oom_crash"
    assert state["status"] == "initialized"
    assert "agent_log" in state
    assert len(state["agent_log"]) == 0


def test_orchestrator_runs_phase1_and_awaits_approval_or_completes(orchestrator):
    logs = Path("scenarios/bad_deploy.log").read_text(encoding="utf-8")
    orchestrator.init_incident(scenario="bad_deploy", raw_logs=logs, auto_approve=False)

    state = orchestrator.run_phase1_analysis_to_safety()
    assert state["error_summary"]
    assert state["root_cause"]
    assert len(state["proposed_fixes"]) > 0

    # For bad_deploy, safety checker flags rollback as MEDIUM risk requiring approval
    assert state["status"] in ("awaiting_approval", "ready_for_execution")


def test_orchestrator_loop_on_human_rejection(orchestrator):
    """Test FR3 rejection loop back to Fix Proposer."""
    logs = Path("scenarios/bad_deploy.log").read_text(encoding="utf-8")
    orchestrator.init_incident(scenario="bad_deploy", raw_logs=logs, auto_approve=False)
    orchestrator.run_phase1_analysis_to_safety()

    # Operator rejects the fix
    rejection_msg = "Please provide an in-place configuration change rather than rolling back"
    updated_state = orchestrator.handle_rejection(feedback=rejection_msg)

    assert orchestrator.rejection_count == 1
    assert updated_state["rejection_feedback"] == rejection_msg
    assert len(updated_state["proposed_fixes"]) > 0


def test_orchestrator_full_pipeline_end_to_end(orchestrator):
    logs = Path("scenarios/oom_crash.log").read_text(encoding="utf-8")
    final_state = orchestrator.run_full_pipeline(
        scenario="oom_crash",
        raw_logs=logs,
        auto_approve=True,
    )
    assert final_state["status"] == "completed"
    assert final_state["postmortem_report"]
    assert final_state["status_update"]
    assert len(final_state["agent_log"]) >= 6
