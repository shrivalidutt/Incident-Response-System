# System Design Document: Incident Response Room

## 1. System Overview & Architecture Diagram

The **Incident Response Room** utilizes a centralized **Hub-and-Spoke (Orchestrator-Worker)** coordination architecture. All specialized agents communicate exclusively through a shared immutable-by-convention blackboard state dictionary owned and audited by the central Orchestrator. No agent invokes another agent directly, which prevents uncontrolled recursion, ensures strict state isolation, and enables sub-millisecond audit tracing to SQLite.

### 1.1 Architecture & Inter-Agent Communication Diagram

```
                               ┌───────────────────────────────────────────────────────────┐
                               │                    Streamlit Web UI                       │
                               │  - Scenario Selector & Live Container Crash Trigger       │
                               │  - Real-Time Streaming Agent Feed & Status Cards          │
                               │  - Human-in-the-Loop Approval & Rejection Feedback Form   │
                               │  - Observability Trace Viewer & Evaluation Benchmark Tab  │
                               └─────────────────────────────┬─────────────────────────────┘
                                                             │ UI Events & Session State
                               ┌─────────────────────────────▼─────────────────────────────┐
                               │               Hub-and-Spoke Orchestrator                  │
                               │  - State Management (`shared_state` blackboard)           │
                               │  - Dynamic / Adaptive Execution Flow                      │
                               │  - Non-Negotiable Safety Hard Gate                        │
                               │  - Human-in-the-Loop Gate & Re-planning Loop              │
                               │  - SQLite Audit Logging (`incidents.db`)                  │
                               └─────────────────────────────┬─────────────────────────────┘
                                                             │
               ┌──────────────────────┬──────────────────────┼──────────────────────┬──────────────────────┐
               │ (Handoff 1)          │ (Handoff 2)          │ (Handoff 3)          │ (Handoff 4)          │ (Handoff 5)
               ▼                      ▼                      ▼                      ▼                      ▼
        ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐
        │ 🔍 Log       │       │ 🧠 Root-Cause│       │ 🔧 Fix       │◀────┐ │ 🛡️ Safety    │       │ 🐳 Runbook   │
        │    Analyst   │       │    Analyst   │       │    Proposer  │     │ │    Checker   │       │    Executor  │
        └──────┬───────┘       └──────┬───────┘       └──────┬───────┘     │ └──────┬───────┘       └──────┬───────┘
               │                      │                      │             │        │                      │
               │ error_summary        │ root_cause           │ fixes       │        │ approved_fix         │ execution_result
               │ timeline             │ confidence           │ ranked_ids  │        │ (or HIGH rejection)  │ stdout / stderr
               ▼                      ▼                      ▼             │        ▼                      ▼
        ┌──────────────────────────────────────────────────────────────────┴───────────────────────────────────────┐
        │                                  Shared Cumulative Incident State                                        │
        └──────────────────────────────────────────────────┬───────────────────────────────────────────────────────┘
                                                           │
                                  ┌────────────────────────┴────────────────────────┐
                                  │ (Handoff 6)                                     │ (Handoff 7)
                                  ▼                                                 ▼
                           ┌──────────────┐                                  ┌──────────────┐
                           │ 📝 Postmortem│                                  │ 📢 Status    │
                           │    Writer    │                                  │  Communicator│
                           └──────────────┘                                  └──────────────┘
```

---

## 2. Specialized Agent Roles & Responsibilities

The system consists of seven clearly delineated agents, fulfilling the CA3 requirement of $\ge 4$ distinct agents:

| # | Agent Name | Persona & Role | Input Schema (`shared_state`) | Output Schema (`shared_state`) | Core Responsibilities & Reasoning |
|---|---|---|---|---|---|
| 1 | **Log Analyst** | Senior Observability Engineer | `raw_logs` (string) | `error_summary` (dict), `timeline` (list) | Ingests unformatted log streams; clusters error types; identifies affected microservices; extracts chronological timeline with severity tags. |
| 2 | **Root-Cause Analyst** | Senior SRE Diagnostician | `error_summary`, `timeline` | `root_cause` (string), `confidence` (float), `evidence` (list), `alternative_causes` (list) | Correlates error spikes with system state; eliminates red herrings; isolates primary root cause with calibrated confidence and empirical log evidence. |
| 3 | **Fix Proposer** | Site Reliability Engineer | `root_cause`, `error_summary`, `rejection_feedback` (optional) | `proposed_fixes` (list of 2-3 ranked fixes), `recommended_fix_id` (int) | Synthesizes standard runbook remediation actions; generates executable container commands; provides estimated downtime and rollback procedures. Supports iterative re-planning upon rejection. |
| 4 | **Safety Checker** | Adversarial Security & Governance Auditor | `proposed_fixes` (list) | `approved_fix` (dict), `evaluations` (list), `requires_human_approval` (bool), `rejection_reasons` (list) | **Hard Gate Gatekeeper**. Evaluates blast radius and classifies fixes as LOW (auto-run), MEDIUM (human approval required), or HIGH (rejected outright). Rejection cannot be bypassed. |
| 5 | **Runbook Executor** | Deterministic Execution Agent | `approved_fix`, `safety_report` | `execution_result` (dict: status, commands, outputs, latency) | Strictly validates commands against regex allowlist; executes commands via Docker SDK / subprocess or fallback container simulator; reports execution stdout/stderr. |
| 6 | **Postmortem Writer** | Principal Technical Writer | Entire cumulative `shared_state` | `postmortem_report` (markdown string) | Drafts formal SRE retrospective containing Executive Summary, Impact Metrics, Incident Chronology, Root Cause, Remediation Verification, and Action Items. |
| 7 | **Status Communicator** | Public Incident Communications Lead | Entire cumulative `shared_state` | `status_update` (string) | Synthesizes complex technical telemetry into concise 3-5 sentence non-technical updates suitable for Slack, Statuspage, or executive stakeholders. |

---

## 3. Orchestration Pattern & Justification

### 3.1 Pattern: Centralized Hub-and-Spoke (Orchestrator-Worker)
The system rejects unconstrained peer-to-peer agent mesh networking in favor of a centralized Hub-and-Spoke model.

### 3.2 Architectural Justification
1. **Deterministic Safety Enforcement**: In production incident response, an unconstrained agent mesh risks infinite loops or unauthorized command execution. A centralized Orchestrator guarantees that the Safety Checker's Hard Gate is checked before the execution agent ever touches the host.
2. **Complete Observability & Auditability**: Every state modification, agent prompt, latency measurement, and LLM output flows through the Orchestrator and is immediately committed to SQLite (`incidents.db`). This produces an immutable audit trail for compliance and post-incident review.
3. **Adaptive Feedback & Re-planning Loops**: When an operator (or safety gate) rejects a proposed remediation, the Orchestrator manages the feedback loop back to the Fix Proposer with contextual guidance, enabling genuine agentic negotiation without losing state history.

---

## 4. Agentic Architecture vs. Simple Automation (Section 1.2 Compliance)

To satisfy Section 1.2 of the CA3 guidelines ("The Distinction That Matters Most"):

1. **Adaptive Step Transitions**: The pipeline's path is not static. If the Safety Checker evaluates a fix as `LOW` risk, the system executes automatically. If classified as `MEDIUM`, it dynamically branches to pause and request human verification. If classified as `HIGH`, it executes a non-bypassable hard halt and invokes iterative re-planning.
2. **LLM-Driven Reasoning**: Each agent formulates its own reasoning context. The Root-Cause Analyst actively weighs alternative hypotheses (e.g., distinguishing application OOM from network saturation); the Safety Checker independently reasons about blast radius and data loss.
3. **Re-planning on Failure**: When a proposed fix is rejected by human oversight or safety constraints, the system does not crash or exit. Instead, the Fix Proposer ingests the rejection feedback, reasons over the critique, and generates alternative remediation paths.
4. **Tool Use & Verification**: The Runbook Executor employs Docker SDK tools, running health check validations post-execution. The Log Analyst employs regex clustering and timestamp extraction tools.

---

## 5. Technology & Framework Choices with Justification

| Technology | Selection | Justification |
|---|---|---|
| **Language** | Python 3.11+ | Industry standard for AI agent development, rich ecosystem of LLM client SDKs, typing support, and native Docker libraries. |
| **Orchestration Framework** | Native Python Hub-and-Spoke | Avoids the black-box abstraction and opaque prompt leakage common in heavy frameworks (e.g., CrewAI, LangChain). Provides full transparency, zero runtime overhead, and explicit state validation. |
| **LLM Inference** | Multi-Provider (Anthropic Claude, Groq Cloud, Offline Mock) | Seamlessly switches between Claude 3.5 Sonnet (for complex reasoning), Groq LLaMA 3.3 70B (for sub-second latency), and offline deterministic mock (for zero-cost, portable grading and demonstrations). |
| **Observability Database** | SQLite 3 (`incidents.db`) | Zero-configuration, ACID-compliant local database storing structured event logs, agent step durations, and full incident state histories. |
| **User Interface** | Streamlit | Rapid interactive web dashboard featuring live streaming updates, collapsible reasoning traces, container crash injection, and instant markdown downloads. |
| **Execution Layer** | Docker SDK & Subprocess with Fallback Engine | Direct integration with container runtimes for authentic incident remediation, paired with a container simulator ensuring full reproducibility even without Docker Desktop. |
