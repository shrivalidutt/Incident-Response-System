"""Postmortem Writer Agent.

Role: Technical writer producing structured markdown/HTML postmortem report:
timeline, root cause, fix applied, prevention recommendations.
Input: entire shared_state
Output: dict with "postmortem_report" (and "postmortem")
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("incident_response.agent.postmortem_writer")

PROMPT_FILE = Path("prompts/postmortem_writer.txt")
DEFAULT_PROMPT = """You are a technical writer producing a postmortem report for an incident.
Given the full incident state, write a structured postmortem in Markdown format:
# Incident Postmortem: [Title]
## Summary
## Impact
## Timeline
## Root Cause
## Resolution
## Lessons Learned
## Action Items
Output the Markdown directly."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Postmortem Writer agent on the full shared state."""
    system_prompt = load_prompt()

    # Pass the cumulative incident context
    context = {
        "incident_id": shared_state.get("incident_id"),
        "scenario": shared_state.get("scenario") or shared_state.get("incident_type"),
        "error_summary": shared_state.get("error_summary"),
        "timeline": shared_state.get("timeline"),
        "root_cause": shared_state.get("root_cause"),
        "evidence": shared_state.get("evidence"),
        "approved_fix": shared_state.get("approved_fix"),
        "execution_result": shared_state.get("execution_result"),
        "rejection_reason": shared_state.get("rejection_reason"),
    }

    user_message = f"Full Cumulative Incident State:\n{json.dumps(context, indent=2, default=str)}"

    logger.info("Postmortem Writer drafting comprehensive report")
    report = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=False)

    report_str = str(report).strip()

    return {
        "postmortem_report": report_str,
        "postmortem": report_str,
    }
