"""Root-Cause Analyst Agent.

Role: Diagnoses the most likely root cause from error summary and timeline.
Input: shared_state["error_summary"], shared_state["timeline"]
Output: dict with "root_cause", "confidence", "alternative_causes", "evidence", "category"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from agents.models import RootCauseAnalysis

logger = logging.getLogger("incident_response.agent.root_cause")

PROMPT_FILE = Path("prompts/root_cause.txt")
DEFAULT_PROMPT = """You are a senior SRE diagnosing a production incident.
Given the error summary and timeline from the Log Analyst, determine the root cause.
Produce a JSON object with: root_cause, confidence, evidence, alternative_causes, category.
Output ONLY valid JSON."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Root-Cause Analyst agent."""
    error_summary = shared_state.get("error_summary", {})
    timeline = shared_state.get("timeline", [])

    system_prompt = load_prompt()
    user_message = (
        f"Incident Error Summary:\n{json.dumps(error_summary, indent=2)}\n\n"
        f"Timeline of Events:\n{json.dumps(timeline, indent=2)}"
    )

    logger.info("Root Cause Analyst investigating incident")
    result = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=True)

    if isinstance(result, str):
        result = json.loads(result)

    rca_model = RootCauseAnalysis.from_dict(result)

    return {
        "root_cause": rca_model.root_cause,
        "confidence": rca_model.confidence,
        "evidence": rca_model.evidence,
        "alternative_causes": [
            {"cause": ac.cause, "confidence": ac.confidence, "why_less_likely": ac.why_less_likely}
            for ac in rca_model.alternative_causes
        ],
        "category": rca_model.category,
        "root_cause_analysis": result,
    }
