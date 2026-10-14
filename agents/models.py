"""Data models for structured data passing between agents.

Uses dataclasses for type safety and clean serialization.
Each model corresponds to the JSON schema defined in config.yaml agent prompts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class Severity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    FATAL = "FATAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IncidentCategory(str, Enum):
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK = "network"
    DEPLOYMENT = "deployment"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    UNKNOWN = "unknown"


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Log Analyst output ────────────────────────────────────────────────

@dataclass
class TimelineEvent:
    timestamp: str
    event: str
    severity: str


@dataclass
class LogAnalysis:
    error_types: list[str]
    error_count: int
    first_error_at: str
    last_error_at: str
    timeline: list[TimelineEvent]
    affected_services: list[str]
    summary: str

    @classmethod
    def from_dict(cls, data: dict) -> LogAnalysis:
        timeline = [
            TimelineEvent(**evt) if isinstance(evt, dict) else evt
            for evt in data.get("timeline", [])
        ]
        return cls(
            error_types=data.get("error_types", []),
            error_count=data.get("error_count", 0),
            first_error_at=data.get("first_error_at", ""),
            last_error_at=data.get("last_error_at", ""),
            timeline=timeline,
            affected_services=data.get("affected_services", []),
            summary=data.get("summary", ""),
        )


# ── Root-Cause Analyst output ────────────────────────────────────────

@dataclass
class AlternativeCause:
    cause: str
    confidence: float
    why_less_likely: str


@dataclass
class RootCauseAnalysis:
    root_cause: str
    confidence: float
    evidence: list[str]
    alternative_causes: list[AlternativeCause]
    category: str

    @classmethod
    def from_dict(cls, data: dict) -> RootCauseAnalysis:
        alt_causes = [
            AlternativeCause(**ac) if isinstance(ac, dict) else ac
            for ac in data.get("alternative_causes", [])
        ]
        return cls(
            root_cause=data.get("root_cause", ""),
            confidence=data.get("confidence", 0.0),
            evidence=data.get("evidence", []),
            alternative_causes=alt_causes,
            category=data.get("category", "unknown"),
        )


# ── Fix Proposer output ──────────────────────────────────────────────

@dataclass
class ProposedFix:
    id: int
    title: str
    description: str
    commands: list[str]
    risk_level: str
    estimated_downtime: str
    rollback_plan: str


@dataclass
class FixProposal:
    proposed_fixes: list[ProposedFix]
    recommended_fix_id: int

    @classmethod
    def from_dict(cls, data: dict) -> FixProposal:
        fixes = [
            ProposedFix(**f) if isinstance(f, dict) else f
            for f in data.get("proposed_fixes", [])
        ]
        return cls(
            proposed_fixes=fixes,
            recommended_fix_id=data.get("recommended_fix_id", 1),
        )


# ── Safety Checker output ────────────────────────────────────────────

@dataclass
class SafetyEvaluation:
    fix_id: int
    risk_classification: str
    reasoning: str
    potential_impact: str
    safeguards_present: bool


@dataclass
class SafetyReport:
    evaluations: list[SafetyEvaluation]
    approved_fix_id: int
    approved_fix: Optional[dict]
    requires_human_approval: bool
    rejection_reasons: list[str]

    @classmethod
    def from_dict(cls, data: dict) -> SafetyReport:
        evals = [
            SafetyEvaluation(**e) if isinstance(e, dict) else e
            for e in data.get("evaluations", [])
        ]
        return cls(
            evaluations=evals,
            approved_fix_id=data.get("approved_fix_id", 0),
            approved_fix=data.get("approved_fix"),
            requires_human_approval=data.get("requires_human_approval", True),
            rejection_reasons=data.get("rejection_reasons", []),
        )


# ── Execution Result ─────────────────────────────────────────────────

@dataclass
class ExecutionResult:
    fix_id: int
    commands_run: list[str]
    outputs: list[str]
    success: bool
    error: Optional[str] = None
    dry_run: bool = False


# ── Agent Step Record ─────────────────────────────────────────────────

@dataclass
class AgentStep:
    """Record of a single agent's execution within the pipeline."""
    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    input_data: Optional[str] = None
    output_data: Optional[str] = None
    raw_llm_response: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None


# ── Full Incident State ──────────────────────────────────────────────

@dataclass
class IncidentState:
    """Complete state of an incident flowing through the pipeline."""
    incident_id: str = ""
    incident_type: str = ""
    log_source: str = ""
    raw_logs: str = ""
    auto_approve: bool = False
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Agent outputs (populated as the pipeline progresses)
    log_analysis: Optional[LogAnalysis] = None
    root_cause: Optional[RootCauseAnalysis] = None
    fix_proposal: Optional[FixProposal] = None
    safety_report: Optional[SafetyReport] = None
    execution_result: Optional[ExecutionResult] = None
    postmortem: Optional[str] = None
    status_update: Optional[str] = None

    # Pipeline tracking
    steps: list[AgentStep] = field(default_factory=list)
    current_step: int = 0
    pipeline_status: str = "pending"  # pending, running, completed, failed

    def to_dict(self) -> dict:
        """Serialize the full state to a dict (for JSON storage)."""
        return asdict(self)

    def to_json(self) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)
