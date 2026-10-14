"""Pipeline orchestrator — chains the 6 AI agents together.

Flow:
  Raw Logs → Log Analyst → Root-Cause Analyst → Fix Proposer
  → Safety Checker → [Execute Fix] → Postmortem Writer → Status Communicator

Each agent receives the cumulative incident state and appends its output.
Callbacks allow the UI to display real-time progress.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from uuid import uuid4

import yaml

from agents.llm_client import LLMClient, LLMError
from agents.docker_executor import DockerExecutor, DockerExecutionError
from agents.models import (
    AgentStatus,
    AgentStep,
    IncidentState,
    LogAnalysis,
    RootCauseAnalysis,
    FixProposal,
    SafetyReport,
    ExecutionResult,
)

logger = logging.getLogger("incident_response.pipeline")

# Agent execution order
AGENT_SEQUENCE = [
    "log_analyst",
    "root_cause",
    "fix_proposer",
    "safety_checker",
    "postmortem_writer",
    "status_communicator",
]


class Pipeline:
    """Orchestrates the multi-agent incident response pipeline."""

    def __init__(
        self,
        config_path: str = "config.yaml",
        dry_run: bool = True,
        on_step_start: Optional[Callable[[str, AgentStep], None]] = None,
        on_step_complete: Optional[Callable[[str, AgentStep], None]] = None,
        on_step_error: Optional[Callable[[str, AgentStep], None]] = None,
    ):
        """Initialize the pipeline.

        Args:
            config_path: Path to config.yaml.
            dry_run: If True, Docker commands are simulated.
            on_step_start: Callback(agent_name, step) when an agent starts.
            on_step_complete: Callback(agent_name, step) when an agent finishes.
            on_step_error: Callback(agent_name, step) when an agent fails.
        """
        self.config = self._load_config(config_path)
        self.dry_run = dry_run

        # Callbacks for UI integration
        self.on_step_start = on_step_start
        self.on_step_complete = on_step_complete
        self.on_step_error = on_step_error

        # Initialize LLM client from config
        llm_cfg = self.config.get("llm", {})
        retry_cfg = self.config.get("retry", {})

        # API key loaded at runtime (from env or parameter)
        self._api_key: Optional[str] = None
        self._llm: Optional[LLMClient] = None

        self.model = llm_cfg.get("model", "claude-sonnet-4-20250514")
        self.max_tokens = llm_cfg.get("max_tokens", 2048)
        self.temperature = llm_cfg.get("temperature", 0.3)
        self.max_retries = retry_cfg.get("max_attempts", 2)
        self.backoff = retry_cfg.get("backoff_seconds", 2)

        # Docker executor
        self.docker_executor = DockerExecutor(dry_run=dry_run)

    def _load_config(self, config_path: str) -> dict:
        """Load and validate config.yaml."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Validate that all required agents are configured
        agents = config.get("agents", {})
        for agent_name in AGENT_SEQUENCE:
            if agent_name not in agents:
                raise ValueError(
                    f"Missing agent config for '{agent_name}' in {config_path}"
                )
            if "prompt" not in agents[agent_name]:
                raise ValueError(
                    f"Missing 'prompt' for agent '{agent_name}' in {config_path}"
                )

        logger.info("Config loaded: %d agents configured", len(agents))
        return config

    def set_api_key(self, api_key: str, provider: str = "auto") -> None:
        """Set the LLM API key and optional provider (call before run())."""
        self._api_key = api_key
        self._llm = LLMClient(
            api_key=api_key,
            provider=provider,
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            max_retries=self.max_retries,
            backoff_seconds=self.backoff,
        )

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient(
                api_key=self._api_key,
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                max_retries=self.max_retries,
                backoff_seconds=self.backoff,
            )
        return self._llm

    def run(
        self,
        log_source: str,
        incident_type: str = "",
        auto_approve: bool = False,
        metadata: Optional[dict] = None,
        human_approval_callback: Optional[Callable[[SafetyReport], bool]] = None,
    ) -> IncidentState:
        """Execute the full incident response pipeline.

        Args:
            log_source: Path to the log file to analyze.
            incident_type: e.g. "oom_crash", "db_connection_failure".
            auto_approve: Skip human approval for MEDIUM risk fixes.
            metadata: Additional incident metadata.
            human_approval_callback: Called when a MEDIUM-risk fix needs approval.
                                    Returns True to approve, False to skip execution.

        Returns:
            Complete IncidentState with all agent outputs.
        """
        # Initialize incident state
        raw_logs = self._read_logs(log_source)

        state = IncidentState(
            incident_id=str(uuid4())[:8],
            incident_type=incident_type,
            log_source=log_source,
            raw_logs=raw_logs,
            auto_approve=auto_approve,
            metadata=metadata or {},
        )

        # Pre-create steps for all agents
        state.steps = [
            AgentStep(agent_name=name) for name in AGENT_SEQUENCE
        ]
        state.pipeline_status = "running"

        logger.info(
            "Pipeline started — incident_id=%s, type=%s, log_lines=%d",
            state.incident_id,
            incident_type,
            raw_logs.count("\n") + 1,
        )

        try:
            # Step 1: Log Analyst
            state.log_analysis = self._run_agent(
                state, 0, "log_analyst", raw_logs, LogAnalysis.from_dict
            )

            # Step 2: Root-Cause Analyst
            rca_input = json.dumps(asdict(state.log_analysis), indent=2, default=str)
            state.root_cause = self._run_agent(
                state, 1, "root_cause", rca_input, RootCauseAnalysis.from_dict
            )

            # Step 3: Fix Proposer
            fix_input = json.dumps(
                {
                    "log_analysis": asdict(state.log_analysis),
                    "root_cause": asdict(state.root_cause),
                },
                indent=2,
                default=str,
            )
            state.fix_proposal = self._run_agent(
                state, 2, "fix_proposer", fix_input, FixProposal.from_dict
            )

            # Step 4: Safety Checker
            safety_input = json.dumps(
                asdict(state.fix_proposal), indent=2, default=str
            )
            state.safety_report = self._run_agent(
                state, 3, "safety_checker", safety_input, SafetyReport.from_dict
            )

            # Step 4.5: Execute the approved fix (if any)
            state.execution_result = self._execute_approved_fix(
                state, auto_approve, human_approval_callback
            )

            # Step 5: Postmortem Writer
            postmortem_input = json.dumps(
                {
                    "log_analysis": asdict(state.log_analysis),
                    "root_cause": asdict(state.root_cause),
                    "fix_applied": asdict(state.execution_result) if state.execution_result else None,
                    "safety_report": asdict(state.safety_report),
                },
                indent=2,
                default=str,
            )
            state.postmortem = self._run_agent(
                state, 4, "postmortem_writer", postmortem_input, parse_json=False
            )

            # Step 6: Status Communicator
            comms_input = json.dumps(
                {
                    "incident_type": state.incident_type,
                    "summary": state.log_analysis.summary,
                    "root_cause": state.root_cause.root_cause,
                    "fix_applied": asdict(state.execution_result) if state.execution_result else None,
                    "postmortem_excerpt": (state.postmortem or "")[:500],
                },
                indent=2,
                default=str,
            )
            state.status_update = self._run_agent(
                state, 5, "status_communicator", comms_input, parse_json=False
            )

            state.pipeline_status = "completed"
            logger.info(
                "Pipeline completed — incident_id=%s, steps=%d",
                state.incident_id,
                len(state.steps),
            )

        except Exception as e:
            state.pipeline_status = "failed"
            logger.error("Pipeline failed: %s", e)
            raise

        return state

    def _run_agent(
        self,
        state: IncidentState,
        step_index: int,
        agent_name: str,
        user_input: str,
        parser: Optional[Callable[[dict], Any]] = None,
        parse_json: bool = True,
    ) -> Any:
        """Run a single agent and update the step record.

        Args:
            state: Current incident state.
            step_index: Index into state.steps.
            agent_name: Key in config.yaml agents section.
            user_input: The text to send as the user message.
            parser: Optional from_dict() method to parse the JSON response.
            parse_json: Whether to parse the response as JSON.

        Returns:
            Parsed model object, raw dict, or raw string depending on args.
        """
        step = state.steps[step_index]
        step.status = AgentStatus.RUNNING
        step.started_at = datetime.utcnow().isoformat() + "Z"
        step.input_data = user_input[:2000]  # Truncate for storage
        state.current_step = step_index

        agent_config = self.config["agents"][agent_name]
        display_name = agent_config.get("name", agent_name)
        emoji = agent_config.get("emoji", "🤖")
        system_prompt = agent_config["prompt"]

        logger.info("%s %s starting...", emoji, display_name)

        if self.on_step_start:
            self.on_step_start(agent_name, step)

        start_time = time.time()

        try:
            response = self.llm.call(
                system_prompt=system_prompt,
                user_message=user_input,
                parse_json=parse_json,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            step.status = AgentStatus.COMPLETED
            step.completed_at = datetime.utcnow().isoformat() + "Z"
            step.duration_ms = elapsed_ms

            if parse_json and parser:
                step.output_data = json.dumps(response, indent=2, default=str)[:2000]
                step.raw_llm_response = json.dumps(response, default=str)[:2000]
                result = parser(response)
            elif parse_json:
                step.output_data = json.dumps(response, indent=2, default=str)[:2000]
                result = response
            else:
                step.output_data = str(response)[:2000]
                step.raw_llm_response = str(response)[:2000]
                result = response

            logger.info(
                "%s %s completed in %dms",
                emoji,
                display_name,
                elapsed_ms,
            )

            if self.on_step_complete:
                self.on_step_complete(agent_name, step)

            return result

        except (LLMError, Exception) as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            step.status = AgentStatus.FAILED
            step.error = str(e)
            step.completed_at = datetime.utcnow().isoformat() + "Z"
            step.duration_ms = elapsed_ms

            logger.error("%s %s failed: %s", emoji, display_name, e)

            if self.on_step_error:
                self.on_step_error(agent_name, step)

            raise

    def _execute_approved_fix(
        self,
        state: IncidentState,
        auto_approve: bool,
        human_approval_callback: Optional[Callable[[SafetyReport], bool]],
    ) -> Optional[ExecutionResult]:
        """Execute the approved fix from the safety report.

        Handles human approval flow for MEDIUM-risk fixes.
        """
        safety = state.safety_report
        if safety is None or safety.approved_fix is None:
            logger.warning("No approved fix to execute")
            return None

        # Check if human approval is needed
        if safety.requires_human_approval and not auto_approve:
            if human_approval_callback:
                approved = human_approval_callback(safety)
                if not approved:
                    logger.info("Human rejected the fix — skipping execution")
                    return ExecutionResult(
                        fix_id=safety.approved_fix_id,
                        commands_run=[],
                        outputs=["Execution skipped — human rejected the fix"],
                        success=False,
                        error="Human rejected",
                        dry_run=self.dry_run,
                    )
            else:
                logger.info(
                    "MEDIUM-risk fix requires human approval but no callback provided — skipping"
                )
                return ExecutionResult(
                    fix_id=safety.approved_fix_id,
                    commands_run=[],
                    outputs=["Execution skipped — human approval required"],
                    success=False,
                    error="Human approval required",
                    dry_run=self.dry_run,
                )

        logger.info(
            "Executing approved fix #%d (dry_run=%s)",
            safety.approved_fix_id,
            self.dry_run,
        )

        try:
            result = self.docker_executor.execute_fix(safety.approved_fix)
            return result
        except DockerExecutionError as e:
            logger.error("Fix execution failed: %s", e)
            return ExecutionResult(
                fix_id=safety.approved_fix_id,
                commands_run=[],
                outputs=[str(e)],
                success=False,
                error=str(e),
                dry_run=self.dry_run,
            )

    def _read_logs(self, log_source: str) -> str:
        """Read raw logs from a file path."""
        path = Path(log_source)
        if not path.exists():
            raise FileNotFoundError(f"Log file not found: {log_source}")

        content = path.read_text(encoding="utf-8")
        logger.debug("Read %d bytes from %s", len(content), log_source)
        return content

    def get_agent_info(self, agent_name: str) -> dict:
        """Get display info for an agent (name, emoji, color)."""
        agent_cfg = self.config.get("agents", {}).get(agent_name, {})
        return {
            "name": agent_cfg.get("name", agent_name),
            "emoji": agent_cfg.get("emoji", "🤖"),
            "color": agent_cfg.get("color", "#FFFFFF"),
        }
