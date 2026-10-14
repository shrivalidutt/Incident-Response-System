"""Runbook Executor Agent.

Role: Thin execution wrapper (not an LLM agent) that maps approved fixes
to real or simulated Docker actions via DockerExecutor / Docker SDK / subprocess.
Safety Rule: Hard gate — if Safety Checker rejected the fix, or if approved_fix is None,
the executor absolutely refuses to run.
Input: shared_state["approved_fix"], shared_state.get("safety_report")
Output: dict with "execution_result"
"""

from __future__ import annotations

import logging
from typing import Any

from agents.docker_executor import DockerExecutor
from agents.models import ExecutionResult

logger = logging.getLogger("incident_response.agent.runbook_executor")


def run_agent(shared_state: dict[str, Any], executor: DockerExecutor) -> dict[str, Any]:
    """Execute the approved fix against Docker/container."""
    approved_fix = shared_state.get("approved_fix")
    rejection_reason = shared_state.get("rejection_reason")

    # Hard gate verification:
    if not approved_fix or rejection_reason and "HARD GATE" in rejection_reason:
        error_msg = f"HARD GATE BLOCKED EXECUTION: No valid safe approved fix. Reason: {rejection_reason}"
        logger.error(error_msg)
        return {
            "execution_result": {
                "fix_id": 0,
                "commands_run": [],
                "outputs": [error_msg],
                "success": False,
                "error": error_msg,
                "dry_run": executor.dry_run,
            }
        }

    # Verify that the approved fix is not marked HIGH risk in safety evaluations
    evaluations = shared_state.get("evaluations", [])
    approved_id = shared_state.get("approved_fix_id") or (approved_fix.get("id") if isinstance(approved_fix, dict) else 0)
    for ev in evaluations:
        if ev.get("fix_id") == approved_id and ev.get("risk_classification") == "HIGH":
            error_msg = f"HARD GATE BLOCKED EXECUTION: Fix #{approved_id} was classified HIGH risk by Safety Checker."
            logger.error(error_msg)
            return {
                "execution_result": {
                    "fix_id": approved_id,
                    "commands_run": [],
                    "outputs": [error_msg],
                    "success": False,
                    "error": error_msg,
                    "dry_run": executor.dry_run,
                }
            }

    logger.info("Runbook Executor running approved fix #%s", approved_id)
    result: ExecutionResult = executor.execute_fix(approved_fix)

    return {
        "execution_result": {
            "fix_id": result.fix_id,
            "commands_run": result.commands_run,
            "outputs": result.outputs,
            "success": result.success,
            "error": result.error,
            "dry_run": result.dry_run,
        }
    }
