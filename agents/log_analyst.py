"""Log Analyst Agent.

Role: Extracts error types, timeline, and affected services from raw logs.
Input: shared_state["raw_logs"]
Output: dict with "error_summary" and "timeline" (and structured fields)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agents.models import LogAnalysis

logger = logging.getLogger("incident_response.agent.log_analyst")

PROMPT_FILE = Path("prompts/log_analyst.txt")
DEFAULT_PROMPT = """You are a log analysis expert on an on-call engineering team.
Your job is to extract structured information from raw server logs.
Given the raw logs below, produce a JSON object with:
error_types, error_count, first_error_at, last_error_at, timeline, affected_services, summary.
Output ONLY valid JSON."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Log Analyst agent on the shared incident state."""
    raw_logs = shared_state.get("raw_logs", "")
    if not raw_logs:
        raise ValueError("Log Analyst requires 'raw_logs' in shared_state.")

    system_prompt = load_prompt()
    user_message = f"Here are the raw production logs:\n\n{raw_logs}"

    logger.info("Log Analyst analyzing %d characters of log data", len(raw_logs))
    result = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=True)

    # Validate / normalize
    if isinstance(result, str):
        import json
        result = json.loads(result)

    analysis_model = LogAnalysis.from_dict(result)

    return {
        "error_summary": {
            "error_types": analysis_model.error_types,
            "error_count": analysis_model.error_count,
            "first_error_at": analysis_model.first_error_at,
            "last_error_at": analysis_model.last_error_at,
            "affected_services": analysis_model.affected_services,
            "summary": analysis_model.summary,
        },
        "timeline": [
            {"timestamp": e.timestamp, "event": e.event, "severity": e.severity}
            for e in analysis_model.timeline
        ],
        "log_analysis": result,
    }
