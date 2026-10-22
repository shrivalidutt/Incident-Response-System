"""Multi-Agent Incident Response Orchestrator (Hub-and-Spoke Architecture).

Architecture:
  Every agent communicates exclusively through the Orchestrator via shared_state.
  No agent directly invokes another agent.

Responsibilities:
- Owns and manages shared_state (dict conforming to FR6 data model)
- Runs agents in sequence with automatic retries
- Enforces Safety Checker hard gate (HIGH risk is non-executable)
- Manages human-in-the-loop approval gate for MEDIUM risk fixes
- Loops back to Fix Proposer when human operator rejects a fix
- Logs every agent call (prompt, input, output, latency) to SQLite for observability/reasoning trace
- Emits real-time streaming events for the web UI
"""

from __future__ import annotations

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

from agents.docker_executor import DockerExecutor
from agents.llm_client import LLMClient
from agents.models import AgentStatus, AgentStep, IncidentState
from db.database import IncidentDatabase

# Agent modules
import agents.log_analyst as agent_log_analyst
import agents.root_cause as agent_root_cause
import agents.fix_proposer as agent_fix_proposer
import agents.safety_checker as agent_safety_checker
import agents.runbook_executor as agent_runbook_executor
import agents.postmortem_writer as agent_postmortem_writer
import agents.status_communicator as agent_status_communicator

logger = logging.getLogger("incident_response.orchestrator")

AGENT_METADATA = {
    "log_analyst": {"name": "Log Analyst", "emoji": "🔍", "color": "#4FC3F7"},
    "root_cause": {"name": "Root-Cause Analyst", "emoji": "🧠", "color": "#AB47BC"},
    "fix_proposer": {"name": "Fix Proposer", "emoji": "🔧", "color": "#66BB6A"},
    "safety_checker": {"name": "Safety Checker", "emoji": "🛡️", "color": "#FFA726"},
    "runbook_executor": {"name": "Runbook Executor", "emoji": "🐳", "color": "#29B6F6"},
    "postmortem_writer": {"name": "Postmortem Writer", "emoji": "📝", "color": "#EF5350"},
    "status_communicator": {"name": "Status Communicator", "emoji": "📢", "color": "#26C6DA"},
}


class Orchestrator:
    """Central Hub orchestrating all specialized agents."""

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        db: Optional[IncidentDatabase] = None,
        dry_run: bool = True,
        on_agent_start: Optional[Callable[[str, dict], None]] = None,
        on_agent_complete: Optional[Callable[[str, dict, int], None]] = None,
        on_agent_error: Optional[Callable[[str, str], None]] = None,
        on_approval_needed: Optional[Callable[[dict, dict], None]] = None,
    ):
        self.llm = llm_client or LLMClient()
        self.db = db or IncidentDatabase()
        self.dry_run = dry_run
        self.docker_executor = DockerExecutor(dry_run=dry_run)

        # Event callbacks
        self.on_agent_start = on_agent_start
        self.on_agent_complete = on_agent_complete
        self.on_agent_error = on_agent_error
        self.on_approval_needed = on_approval_needed

        # Shared state
        self.shared_state: dict[str, Any] = {}
        self.rejection_count = 0
        self.max_rejections = 3

    def init_incident(
        self,
        scenario: str,
        raw_logs: str,
        incident_id: Optional[str] = None,
        auto_approve: bool = False,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Initialize the shared state for a new incident."""
        now = datetime.datetime.now(datetime.timezone.utc)
        inc_id = incident_id or f"inc-{now.strftime('%Y%m%d')}-{str(uuid4())[:4]}"

        self.shared_state = {
            "incident_id": inc_id,
            "scenario": scenario,
            "incident_type": scenario,
            "raw_logs": raw_logs,
            "auto_approve": auto_approve,
            "metadata": metadata or {},
            "status": "initialized",
            "created_at": now.isoformat(),

            # Agent outputs (added incrementally)
            "error_summary": {},
            "timeline": [],
            "root_cause": "",
            "confidence": 0.0,
            "alternative_causes": [],
            "evidence": [],
            "category": "unknown",
            "proposed_fixes": [],
            "recommended_fix_id": 1,
            "approved_fix": None,
            "approved_fix_id": 0,
            "rejection_reason": "",
            "rejection_feedback": "",
            "requires_human_approval": False,
            "evaluations": [],
            "execution_result": None,
            "postmortem_report": "",
            "status_update": "",

            # Observability trace
            "agent_log": [],
        }
        self.rejection_count = 0
        self._persist_to_db()
        return self.shared_state

    def run_phase1_analysis_to_safety(self) -> dict[str, Any]:
        """Run Phase 1: Log Analyst -> Root Cause -> Fix Proposer -> Safety Checker.

        Stops right before execution to allow the UI to inspect the fix
        and handle the human approval gate for MEDIUM risk.
        """
        self.shared_state["status"] = "analyzing"

        # 1. Log Analyst
        self._execute_agent_step(
            agent_key="log_analyst",
            runner=lambda: agent_log_analyst.run_agent(self.shared_state, self.llm),
        )

        # 2. Root Cause Analyst
        self._execute_agent_step(
            agent_key="root_cause",
            runner=lambda: agent_root_cause.run_agent(self.shared_state, self.llm),
        )

        # 3. Fix Proposer
        self._execute_agent_step(
            agent_key="fix_proposer",
            runner=lambda: agent_fix_proposer.run_agent(self.shared_state, self.llm),
        )

        # 4. Safety Checker
        self._execute_agent_step(
            agent_key="safety_checker",
            runner=lambda: agent_safety_checker.run_agent(self.shared_state, self.llm),
        )

        # Evaluate safety gate state
        approved_fix = self.shared_state.get("approved_fix")
        rejection_reason = self.shared_state.get("rejection_reason", "")
        requires_approval = self.shared_state.get("requires_human_approval", False)

        if not approved_fix:
            self.shared_state["status"] = "blocked_by_safety_gate"
            logger.warning("Safety Checker rejected all fixes: %s", rejection_reason)
        elif requires_approval and not self.shared_state.get("auto_approve", False):
            self.shared_state["status"] = "awaiting_approval"
            logger.info("Fix #%s requires human approval", self.shared_state.get("approved_fix_id"))
            if self.on_approval_needed:
                self.on_approval_needed(approved_fix, self.shared_state.get("safety_report", {}))
        else:
            self.shared_state["status"] = "ready_for_execution"

        self._persist_to_db()
        return self.shared_state

    def handle_rejection(self, feedback: str) -> dict[str, Any]:
        """Handle human operator rejection of the proposed fix.

        Loops control back to the Fix Proposer with rejection feedback!
        """
        self.rejection_count += 1
        logger.info("Human operator rejected proposed fix (attempt %d). Feedback: %s", self.rejection_count, feedback)

        self.shared_state["rejection_feedback"] = feedback
        self.shared_state["rejection_reason"] = f"Rejected by operator: {feedback}"
        self.shared_state["status"] = "refining_fix"

        self.db.log_event(
            incident_id=self.shared_state["incident_id"],
            event_type="human_rejection",
            agent_name="human_operator",
            message=f"Human rejected fix: {feedback}",
            details={"attempt": self.rejection_count, "feedback": feedback},
        )

        # Loop back to Fix Proposer
        self._execute_agent_step(
            agent_key="fix_proposer",
            runner=lambda: agent_fix_proposer.run_agent(self.shared_state, self.llm),
        )

        # Re-run Safety Checker on new proposal
        self._execute_agent_step(
            agent_key="safety_checker",
            runner=lambda: agent_safety_checker.run_agent(self.shared_state, self.llm),
        )

        approved_fix = self.shared_state.get("approved_fix")
        requires_approval = self.shared_state.get("requires_human_approval", False)

        if not approved_fix:
            self.shared_state["status"] = "blocked_by_safety_gate"
        elif requires_approval and not self.shared_state.get("auto_approve", False):
            self.shared_state["status"] = "awaiting_approval"
            if self.on_approval_needed:
                self.on_approval_needed(approved_fix, self.shared_state.get("safety_report", {}))
        else:
            self.shared_state["status"] = "ready_for_execution"

        self._persist_to_db()
        return self.shared_state

    def run_phase2_execution_and_reporting(self, user_approved: bool = True) -> dict[str, Any]:
        """Run Phase 2: Runbook Executor -> Postmortem Writer -> Status Communicator."""
        approved_fix = self.shared_state.get("approved_fix")

        # Hard Gate verification: Rejection is FINAL
        evaluations = self.shared_state.get("evaluations", [])
        approved_id = self.shared_state.get("approved_fix_id", 0)

        for ev in evaluations:
            if ev.get("fix_id") == approved_id and ev.get("risk_classification") == "HIGH":
                error_msg = f"HARD GATE BLOCKED: Safety Checker rejected Fix #{approved_id} as HIGH risk. Cannot execute."
                logger.error(error_msg)
                self.shared_state["execution_result"] = {
                    "fix_id": approved_id,
                    "commands_run": [],
                    "outputs": [error_msg],
                    "success": False,
                    "error": error_msg,
                    "dry_run": self.dry_run,
                }
                self.shared_state["status"] = "failed"
                self._persist_to_db()
                return self.shared_state

        if not user_approved:
            logger.info("Human operator declined execution")
            self.shared_state["execution_result"] = {
                "fix_id": approved_id,
                "commands_run": [],
                "outputs": ["Execution cancelled by operator"],
                "success": False,
                "error": "Operator declined",
                "dry_run": self.dry_run,
            }
        else:
            # 5. Runbook Executor
            self._execute_agent_step(
                agent_key="runbook_executor",
                runner=lambda: agent_runbook_executor.run_agent(self.shared_state, self.docker_executor),
            )

        # 6. Postmortem Writer
        self._execute_agent_step(
            agent_key="postmortem_writer",
            runner=lambda: agent_postmortem_writer.run_agent(self.shared_state, self.llm),
        )

        # 7. Status Communicator
        self._execute_agent_step(
            agent_key="status_communicator",
            runner=lambda: agent_status_communicator.run_agent(self.shared_state, self.llm),
        )

        self.shared_state["status"] = "completed"
        self._persist_to_db()
        return self.shared_state

    def run_full_pipeline(
        self,
        scenario: str,
        raw_logs: str,
        auto_approve: bool = False,
        human_approval_callback: Optional[Callable[[dict], bool]] = None,
    ) -> dict[str, Any]:
        """Run the full pipeline end-to-end synchronously."""
        self.init_incident(scenario, raw_logs, auto_approve=auto_approve)

        # Phase 1
        self.run_phase1_analysis_to_safety()

        # Approval handling
        if self.shared_state.get("status") == "awaiting_approval":
            if human_approval_callback:
                approved = human_approval_callback(self.shared_state.get("approved_fix", {}))
                if not approved:
                    self.handle_rejection(feedback="Operator requested alternative fix")
                    return self.run_phase2_execution_and_reporting(user_approved=True)
            elif not auto_approve:
                logger.info("Pending manual approval")
                return self.shared_state

        # Phase 2
        return self.run_phase2_execution_and_reporting(user_approved=True)

    def _execute_agent_step(self, agent_key: str, runner: Callable[[], dict[str, Any]]) -> None:
        """Execute a single agent with latency measurement, logging, and error handling."""
        meta = AGENT_METADATA.get(agent_key, {"name": agent_key, "emoji": "🤖"})
        agent_name = meta["name"]
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
 
        if self.on_agent_start:
            try:
                self.on_agent_start(agent_key, meta)
            except Exception as cb_err:
                logger.warning("on_agent_start callback failed (non-fatal): %s", cb_err)

        start_time = time.time()
        error_msg = None
        output: dict[str, Any] = {}

        try:
            output = runner()
            # Merge output into shared_state (hub and spoke model)
            self.shared_state.update(output)
            status = "completed"
        except Exception as e:
            error_msg = str(e)
            status = "failed"
            logger.error("Agent %s failed: %s", agent_name, e)
            if self.on_agent_error:
                try:
                    self.on_agent_error(agent_key, error_msg)
                except Exception as cb_err:
                    logger.warning("on_agent_error callback failed (non-fatal): %s", cb_err)
            raise

        finally:
            elapsed_ms = int((time.time() - start_time) * 1000)
            completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

            # Record in shared_state observability trace
            step_record = {
                "agent_key": agent_key,
                "agent_name": agent_name,
                "status": status,
                "started_at": started_at,
                "completed_at": completed_at,
                "duration_ms": elapsed_ms,
                "output_preview": json.dumps(output, default=str)[:600],
                "error": error_msg,
            }
            self.shared_state["agent_log"].append(step_record)

            # Record in SQLite agent_steps table
            self._save_step_to_db(agent_key, status, output, error_msg, started_at, completed_at, elapsed_ms)

            if status == "completed" and self.on_agent_complete:
                try:
                    self.on_agent_complete(agent_key, output, elapsed_ms)
                except Exception as cb_err:
                    logger.warning("on_agent_complete callback failed (non-fatal): %s", cb_err)

    def _save_step_to_db(
        self,
        agent_key: str,
        status: str,
        output: dict,
        error: Optional[str],
        started_at: str,
        completed_at: str,
        duration_ms: int,
    ) -> None:
        """Persist step record to SQLite for observability and reasoning-trace."""
        try:
            step = AgentStep(
                agent_name=agent_key,
                status=AgentStatus.COMPLETED if status == "completed" else AgentStatus.FAILED,
                output_data=json.dumps(output, default=str)[:3000],
                raw_llm_response=json.dumps(output, default=str)[:3000],
                error=error,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )
            with self.db._connect() as conn:
                self.db._save_step(conn, self.shared_state["incident_id"], step)
        except Exception as e:
            logger.warning("Failed to save step to DB: %s", e)

    def _persist_to_db(self) -> None:
        """Save overall incident state to SQLite."""
        try:
            state_obj = IncidentState(
                incident_id=self.shared_state["incident_id"],
                incident_type=self.shared_state.get("scenario", "unknown"),
                log_source=self.shared_state.get("scenario", "log"),
                raw_logs=self.shared_state.get("raw_logs", ""),
                auto_approve=self.shared_state.get("auto_approve", False),
                metadata=self.shared_state.get("metadata", {}),
                pipeline_status=self.shared_state.get("status", "running"),
                created_at=self.shared_state.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
                postmortem=self.shared_state.get("postmortem_report"),
                status_update=self.shared_state.get("status_update"),
            )
            self.db.save_incident(state_obj)
        except Exception as e:
            logger.warning("Failed to persist incident state to DB: %s", e)
