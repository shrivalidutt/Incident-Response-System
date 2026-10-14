"""Fix Proposer Agent.

Role: Proposes 2-3 ranked fixes using standard runbook practices.
Input: shared_state["root_cause"], (and rejection_reason if looping back)
Output: dict with "proposed_fixes", "recommended_fix_id"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents.models import FixProposal

logger = logging.getLogger("incident_response.agent.fix_proposer")

PROMPT_FILE = Path("prompts/fix_proposer.txt")
DEFAULT_PROMPT = """You are a fix-recommendation agent following standard SRE runbook practices.
Given the root cause analysis, propose 2-3 ranked fixes using standard commands targeting container 'demo-app'.
Output ONLY valid JSON."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Fix Proposer agent."""
    root_cause = shared_state.get("root_cause", "")
    error_summary = shared_state.get("error_summary", {})
    rejection_feedback = shared_state.get("rejection_feedback") or shared_state.get("rejection_reason")

    system_prompt = load_prompt()
    user_payload: dict[str, Any] = {
        "root_cause": root_cause,
        "error_summary": error_summary,
    }

    if rejection_feedback:
        user_payload["REJECTION_FEEDBACK"] = (
            f"The previous proposed fix was REJECTED: {rejection_feedback}. "
            "Do NOT propose the rejected fix again. Provide a safer or alternative approach."
        )

    user_message = f"Root Cause Analysis and Context:\n{json.dumps(user_payload, indent=2)}"

    logger.info("Fix Proposer formulating remediation proposals (feedback=%s)", bool(rejection_feedback))
    result = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=True)

    if isinstance(result, str):
        result = json.loads(result)

    fix_model = FixProposal.from_dict(result)

    return {
        "proposed_fixes": [
            {
                "id": f.id,
                "title": f.title,
                "description": f.description,
                "commands": f.commands,
                "risk_level": f.risk_level,
                "estimated_downtime": f.estimated_downtime,
                "rollback_plan": f.rollback_plan,
            }
            for f in fix_model.proposed_fixes
        ],
        "recommended_fix_id": fix_model.recommended_fix_id,
        "fix_proposal": result,
    }
