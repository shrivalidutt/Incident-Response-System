"""Unit tests for each specialized agent in the pipeline."""

from pathlib import Path
import pytest

from agents.llm_client import LLMClient
import agents.log_analyst as agent_log_analyst
import agents.root_cause as agent_root_cause
import agents.fix_proposer as agent_fix_proposer
import agents.safety_checker as agent_safety_checker
import agents.runbook_executor as agent_runbook_executor
import agents.postmortem_writer as agent_postmortem_writer
import agents.status_communicator as agent_status_communicator
from agents.docker_executor import DockerExecutor


@pytest.fixture
def llm():
    return LLMClient(provider="mock")


@pytest.fixture
def oom_logs():
    p = Path("scenarios/oom_crash.log")
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "2026-10-08T02:12:46Z ERROR java.lang.OutOfMemoryError: Java heap space"


def test_log_analyst(llm, oom_logs):
    state = {"raw_logs": oom_logs}
    output = agent_log_analyst.run_agent(state, llm)
    assert "error_summary" in output
    assert "timeline" in output
    assert output["error_summary"]["error_count"] > 0
    assert len(output["timeline"]) > 0


def test_root_cause_analyst(llm, oom_logs):
    state = {
        "raw_logs": oom_logs,
        "error_summary": {
            "error_types": ["OutOfMemoryError"],
            "error_count": 14,
            "summary": "Heap usage at 98%",
        },
        "timeline": [
            {"timestamp": "02:12:46Z", "event": "OutOfMemoryError in UserService", "severity": "ERROR"}
        ],
    }
    output = agent_root_cause.run_agent(state, llm)
    assert "root_cause" in output
    assert "confidence" in output
    assert output["confidence"] >= 0.8
    assert len(output["evidence"]) > 0


def test_fix_proposer(llm):
    state = {
        "root_cause": "Java heap space OutOfMemoryError in UserService",
        "error_summary": {"error_count": 14},
    }
    output = agent_fix_proposer.run_agent(state, llm)
    assert "proposed_fixes" in output
    assert len(output["proposed_fixes"]) >= 2
    assert "recommended_fix_id" in output

    first_fix = output["proposed_fixes"][0]
    assert "id" in first_fix
    assert "commands" in first_fix
    assert len(first_fix["commands"]) > 0


def test_postmortem_writer(llm):
    state = {
        "scenario": "oom_crash",
        "root_cause": "JVM heap exhaustion",
        "error_summary": {"summary": "Out of memory"},
        "execution_result": {"success": True, "commands_run": ["docker restart demo-app"]},
    }
    output = agent_postmortem_writer.run_agent(state, llm)
    assert "postmortem_report" in output
    report = output["postmortem_report"]
    assert "# Incident Postmortem" in report
    assert "## Summary" in report
    assert "## Root Cause" in report
    assert "## Action Items" in report


def test_status_communicator(llm):
    state = {
        "scenario": "oom_crash",
        "root_cause": "JVM heap exhaustion",
        "execution_result": {"success": True},
    }
    output = agent_status_communicator.run_agent(state, llm)
    assert "status_update" in output
    assert len(output["status_update"]) > 20
