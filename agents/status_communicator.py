"""Status Communicator Agent.

Role: Drafts a one-paragraph non-technical update suitable for Slack or public status page.
Input: shared_state
Output: dict with "status_update"
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("incident_response.agent.status_communicator")

PROMPT_FILE = Path("prompts/status_communicator.txt")
DEFAULT_PROMPT = """You are a communications specialist. Given the full incident state,
write a brief 3-5 sentence non-technical status update for Slack or a status page.
Output the message text directly."""


def load_prompt() -> str:
    if PROMPT_FILE.exists():
        return PROMPT_FILE.read_text(encoding="utf-8")
    return DEFAULT_PROMPT


def run_agent(shared_state: dict[str, Any], llm_client: Any) -> dict[str, Any]:
    """Execute the Status Communicator agent."""
    system_prompt = load_prompt()

    context = {
        "incident_type": shared_state.get("incident_type") or shared_state.get("scenario"),
        "root_cause": shared_state.get("root_cause"),
        "fix_applied": shared_state.get("execution_result"),
        "error_summary": shared_state.get("error_summary", {}).get("summary", ""),
        "postmortem_excerpt": (shared_state.get("postmortem_report") or "")[:400],
    }

    user_message = f"Incident Summary for Stakeholder Update:\n{json.dumps(context, indent=2, default=str)}"

    logger.info("Status Communicator drafting stakeholder message")
    message = llm_client.call(system_prompt=system_prompt, user_message=user_message, parse_json=False)

    return {
        "status_update": str(message).strip()
    }
