"""Tests for Safety Checker agent and hard gate enforcement."""

import pytest
from agents.llm_client import LLMClient
import agents.safety_checker as safety_checker
import agents.runbook_executor as runbook_executor
from agents.docker_executor import DockerExecutor


def test_safety_checker_evaluates_risk():
    llm = LLMClient(provider="mock")
    shared_state = {
        "proposed_fixes": [
            {
                "id": 1,
                "title": "Restart Container",
                "description": "Restart container",
                "commands": ["docker restart demo-app"],
                "risk_level": "LOW",
                "estimated_downtime": "< 10s",
                "rollback_plan": "docker restart demo-app",
            },
            {
                "id": 2,
                "title": "Drop Database",
                "description": "Drop tables",
                "commands": ["docker exec demo-app drop database production"],
                "risk_level": "HIGH",
                "estimated_downtime": "permanent",
                "rollback_plan": "none",
            },
        ]
    }

    result = safety_checker.run_agent(shared_state, llm)
    assert "approved_fix" in result
    assert "evaluations" in result
    assert len(result["evaluations"]) > 0

    # Ensure HIGH risk fix is identified and marked
    high_risk_evals = [e for e in result["evaluations"] if e["risk_classification"] == "HIGH"]
    assert len(high_risk_evals) > 0


def test_hard_gate_blocks_high_risk_execution():
    """Non-functional requirement: Safety Checker rejection is final and cannot be bypassed."""
    executor = DockerExecutor(dry_run=True)

    # Attempt to execute a HIGH risk fix that was rejected by Safety Checker
    shared_state = {
        "approved_fix": {
            "id": 3,
            "title": "Purge all database tables",
            "commands": ["docker exec demo-app drop database if exists production"],
        },
        "approved_fix_id": 3,
        "evaluations": [
            {"fix_id": 3, "risk_classification": "HIGH", "reasoning": "High danger of data loss"}
        ],
        "rejection_reason": "HARD GATE TRIGGERED: Fix #3 is classified as HIGH risk and cannot be executed.",
    }

    result = runbook_executor.run_agent(shared_state, executor)
    assert result["execution_result"]["success"] is False
    assert "HARD GATE BLOCKED" in result["execution_result"]["error"]
    assert len(result["execution_result"]["commands_run"]) == 0
