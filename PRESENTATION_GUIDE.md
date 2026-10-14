# 🎤 Presentation & Demo Guide: Incident Response Room

This guide provides a **3-minute live presentation script**, core architectural talking points, and anticipated Q&A to ensure an engaging demonstration.

---

## ⏱️ 3-Minute Live Demo Script

### Minute 1: The Problem & The Solution
1. **The Hook:**
   > *"When production servers go down at 3 AM, human on-call engineers face cognitive overload: parsing thousands of log lines, diagnosing root causes under stress, and hoping their fix doesn't cause more damage. Today, we built the **Incident Response Room** — an autonomous multi-agent AI system that simulates an entire SRE team working together in real-time."*
2. **Open the UI:**
   - Launch `run_demo.bat` or run `streamlit run app.py`.
   - Point to the **Sidebar**: show that it supports **Simulation/Offline mode** (zero API keys needed) as well as **Claude 3.5 Sonnet** and **Groq Cloud**.
   - Show the **Docker Container Status** monitor.

---

### Minute 2: Triggering an Incident & Live Multi-Agent Pipeline
1. **Select a Scenario:**
   - In the dropdown, pick **`🚀 Bad Deployment v2.4.1 (Checkout Regression)`** (or trigger a live crash using **`Trigger Bad Deploy`** in the container expander).
   - Click **`🚀 Trigger Incident Pipeline`**.
2. **Highlight the Live Stream (FR2):**
   - Direct attention to the live progress feed:
     - 🔍 **Log Analyst**: parses error rate surges (>80%) and builds the timeline.
     - 🧠 **Root-Cause Analyst**: diagnoses the exact code regression (`TypeError in calculate_discount`).
     - 🔧 **Fix Proposer**: formulates 3 ranked runbook fixes (Rollback vs Feature Flag toggle vs Aggressive hot-patching).
     - 🛡️ **Safety Checker (Hard Gate)**: automatically analyzes blast radius. It rejects Fix #3 outright (HIGH risk) and flags Fix #1 as MEDIUM risk.

---

### Minute 3: The Human-in-the-Loop Gate (FR3) & Postmortem (FR5)
1. **Show the Inline Approval Card:**
   > *"Notice the pipeline paused before touching production. Because rolling back an image tag is MEDIUM risk, our safety policy requires human sign-off."*
2. **Demonstrate the Rejection Loop:**
   - Click **`❌ Reject & Request Alternative Fix`**.
   - Type in: *"Propose a safer in-place feature flag toggle instead of rollback."*
   - Click **`🔁 Submit Feedback`**.
   - Point out that control looped back to the **Fix Proposer**, generating an updated proposal that incorporates human guidance!
3. **Approve & Execute (FR4):**
   - Click **`✅ Approve & Execute Fix`**.
   - Watch the **Runbook Executor** run the container fix and verify health check pass.
4. **Show Deliverables:**
   - **Postmortem Report**: Scroll down to the structured report (Executive Summary, Impact, Timeline, Root Cause, Action Items) and click **`📥 Download Postmortem (.md)`**.
   - **Observability Trace (FR6)**: Expand **`🔍 Observability`** to show exact prompts, raw JSON, and sub-second latencies recorded in SQLite.
   - **Evaluation Tab**: Switch to **`📊 Evaluation Benchmark`** to show our results table demonstrating **100% root cause accuracy**, **0 unsafe fixes executed** (blocked by Hard Gate), and **5.0/5 postmortem score** vs **1.0/5 for single-prompt baselines**.

---

## 🏛️ Core Architectural Talking Points

1. **Hub-and-Spoke vs Peer-to-Peer:**
   - Agents never call each other directly. All state is maintained in a central `shared_state` dictionary owned by the `Orchestrator`.
   - **Why?** Eliminates infinite agent call loops, simplifies debugging to "read the state after step N", and enables deterministic audit logging.
2. **Non-Negotiable Safety Hard Gate:**
   - Rejection by the Safety Checker is final. Even if an operator clicks approve, high-risk destructive commands (e.g. `rm -rf`, dropping tables) cannot be executed by the Runbook Executor.
3. **Human-in-the-Loop Rejection Loop:**
   - Rejection is not a dead end. Feedback loops back to the Fix Proposer to negotiate a viable path forward.
4. **Offline Portability & Zero-Dependency Execution:**
   - Built-in simulation mode allows complete demos without external API keys or cloud dependencies.

---

## 💬 Anticipated Q&A

### Q1: *"Why didn't you use LangChain or CrewAI?"*
> **Answer:** *"For mission-critical production incident response, transparency and predictable state transitions are paramount. Frameworks like CrewAI or LangChain add abstraction layers that make debugging state drift difficult. Our native Python hub-and-spoke Orchestrator has zero hidden prompts, deterministic execution, and logs every step directly to SQLite with zero bloat."*

### Q2: *"What stops an LLM hallucination from deleting our database?"*
> **Answer:** *"A two-layer defense-in-depth model: First, the **Safety Checker agent** scans proposed commands and enforces a Hard Gate blocking any HIGH-risk actions. Second, the **Runbook Executor** enforces a strict regex whitelist of approved Docker subcommands (e.g., restart, update, logs) and rejects unapproved prefixes."*

### Q3: *"How does the system perform under real latency constraints?"*
> **Answer:** *"In simulated mode, the pipeline finishes in under 2 seconds. When running against live Claude 3.5 Sonnet or Groq Cloud, the entire 6-agent chain completes in 12–18 seconds — well within our 30-second non-functional requirement."*

### Q4: *"Can this integrate with real production tools like PagerDuty or Datadog?"*
> **Answer:** *"Yes. The Orchestrator's input is a log stream (which can be fed via Datadog/CloudWatch webhooks), and the Status Communicator agent's output is structured for direct delivery to Slack webhooks or PagerDuty incident notes."*
