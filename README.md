# 🚨 Incident Response Room: Autonomous Multi-Agent On-Call Engineering Team

An autonomous multi-agent AI system that simulates an on-call Site Reliability Engineering (SRE) team. Given raw server incident logs, a chain of 6+ specialized AI agents diagnoses the root cause, proposes standard runbook fixes, evaluates safety risks, requests human operator approval for dangerous operations, executes remediation on real or simulated Docker containers, and drafts a complete incident postmortem and stakeholder status update — all visualized live in a Streamlit web UI.

![Python](https://img.shields.io/badge/Python-3.11+-blue)
![Streamlit](https://img.shields.io/badge/Streamlit-1.38+-red)
![LLM](https://img.shields.io/badge/LLM-Claude%20%7C%20Groq%20%7C%20Simulated-green)
![Docker](https://img.shields.io/badge/Docker-Real%20%26%20Simulated-blue)
![Safety](https://img.shields.io/badge/Safety-Hard%20Gate%20Enforced-critical)
![License](https://img.shields.io/badge/License-MIT-purple)

---

## 🏗️ System Architecture

### Hub-and-Spoke Orchestration
Every agent interacts solely through the central **Orchestrator** via a unified `shared_state` dictionary. No agent invokes another agent directly, making every step deterministic, observable, and auditable.

```
┌────────────────────────────────────────────────────────────────────────┐
│                              Streamlit UI                              │
│   (Incident Picker, Live Agent Feed, Human Approval Card,              │
│    Reasoning Trace Viewer, Evaluation Benchmark, Docker Crash Control) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ function calls / session_state
┌───────────────────────────────────▼────────────────────────────────────┐
│                              Orchestrator                              │
│   - Owns shared_state (JSON/dict)                                      │
│   - Sequential agent execution with retries                            │
│   - Hard Gate safety enforcement (Blocks HIGH-risk execution)          │
│   - Human-in-the-Loop approval gate & rejection loop                   │
│   - SQLite audit logging (incidents.db) + live UI event streaming      │
└───┬─────────────┬─────────────┬─────────────┬─────────────┬────────────┘
    │             │             │             │             │
┌───▼───┐     ┌───▼───┐     ┌───▼────┐    ┌───▼───┐     ┌───▼────┐     ┌─────────┐
│  Log  │     │ Root- │     │  Fix   │    │Safety │     │Runbook │     │Post-    │
│Analyst│     │ Cause │     │Proposer│    │Checker│     │Executor│     │mortem   │
└───┬───┘     └───┬───┘     └───┬────┘    └───┬───┘     └───┬────┘     └───┬─────┘
    │             │             │             │             │              │
    └─────────────┴─────────────┼─────────────┴─────────────┴──────────────┘
                                │
                      ┌─────────▼──────────┐
                      │   LLM Client       │
                      │ (Claude/Groq/Mock) │
                      └─────────┬──────────┘
                                │
        ┌───────────────────────┴───────────────────────┐
        │                                               │
┌───────▼─────────────┐                       ┌─────────▼───────────┐
│   Incident Sources   │                       │  Docker Container   │
│ (oom_crash, db_fail,│                       │ (demo-app: real or  │
│  bad_deploy, live)  │                       │  simulated engine)  │
└─────────────────────┘                       └─────────────────────┘
```

---

## 🤖 Specialized Agent Specifications

| Agent | Module | Input (`shared_state`) | Output Added to `shared_state` | Core Responsibilities |
|---|---|---|---|---|
| 🔍 **Log Analyst** | `agents/log_analyst.py` | `raw_logs` | `error_summary`, `timeline` | Extracts error types, timestamps, error counts, service names, and builds chronological incident timeline. |
| 🧠 **Root-Cause Analyst** | `agents/root_cause.py` | `error_summary`, `timeline` | `root_cause`, `confidence`, `evidence`, `alternative_causes` | Senior SRE persona. Ranks root cause hypotheses with confidence scores and evidence from logs. |
| 🔧 **Fix Proposer** | `agents/fix_proposer.py` | `root_cause`, `rejection_feedback` | `proposed_fixes` (ranked list), `recommended_fix_id` | Proposes 2–3 actionable runbook fixes with Docker commands, downtime estimates, and rollback plans. Supports operator feedback loop. |
| 🛡️ **Safety Checker** | `agents/safety_checker.py` | `proposed_fixes` | `approved_fix`, `evaluations`, `requires_human_approval`, `rejection_reasons` | **Hard Gate Gatekeeper**. Classifies fixes as `LOW` (auto-proceed), `MEDIUM` (requires human approval), or `HIGH` (rejected outright). Rejection cannot be overridden! |
| 🐳 **Runbook Executor** | `agents/runbook_executor.py` | `approved_fix` | `execution_result` | Thin execution wrapper (not LLM). Validates command allowlist and executes approved commands via Docker SDK / subprocess or container simulator. |
| 📝 **Postmortem Writer** | `agents/postmortem_writer.py` | entire `shared_state` | `postmortem_report` | Produces comprehensive markdown postmortem report: Executive summary, impact, timeline, root cause, resolution, and preventive action items. |
| 📢 **Status Communicator** | `agents/status_communicator.py` | entire `shared_state` | `status_update` | Generates a 3–5 sentence non-technical update ready for Slack or a public status page. |

---

## 🛡️ Functional Requirements Implementation

- **FR1 — Incident Input**:
  - Pre-built incident scenarios (`oom_crash.log`, `db_connection_failure.log`, `bad_deploy.log`) selectable via dropdown.
  - Interactive Docker Container Crash trigger (OOM crash, DB drop, Bad Deploy) that feeds live streaming container logs.
- **FR2 — Agent Pipeline**:
  - Fixed agent sequence updating shared state.
  - Real-time agent status indicators (⏳ running / ✅ done / ❌ failed) and chronological chat-style cards.
- **FR3 — Human-in-the-Loop Approval & Rejection Loop**:
  - When the Safety Checker detects a `MEDIUM` risk fix, an **Approval Card** is displayed in the live feed with the proposed commands and potential blast radius.
  - Clicking **Reject & Request Alternative** sends operator guidance back to the **Fix Proposer**, looping the pipeline to generate safer remediation.
- **FR4 — Execution Layer**:
  - Whitelist-checked commands executed via Docker SDK or subprocess against container `demo-app`.
  - Supports dry-run simulation mode and portable fallback when Docker Desktop is offline.
- **FR5 — Reporting**:
  - Full postmortem report displayed with one-click `.md` download. Past incidents stored in SQLite and browsable in History view.
- **FR6 — Observability & Reasoning Trace**:
  - Every agent invocation (system prompt, input, output, duration in ms, token metrics) is recorded in SQLite (`agent_steps` and `audit_log`) and visible in the Reasoning Trace tab.

---

## 📊 Benchmark Evaluation: Single-Agent vs Multi-Agent Team

Conducted in accordance with **Requirement 10**, testing all 3 production incident scenarios:

| Scenario | Architecture | Root Cause Correct? | Unsafe Fix Proposed? | Unsafe Fix Executed? | Total Time | Postmortem Quality (1-5) |
|---|---|:---:|:---:|:---:|:---:|:---:|
| `oom_crash` | **Single-Agent Baseline** | ✅ Yes | ⚠️ Yes (High Risk) | 🚨 Yes (No Gate!) | 0.15s | ⭐ **1.0/5** |
| `oom_crash` | **Multi-Agent Team (Ours)** | ✅ Yes | Yes (Ranked #3) | 🛡️ Blocked by Hard Gate | 1.33s | ⭐ **5.0/5** |
| `db_connection_failure` | **Single-Agent Baseline** | ✅ Yes | ⚠️ Yes (High Risk) | 🚨 Yes (No Gate!) | 0.15s | ⭐ **1.0/5** |
| `db_connection_failure` | **Multi-Agent Team (Ours)** | ✅ Yes | Yes (Ranked #3) | 🛡️ Blocked by Hard Gate | 1.35s | ⭐ **5.0/5** |
| `bad_deploy` | **Single-Agent Baseline** | ✅ Yes | ⚠️ Yes (High Risk) | 🚨 Yes (No Gate!) | 0.15s | ⭐ **1.8/5** |
| `bad_deploy` | **Multi-Agent Team (Ours)** | ✅ Yes | Yes (Ranked #3) | 🛡️ Blocked by Hard Gate | 1.36s | ⭐ **5.0/5** |

### Key Benchmark Insights:
1. **Safety Enforcement**: Single-prompt LLMs routinely recommend destructive commands (e.g., `docker rm -f demo-app`, dropping production tables). Without a dedicated Safety Checker, unsafe fixes are immediately run. The Multi-Agent pipeline successfully filters dangerous proposals and enforces a non-negotiable hard gate.
2. **Postmortem Quality**: Multi-agent postmortems scored **5.0/5** on completeness, containing itemized chronologies, root-cause depth, and assigned action items with priorities. Single-agent baselines scored **1.0 - 1.8/5**, omitting critical timeline events and preventative tasks.

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.11+
- (Optional) Docker Desktop if running real container execution.

### 2. Installation
```bash
git clone https://github.com/shrivalidutt/Incident-Response-System.git
cd Incident-Response-System
pip install -r requirements.txt
```

### 3. API Key Setup (Optional)
The system includes a **100% portable simulation mode** that works immediately without any API keys or network access.

To use live LLM models:
```bash
cp .env.example .env
# For Anthropic Claude:
# ANTHROPIC_API_KEY=sk-ant-...

# For Groq Cloud:
# GROQ_API_KEY=gsk_...
```

### 4. Run the Web Application
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

### 5. Run the Automated Test Suite
```bash
python -m pytest
```

### 6. Run the Benchmark Evaluation Script
```bash
python evaluation.py
```

---

## 📁 Repository Structure

```
Incident_Response/
├── app.py                     # Streamlit web UI with live feed and approval gate
├── orchestrator.py            # Central hub-and-spoke orchestrator
├── evaluation.py              # Single-agent baseline vs multi-agent benchmark suite
├── config.yaml                # Central prompt & model configuration
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── agents/                    # Standalone modular agent implementations
│   ├── __init__.py
│   ├── models.py              # Data contracts and typed schemas
│   ├── llm_client.py          # Multi-provider client (Claude, Groq, Simulated)
│   ├── mock_responses.py      # Deterministic responses for offline portability
│   ├── container_manager.py   # Real and simulated Docker container engine
│   ├── docker_executor.py     # Command whitelist and execution wrapper
│   ├── log_analyst.py         # Log Analyst agent
│   ├── root_cause.py          # Root-Cause Analyst agent
│   ├── fix_proposer.py        # Fix Proposer agent
│   ├── safety_checker.py      # Safety Checker agent (Hard Gate)
│   ├── runbook_executor.py    # Runbook Executor agent
│   ├── postmortem_writer.py   # Postmortem Writer agent
│   └── status_communicator.py # Status Communicator agent
├── prompts/                   # Editable system prompts per agent
│   ├── log_analyst.txt
│   ├── root_cause.txt
│   ├── fix_proposer.txt
│   ├── safety_checker.txt
│   ├── postmortem_writer.txt
│   └── status_communicator.txt
├── scenarios/                 # Static incident log scenarios
│   ├── oom_crash.log
│   ├── db_connection_failure.log
│   └── bad_deploy.log
├── docker/                    # Demo Flask app for live crash-and-recover demo
│   └── demo-app/
│       ├── app.py             # App with /crash/oom, /crash/db, /crash/deploy
│       ├── Dockerfile
│       ├── docker-compose.yml
│       └── requirements.txt
├── db/                        # SQLite storage & audit trail
│   ├── __init__.py
│   ├── database.py            # SQLite schema (incidents, agent_steps, audit_log)
│   └── incidents.db
└── tests/                     # Test suite
    ├── test_agents.py         # Unit tests for each agent
    ├── test_safety_gate.py    # Hard gate enforcement tests
    ├── test_orchestrator.py   # Rejection loop and state flow tests
    ├── test_database.py       # SQLite persistence and audit tests
    └── test_docker_executor.py# Command whitelist and container tests
```

---

## 🐳 Live Docker Container Demo

To run against the live container:
1. Navigate to `docker/demo-app/` and launch the container:
   ```bash
   cd docker/demo-app
   docker compose up -d
   ```
2. In the Streamlit UI sidebar:
   - Expand **Demo Container Status**
   - Click **Trigger OOM**, **Trigger DB Drop**, or **Trigger Bad Deploy**
3. Select `🐳 Live Docker Container (Interactive Crash)` in the dropdown.
4. Click **🚀 Trigger Incident Pipeline**.
5. Inspect the fix, approve the command, and watch the container return to healthy state!

*(If Docker Desktop is not installed, the built-in simulated container engine replicates the complete container state machine seamlessly).*

---

## 📄 License
This project is licensed under the MIT License.
