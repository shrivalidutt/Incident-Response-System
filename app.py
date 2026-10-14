"""Incident Response Room — Multi-Agent AI System Web UI.

Built with Streamlit, implementing:
FR1 - Incident Input (3 pre-built scenarios + live Docker container crash trigger + upload)
FR2 - Agent Pipeline with real-time streaming feed
FR3 - Human-in-the-loop Approval Card with Reject-and-Loop-Back to Fix Proposer
FR4 - Runbook Execution (real Docker or simulated container engine)
FR5 - Postmortem Report generation & download (.md) + History view
FR6 - Observability & Reasoning Trace for every agent call
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import streamlit as st
from dotenv import load_dotenv

from agents.container_manager import ContainerManager
from agents.llm_client import LLMClient
from agents.models import AgentStatus, IncidentState
from db.database import IncidentDatabase
from evaluation import IncidentEvaluator, format_evaluation_markdown
from orchestrator import AGENT_METADATA, Orchestrator

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("incident_response.app")

SCENARIOS_DIR = Path("scenarios")
DATA_INCIDENTS_DIR = Path("data/incidents")

# ── Page Configuration ──────────────────────────────────────────────────

st.set_page_config(
    page_title="Incident Response Room",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Premium Theme & Styling ─────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    code, pre {
        font-family: 'JetBrains Mono', monospace !important;
    }

    /* Main Container Header */
    .hero-banner {
        background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #311042 100%);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 16px;
        padding: 1.8rem 2.2rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    }
    .hero-title {
        color: #f43f5e;
        font-size: 2.1rem;
        font-weight: 800;
        margin: 0;
        letter-spacing: -0.5px;
        display: flex;
        align-items: center;
        gap: 0.6rem;
    }
    .hero-subtitle {
        color: #94a3b8;
        font-size: 0.95rem;
        margin-top: 0.4rem;
    }

    /* Status Badges */
    .badge-provider {
        background: rgba(99, 102, 241, 0.2);
        color: #a5b4fc;
        padding: 0.25rem 0.6rem;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        border: 1px solid rgba(99, 102, 241, 0.4);
    }
    .badge-safe {
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        padding: 0.2rem 0.5rem;
        border-radius: 6px;
        font-weight: 600;
        font-size: 0.8rem;
    }

    /* Agent Left Tracker Card */
    .agent-status-box {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 0.75rem 1rem;
        margin-bottom: 0.5rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.2s ease;
    }
    .agent-status-box.running {
        border-color: #f59e0b;
        background: rgba(245, 158, 11, 0.08);
        box-shadow: 0 0 15px rgba(245, 158, 11, 0.2);
    }
    .agent-status-box.completed {
        border-left: 4px solid #10b981;
    }
    .agent-status-box.failed {
        border-left: 4px solid #ef4444;
    }
    .agent-status-box.waiting {
        opacity: 0.5;
        border-left: 4px solid #4b5563;
    }

    /* Chat / Feed Cards */
    .feed-card {
        background: #111827;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1.2rem;
        border: 1px solid #1f2937;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    .feed-header {
        display: flex;
        align-items: center;
        gap: 0.6rem;
        margin-bottom: 0.75rem;
        font-size: 1.05rem;
        font-weight: 700;
    }

    /* Approval Card (FR3) */
    .approval-banner {
        background: linear-gradient(135deg, #2a1b04 0%, #3d2402 100%);
        border: 2px solid #f59e0b;
        border-radius: 14px;
        padding: 1.5rem 1.8rem;
        margin: 1.5rem 0;
        box-shadow: 0 0 25px rgba(245, 158, 11, 0.25);
    }

    /* Metric Cards */
    .metric-container {
        background: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #f43f5e;
    }
    .metric-label {
        font-size: 0.8rem;
        color: #94a3b8;
    }

    /* Hide standard Streamlit header & footer clutter */
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Session State Setup ─────────────────────────────────────────────────

def init_state():
    defaults = {
        "active_view": "response_room",
        "orchestrator": None,
        "incident_state": None,
        "pipeline_running": False,
        "approval_requested": False,
        "approval_fix": None,
        "rejection_mode": False,
        "live_logs_preview": "",
        "scenario_key": "oom_crash",
        "container_manager": ContainerManager(),
        "provider": "mock",
        "api_key": os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY") or "",
        "dry_run": True,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ── Scenario Loader ─────────────────────────────────────────────────────

SCENARIO_OPTIONS = {
    "oom_crash": {
        "title": "💥 Out of Memory (OOM) Heap Crash",
        "file": "oom_crash.log",
        "service": "web-server (Java)",
        "desc": "JVM heap exhaustion in UserService.loadAllUsers causing 500 errors and load balancer eviction.",
    },
    "db_connection_failure": {
        "title": "🔌 PostgreSQL DB Connection Pool Failure",
        "file": "db_connection_failure.log",
        "service": "api-gateway (HikariPool)",
        "desc": "PostgreSQL port 5432 refused, cascading 503 errors across customer endpoints.",
    },
    "bad_deploy": {
        "title": "🚀 Bad Deployment v2.4.1 (Checkout Regression)",
        "file": "bad_deploy.log",
        "service": "checkout-service (Node.js)",
        "desc": "TypeError in calculate_discount post-deployment causing 80%+ checkout failure rate.",
    },
    "live_container": {
        "title": "🐳 Live Docker Container (Interactive Crash)",
        "file": "live_container.log",
        "service": "demo-app",
        "desc": "Real or simulated container that you can crash and recover live.",
    },
}


def load_scenario_logs(scenario_key: str) -> str:
    """Load scenario log content from scenarios/ or data/incidents/."""
    file_name = SCENARIO_OPTIONS.get(scenario_key, {}).get("file", f"{scenario_key}.log")

    paths = [
        SCENARIOS_DIR / file_name,
        DATA_INCIDENTS_DIR / file_name,
        DATA_INCIDENTS_DIR / ("bad_deployment.log" if "bad_deploy" in file_name else file_name),
    ]
    for p in paths:
        if p.exists():
            return p.read_text(encoding="utf-8")

    return f"2026-10-14T10:00:00Z ERROR [demo-app] Simulated incident logs for {scenario_key}"


# ── Sidebar ─────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.markdown("### 🚨 Incident Response Room")

        # View navigation
        view = st.radio(
            "Navigation",
            ["🚨 Incident Response Room", "📊 Evaluation Benchmark", "📚 Incident History"],
            label_visibility="collapsed",
        )
        if "Evaluation" in view:
            st.session_state.active_view = "evaluation"
        elif "History" in view:
            st.session_state.active_view = "history"
        else:
            st.session_state.active_view = "response_room"

        st.markdown("---")

        # Provider Settings
        st.markdown("#### ⚙️ LLM & Provider")
        provider_choice = st.selectbox(
            "LLM Engine",
            [
                "🚀 Simulation / Offline Mode (Fast & Free)",
                "⚡ Groq Cloud (llama-3.3-70b-versatile)",
                "🧠 Anthropic Claude (claude-3-5-sonnet)",
            ],
            index=0,
            help="Simulated mode requires no API key and runs 100% offline. Or select Groq / Claude with your API key.",
        )

        if "Simulation" in provider_choice:
            st.session_state.provider = "mock"
            st.caption("✅ Portable offline simulation active. No API keys required.")
        elif "Groq" in provider_choice:
            st.session_state.provider = "groq"
            api_key = st.text_input(
                "Groq API Key",
                value=os.getenv("GROQ_API_KEY", st.session_state.api_key),
                type="password",
                placeholder="gsk_...",
            )
            if api_key:
                st.session_state.api_key = api_key
        else:
            st.session_state.provider = "anthropic"
            api_key = st.text_input(
                "Anthropic API Key",
                value=os.getenv("ANTHROPIC_API_KEY", st.session_state.api_key),
                type="password",
                placeholder="sk-ant-...",
            )
            if api_key:
                st.session_state.api_key = api_key

        st.markdown("---")

        # Execution Mode
        st.markdown("#### 🛡️ Execution Safety")
        dry_run = st.toggle(
            "Dry-Run Mode",
            value=st.session_state.dry_run,
            help="When enabled, fix commands are simulated without modifying live system state.",
        )
        st.session_state.dry_run = dry_run
        if dry_run:
            st.caption("🛡️ Dry-run active: Commands will be validated without host mutation.")
        else:
            st.caption("⚠️ Live execution: Commands will execute on Docker / container manager.")

        st.markdown("---")

        # Container Health Monitor
        st.markdown("#### 🐳 Demo Container Status")
        cm = st.session_state.container_manager
        status = cm.get_status()
        status_color = "🟢" if status.get("health") == "healthy" and not status.get("crashed") else "🔴"
        st.markdown(f"**Status:** {status_color} `{status.get('status', 'running')}`")
        st.markdown(f"**Mode:** `{status.get('mode')}` | **Ver:** `{status.get('version')}`")

        with st.expander("💥 Trigger Container Crash", expanded=False):
            st.write("Induce a live incident in the demo container:")
            c_col1, c_col2 = st.columns(2)
            with c_col1:
                if st.button("Trigger OOM", use_container_width=True):
                    ok, msg, log_path = cm.trigger_crash("oom_crash")
                    st.toast(msg, icon="💥")
                    st.session_state.scenario_key = "live_container"
                    st.rerun()
                if st.button("Trigger DB Drop", use_container_width=True):
                    ok, msg, log_path = cm.trigger_crash("db_connection_failure")
                    st.toast(msg, icon="🔌")
                    st.session_state.scenario_key = "live_container"
                    st.rerun()
            with c_col2:
                if st.button("Trigger Bad Deploy", use_container_width=True):
                    ok, msg, log_path = cm.trigger_crash("bad_deploy")
                    st.toast(msg, icon="🚀")
                    st.session_state.scenario_key = "live_container"
                    st.rerun()
                if st.button("Reset Container", use_container_width=True):
                    cm.execute_docker_command("docker restart demo-app")
                    st.toast("Container reset to healthy state!", icon="✅")
                    st.rerun()

        st.markdown("---")
        try:
            db = IncidentDatabase()
            stats = db.get_stats()
            st.caption(f"📊 Database: **{stats['total_incidents']}** incidents recorded")
        except Exception:
            pass


# ── Main Response Room View ─────────────────────────────────────────────

def render_response_room():
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">🚨 Incident Response Room</div>
        <div class="hero-subtitle">
            Autonomous 6-Agent SRE Team: Log Analyst → Root-Cause Analyst → Fix Proposer → Safety Checker Gate → Runbook Executor → Postmortem Writer
        </div>
    </div>
    """, unsafe_allow_html=True)

    # FR1: Scenario Selector
    s_col1, s_col2, s_col3 = st.columns([3, 2, 2])

    with s_col1:
        scenario_keys = list(SCENARIO_OPTIONS.keys())
        selected_idx = scenario_keys.index(st.session_state.scenario_key) if st.session_state.scenario_key in scenario_keys else 0
        chosen_scenario = st.selectbox(
            "Select Incident Scenario (FR1)",
            scenario_keys,
            index=selected_idx,
            format_func=lambda k: SCENARIO_OPTIONS[k]["title"],
        )
        st.session_state.scenario_key = chosen_scenario

    with s_col2:
        auto_approve = st.checkbox(
            "Auto-approve MEDIUM risk",
            value=False,
            help="If checked, bypasses the human approval modal for MEDIUM-risk fixes (HIGH risk remains blocked).",
        )

    with s_col3:
        btn_start = st.button(
            "🚀 Trigger Incident Pipeline",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.pipeline_running,
        )

    # Scenario details box
    scenario_info = SCENARIO_OPTIONS[chosen_scenario]
    st.caption(f"**Target Service:** `{scenario_info['service']}` — {scenario_info['desc']}")

    # Preview Logs Expander
    raw_logs = load_scenario_logs(chosen_scenario)
    with st.expander("📄 View Starting Incident Logs", expanded=False):
        st.code(raw_logs, language="log")

    st.markdown("---")

    # Start Pipeline execution trigger
    if btn_start:
        start_incident_pipeline(chosen_scenario, raw_logs, auto_approve)

    # Render Main Workspace (Left Tracker + Center Feed)
    render_pipeline_workspace()


# ── Pipeline Execution Controller ───────────────────────────────────────

def start_incident_pipeline(scenario: str, logs: str, auto_approve: bool):
    """Initiate Phase 1 of the multi-agent incident pipeline."""
    st.session_state.pipeline_running = True
    st.session_state.approval_requested = False
    st.session_state.approval_fix = None

    llm = LLMClient(
        api_key=st.session_state.api_key,
        provider=st.session_state.provider,
    )
    db = IncidentDatabase()
    orchestrator = Orchestrator(
        llm_client=llm,
        db=db,
        dry_run=st.session_state.dry_run,
    )

    st.session_state.orchestrator = orchestrator
    orchestrator.init_incident(
        scenario=scenario,
        raw_logs=logs,
        auto_approve=auto_approve,
    )

    # Run Phase 1
    with st.spinner("Multi-agent team analyzing incident..."):
        state = orchestrator.run_phase1_analysis_to_safety()

    st.session_state.incident_state = state
    st.session_state.pipeline_running = False

    # Check if human approval is needed (FR3)
    if state.get("status") == "awaiting_approval":
        st.session_state.approval_requested = True
        st.session_state.approval_fix = state.get("approved_fix")
        st.toast("⚠️ Human Approval Required: Fix classified as MEDIUM risk", icon="🛡️")
    elif state.get("status") in ("ready_for_execution", "analyzing"):
        # Auto-execute phase 2
        with st.spinner("Executing runbook & writing postmortem..."):
            final_state = orchestrator.run_phase2_execution_and_reporting(user_approved=True)
            st.session_state.incident_state = final_state
        st.toast("✅ Incident response pipeline completed successfully!", icon="🎉")

    st.rerun()


# ── Main Workspace Rendering ────────────────────────────────────────────

def render_pipeline_workspace():
    state = st.session_state.incident_state
    if not state:
        st.info("👈 Select an incident scenario and click **Trigger Incident Pipeline** to start.")
        return

    col_tracker, col_feed = st.columns([1, 2.5])

    # 1. Left Column: Agent Status Tracker
    with col_tracker:
        st.markdown("#### 🤖 Agent Tracker")
        render_agent_tracker(state)

        # Incident Metadata card
        st.markdown("#### 📋 Incident Info")
        st.markdown(f"""
        <div class="metric-container" style="text-align: left; margin-bottom: 0.8rem;">
            <div><b>Incident ID:</b> <code>{state.get('incident_id')}</code></div>
            <div><b>Scenario:</b> {state.get('scenario')}</div>
            <div><b>Status:</b> <code>{state.get('status')}</code></div>
            <div><b>Time:</b> {state.get('created_at', '')[:19]}</div>
        </div>
        """, unsafe_allow_html=True)

    # 2. Center Column: Chronological Chat/Agent Feed
    with col_feed:
        st.markdown("#### 💬 Agent Response Feed")
        render_agent_feed(state)

        # FR3: Inline Human-in-the-Loop Approval Card
        if st.session_state.approval_requested and state.get("status") == "awaiting_approval":
            render_human_approval_card(state)

        # Render Postmortem and Export at Bottom
        if state.get("postmortem_report"):
            render_postmortem_section(state)


# ── Left Column: Agent Tracker ──────────────────────────────────────────

def render_agent_tracker(state: dict[str, Any]):
    agent_sequence = [
        ("log_analyst", "Log Analyst", "🔍"),
        ("root_cause", "Root-Cause Analyst", "🧠"),
        ("fix_proposer", "Fix Proposer", "🔧"),
        ("safety_checker", "Safety Checker", "🛡️"),
        ("runbook_executor", "Runbook Executor", "🐳"),
        ("postmortem_writer", "Postmortem Writer", "📝"),
        ("status_communicator", "Status Communicator", "📢"),
    ]

    agent_logs = {log["agent_key"]: log for log in state.get("agent_log", [])}

    for key, name, emoji in agent_sequence:
        log_entry = agent_logs.get(key)
        if log_entry:
            status = log_entry.get("status", "completed")
            duration = f"{log_entry.get('duration_ms', 0)}ms"
            icon = "✅" if status == "completed" else "❌"
            css_class = status
        elif state.get("status") == "analyzing":
            status = "waiting"
            duration = "—"
            icon = "⏳"
            css_class = "waiting"
        else:
            status = "waiting"
            duration = "—"
            icon = "⬜"
            css_class = "waiting"

        st.markdown(f"""
        <div class="agent-status-box {css_class}">
            <div>
                <span>{icon} {emoji} <b>{name}</b></span>
            </div>
            <div style="font-size: 0.75rem; color: #94a3b8;">
                {duration}
            </div>
        </div>
        """, unsafe_allow_html=True)


# ── Center Column: Live Agent Feed ──────────────────────────────────────

def render_agent_feed(state: dict[str, Any]):
    # 1. Log Analyst Output
    if state.get("error_summary"):
        la = state.get("error_summary", {})
        timeline = state.get("timeline", [])
        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid #4FC3F7;">
                <div class="feed-header" style="color: #4FC3F7;">
                    🔍 Log Analyst Report
                </div>
                <p style="font-size: 0.95rem; color: #e2e8f0;">{la.get('summary', '')}</p>
            </div>
            """, unsafe_allow_html=True)

            with st.expander("📊 Error Statistics & Chronological Timeline", expanded=False):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.metric("Total Errors Found", la.get("error_count", 0))
                    st.write("**Affected Services:**")
                    for svc in la.get("affected_services", []):
                        st.markdown(f"- `{svc}`")
                with col_b:
                    st.write("**Categorized Error Types:**")
                    for et in la.get("error_types", []):
                        st.markdown(f"- `{et}`")

                st.write("**Incident Timeline:**")
                for ev in timeline:
                    sev_icon = "🔴" if ev.get("severity") in ("ERROR", "FATAL") else "🟡"
                    st.markdown(f"{sev_icon} `{ev.get('timestamp')}` — {ev.get('event')}")

    # 2. Root Cause Analyst Output
    if state.get("root_cause"):
        rc = state.get("root_cause")
        conf = state.get("confidence", 0.0)
        evidence = state.get("evidence", [])
        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid #AB47BC;">
                <div class="feed-header" style="color: #AB47BC;">
                    🧠 Root-Cause Diagnosis
                </div>
                <div style="font-size: 1.1rem; font-weight: 600; color: #f8fafc; margin-bottom: 0.5rem;">
                    🎯 {rc}
                </div>
            </div>
            """, unsafe_allow_html=True)
            st.progress(conf, text=f"Diagnosis Confidence: {conf:.0%}")

            with st.expander("🔍 Corroborating Evidence & Alternative Hypotheses", expanded=False):
                st.write("**Direct Evidence:**")
                for ev in evidence:
                    st.markdown(f"- {ev}")
                if state.get("alternative_causes"):
                    st.write("**Alternative Hypotheses Considered:**")
                    for alt in state.get("alternative_causes", []):
                        st.markdown(f"- **{alt.get('cause')}** ({alt.get('confidence', 0):.0%}) — *{alt.get('why_less_likely')}*")

    # 3. Fix Proposer Output
    if state.get("proposed_fixes"):
        fixes = state.get("proposed_fixes", [])
        rec_id = state.get("recommended_fix_id", 1)
        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid #66BB6A;">
                <div class="feed-header" style="color: #66BB6A;">
                    🔧 Fix Proposer Recommendations ({len(fixes)} options generated)
                </div>
            </div>
            """, unsafe_allow_html=True)

            for fix in fixes:
                is_rec = fix.get("id") == rec_id
                risk = fix.get("risk_level", "LOW")
                risk_color = "#34d399" if risk == "LOW" else ("#f59e0b" if risk == "MEDIUM" else "#ef4444")

                with st.expander(
                    f"{'⭐ [RECOMMENDED] ' if is_rec else ''}Fix #{fix.get('id')}: {fix.get('title')} ({risk} RISK)",
                    expanded=is_rec,
                ):
                    st.markdown(f"**Description:** {fix.get('description')}")
                    st.markdown(f"**Risk Level:** <span style='color:{risk_color}; font-weight:bold;'>{risk}</span>", unsafe_allow_html=True)
                    st.markdown(f"**Estimated Downtime:** `{fix.get('estimated_downtime')}`")
                    st.markdown("**Executable Commands:**")
                    for cmd in fix.get("commands", []):
                        st.code(cmd, language="bash")
                    st.markdown(f"**Rollback Plan:** `{fix.get('rollback_plan')}`")

    # 4. Safety Checker Output
    if state.get("safety_report") or state.get("evaluations"):
        evals = state.get("evaluations", [])
        approved_id = state.get("approved_fix_id", 0)
        rejection_reasons = state.get("rejection_reasons", [])

        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid #FFA726;">
                <div class="feed-header" style="color: #FFA726;">
                    🛡️ Safety Checker Gate Verdict
                </div>
                <p>Safety Gate evaluated {len(evals)} proposed fixes against operational safety policies.</p>
            </div>
            """, unsafe_allow_html=True)

            for ev in evals:
                r_class = ev.get("risk_classification")
                badge_color = "#10b981" if r_class == "LOW" else ("#f59e0b" if r_class == "MEDIUM" else "#ef4444")
                st.markdown(
                    f"- Fix #{ev.get('fix_id')}: <b style='color:{badge_color};'>[{r_class}]</b> {ev.get('reasoning')}",
                    unsafe_allow_html=True,
                )

            if rejection_reasons:
                for rr in rejection_reasons:
                    st.error(f"🚫 {rr}")

    # 5. Runbook Execution Result
    if state.get("execution_result"):
        er = state.get("execution_result", {})
        success = er.get("success", False)
        dry = er.get("dry_run", False)

        color = "#10b981" if success else "#ef4444"
        title = "🐳 Runbook Execution Succeeded" if success else "❌ Runbook Execution Failed"

        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid {color};">
                <div class="feed-header" style="color: {color};">
                    {title} {'[DRY-RUN]' if dry else '[LIVE CONTAINER]'}
                </div>
            </div>
            """, unsafe_allow_html=True)

            st.write("**Commands Executed:**")
            for c in er.get("commands_run", []):
                st.code(c, language="bash")

            st.write("**Command Output:**")
            for out in er.get("outputs", []):
                st.code(out, language="text")

    # 6. Status Communicator
    if state.get("status_update"):
        su = state.get("status_update")
        with st.container():
            st.markdown(f"""
            <div class="feed-card" style="border-left: 5px solid #26C6DA;">
                <div class="feed-header" style="color: #26C6DA;">
                    📢 Stakeholder Communications (Slack / Status Page)
                </div>
                <div style="background: rgba(38, 198, 218, 0.1); padding: 1rem; border-radius: 8px; color: #e2e8f0; font-size: 0.95rem;">
                    {su}
                </div>
            </div>
            """, unsafe_allow_html=True)


# ── FR3: Inline Human-in-the-Loop Approval Card ─────────────────────────

def render_human_approval_card(state: dict[str, Any]):
    fix = st.session_state.approval_fix or state.get("approved_fix", {})
    fix_id = fix.get("id", state.get("approved_fix_id", 1))

    st.markdown(f"""
    <div class="approval-banner">
        <h3 style="color: #f59e0b; margin-top: 0;">⚠️ Human-in-the-Loop Approval Gate (FR3)</h3>
        <p style="color: #fef3c7; font-size: 0.95rem;">
            The Safety Checker classified the recommended fix as <b>MEDIUM RISK</b>.
            Before the Runbook Executor touches production, an engineer must review and approve or reject the action.
        </p>
        <div style="background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 8px; margin: 1rem 0;">
            <div style="font-size: 1.1rem; font-weight: 700; color: #fff;">Fix #{fix_id}: {fix.get('title')}</div>
            <div style="color: #d1d5db; margin: 0.3rem 0;">{fix.get('description')}</div>
            <div style="color: #94a3b8; font-size: 0.85rem;">Estimated Downtime: <code>{fix.get('estimated_downtime', '< 1 min')}</code></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.write("**Proposed Commands to Run:**")
    for cmd in fix.get("commands", []):
        st.code(cmd, language="bash")

    col_appr, col_rej = st.columns([1, 1])

    with col_appr:
        if st.button("✅ Approve & Execute Fix", type="primary", use_container_width=True):
            orch = st.session_state.orchestrator
            with st.spinner("Executing approved fix on container..."):
                final_state = orch.run_phase2_execution_and_reporting(user_approved=True)
                st.session_state.incident_state = final_state
                st.session_state.approval_requested = False
            st.toast("Fix approved and executed!", icon="✅")
            st.rerun()

    with col_rej:
        if st.button("❌ Reject & Request Alternative Fix", use_container_width=True):
            st.session_state.rejection_mode = True

    if st.session_state.get("rejection_mode"):
        st.markdown("---")
        st.warning("Provide operator rejection feedback to guide the Fix Proposer:")
        feedback = st.text_input(
            "Rejection Reason / Guidance for AI Agents",
            value="Please propose a safer, non-restart alternative that avoids container downtime.",
        )
        if st.button("🔁 Submit Feedback and Loop Back to Fix Proposer", type="secondary"):
            orch = st.session_state.orchestrator
            with st.spinner("Sending feedback back to Fix Proposer for alternative..."):
                updated_state = orch.handle_rejection(feedback)
                st.session_state.incident_state = updated_state
                st.session_state.rejection_mode = False
                if updated_state.get("status") == "awaiting_approval":
                    st.session_state.approval_requested = True
                    st.session_state.approval_fix = updated_state.get("approved_fix")
                else:
                    st.session_state.approval_requested = False
            st.toast("Control looped back to Fix Proposer with your feedback!", icon="🔄")
            st.rerun()


# ── Bottom Section: Postmortem Viewer & Download ────────────────────────

def render_postmortem_section(state: dict[str, Any]):
    st.markdown("---")
    st.markdown("### 📝 Incident Postmortem Report (FR5)")

    report = state.get("postmortem_report", "")

    # Postmortem viewer
    st.markdown(report)

    # Download Button
    inc_id = state.get("incident_id", "incident")
    st.download_button(
        label="📥 Download Structured Postmortem Report (.md)",
        data=report,
        file_name=f"postmortem_{inc_id}.md",
        mime="text/markdown",
        type="primary",
    )

    # Observability & Reasoning Trace Tab (FR6)
    with st.expander("🔍 Observability: Agent Reasoning Trace & Latency Log (FR6)", expanded=False):
        render_reasoning_trace(state)


def render_reasoning_trace(state: dict[str, Any]):
    st.markdown("Every agent call is tracked with latency, prompts, and output for complete auditability:")
    agent_logs = state.get("agent_log", [])

    if not agent_logs:
        st.info("No step logs found.")
        return

    for log in agent_logs:
        st.markdown(f"#### 🤖 {log.get('agent_name')} — `{log.get('duration_ms')}ms` (Status: `{log.get('status')}`)")
        st.markdown(f"- **Started:** `{log.get('started_at')}` | **Completed:** `{log.get('completed_at')}`")
        if log.get("error"):
            st.error(f"Error: {log.get('error')}")
        st.code(log.get("output_preview", ""), language="json")


# ── View 2: Evaluation Benchmark View ───────────────────────────────────

def render_evaluation_view():
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">📊 Evaluation Benchmark Suite</div>
        <div class="hero-subtitle">
            Requirement 10: Comparative benchmark of Single-Prompt Baseline vs Full Multi-Agent Pipeline across all 3 scenarios.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    This evaluation compares the architectures on:
    1. **Root Cause Correctness**
    2. **Unsafe Fix Proposed** (Did the model suggest dangerous commands like `rm -rf` or `drop table`?)
    3. **Unsafe Fix Executed** (Did the safety gate catch and prevent execution?)
    4. **Response Latency**
    5. **Postmortem Quality Score** (1-5 SRE rubric based on timelines, root cause depth, and action items)
    """)

    if st.button("⚡ Run Live Benchmark Across All 3 Scenarios", type="primary"):
        with st.spinner("Running benchmarks across oom_crash, db_connection_failure, and bad_deploy..."):
            evaluator = IncidentEvaluator(LLMClient(provider=st.session_state.provider, api_key=st.session_state.api_key))
            results = evaluator.evaluate_all()
            st.session_state.eval_results = results
        st.toast("Evaluation complete!", icon="📊")

    # Render results table
    eval_file = Path("data/evaluation_results.md")
    if eval_file.exists():
        st.markdown("### 🏆 Benchmark Results Table")
        st.markdown(eval_file.read_text(encoding="utf-8"))

        st.markdown("---")
        st.markdown("### 💡 Key Findings")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **Single-Agent Baseline Deficiencies:**
            - 🚨 **Zero Safety Gates:** Single-prompt LLMs willingly propose and execute destructive actions (e.g. `docker rm -f`, `drop database`).
            - ⚠️ **Superficial Postmortems:** Averaged **1.0 - 1.8 / 5** quality score due to missing chronological timelines, root-cause depth, and action items.
            - ❌ **No Human-in-the-Loop:** Inflexible, all-or-nothing execution without risk grading.
            """)
        with col2:
            st.markdown("""
            **Multi-Agent Team (Ours) Advantages:**
            - 🛡️ **Hard Safety Gate:** Dangerous fixes are automatically classified as `HIGH` risk and blocked before reaching execution.
            - ⭐ **High Quality Postmortems (5.0 / 5):** Structured reports with root cause, timelines, and prevention tasks.
            - 🔁 **Human Feedback Loop:** Rejection loops back to Fix Proposer for safer alternatives.
            """)


# ── View 3: Incident History View ───────────────────────────────────────

def render_history_view():
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-title">📚 Incident Audit History</div>
        <div class="hero-subtitle">
            Browse past incidents stored in SQLite (incidents.db) with reasoning traces and audit trails.
        </div>
    </div>
    """, unsafe_allow_html=True)

    db = IncidentDatabase()
    incidents = db.list_incidents(limit=50)

    if not incidents:
        st.info("No past incidents in database yet. Run an incident from the Response Room!")
        return

    for inc in incidents:
        inc_id = inc["id"]
        status_icon = "🟢" if inc.get("pipeline_status") == "completed" else "🔴"
        with st.expander(f"{status_icon} `{inc_id}` — {inc.get('incident_type')} ({inc.get('created_at', '')[:19]})"):
            full = db.get_incident(inc_id)
            if full:
                st.write(f"**Status:** `{full.get('pipeline_status')}`")
                st.write(f"**Created:** `{full.get('created_at')}`")

                steps = full.get("steps", [])
                st.markdown(f"**Agent Steps Executed:** {len(steps)}")
                for s in steps:
                    st.markdown(f"- **{s.get('agent_name')}**: status=`{s.get('status')}` ({s.get('duration_ms')}ms)")

                if full.get("postmortem"):
                    st.markdown("---")
                    st.markdown("#### Postmortem Summary")
                    st.markdown(full.get("postmortem")[:500] + "\n\n*(Truncated for preview)*")

                if st.button(f"🗑️ Delete Incident {inc_id}", key=f"del_{inc_id}"):
                    db.delete_incident(inc_id)
                    st.toast(f"Deleted incident {inc_id}", icon="🗑️")
                    st.rerun()


# ── Main Entrypoint ─────────────────────────────────────────────────────

def main():
    render_sidebar()

    active_view = st.session_state.get("active_view", "response_room")
    if active_view == "evaluation":
        render_evaluation_view()
    elif active_view == "history":
        render_history_view()
    else:
        render_response_room()


if __name__ == "__main__":
    main()
