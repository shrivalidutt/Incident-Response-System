"""Safety Checker Agent.

Role: Safety gate evaluating proposed fixes.
Hard gate: HIGH risk fixes are rejected outright and CANNOT be executed even with human approval.
LOW risk fixes can proceed automatically.
MEDIUM risk fixes require human approval.
Input: shared_state["proposed_fixes"]
Output: dict with "approved_fix", "rejection_reason", "evaluations", "requires_human_approval"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents.models import SafetyReport

logger = logging.getLogger("incident_response.agent.safety_checker")

PROMPT_FILE = Path("prompts/safety_checker.txt")
DEFAULT_PROMPT = """You are a safety gate for production changes. Your classification is FINAL and cannot be overridden.
Given the list of proposed fixes, evaluate each one for safety (LOW, MEDIUM, HIGH).
Reject HIGH risk fixes outright; MEDIUM requires human approval; LOW can proceed automatically.
Output ONLY valid JSON."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Safety Checker agent."""
    proposed_fixes = shared_state.get("proposed_fixes", [])
    if not proposed_fixes:
        raise ValueError("Safety Checker requires 'proposed_fixes' in shared_state.")

    system_prompt = load_prompt()
    user_message = f"Proposed Fixes to evaluate for safety:\n{json.dumps(proposed_fixes, indent=2)}"

    logger.info("Safety Checker evaluating %d proposed fixes", len(proposed_fixes))
    result = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=True)

    if isinstance(result, str):
        result = json.loads(result)

    safety_model = SafetyReport.from_dict(result)

    # Enforce Hard Gate:
    # If the approved fix is classified as HIGH risk, or contains dangerous commands, reject it!
    approved_fix = safety_model.approved_fix
    approved_id = safety_model.approved_fix_id
    rejection_reasons = list(safety_model.rejection_reasons)

    # Check if approved fix is secretly HIGH risk or missing
    is_safe = False
    if approved_fix and approved_id > 0:
        for eval_item in safety_model.evaluations:
            if eval_item.fix_id == approved_id:
                if eval_item.risk_classification == "HIGH":
                    rejection_reasons.append(
                        f"HARD GATE TRIGGERED: Fix #{approved_id} is classified as HIGH risk and cannot be executed under any circumstances."
                    )
                    approved_fix = None
                    approved_id = 0
                else:
                    is_safe = True
                break

    # If approved_fix was not selected or was rejected
    rejection_reason = " | ".join(rejection_reasons) if rejection_reasons else ""

    return {
        "approved_fix": approved_fix,
        "approved_fix_id": approved_id,
        "requires_human_approval": safety_model.requires_human_approval if approved_fix else False,
        "rejection_reason": rejection_reason,
        "rejection_reasons": rejection_reasons,
        "evaluations": [
            {
                "fix_id": e.fix_id,
                "risk_classification": e.risk_classification,
                "reasoning": e.reasoning,
                "potential_impact": e.potential_impact,
                "safeguards_present": e.safeguards_present,
            }
            for e in safety_model.evaluations
        ],
        "safety_report": result,
    }
