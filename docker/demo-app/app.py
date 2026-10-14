"""Demo Flask application designed to simulate production incidents on demand.

Endpoints:
  GET  /               - Healthy status check
  GET  /health         - Service health check
  POST /crash/oom      - Trigger simulated OutOfMemory crash
  POST /crash/db       - Trigger simulated Database connection failure
  POST /crash/deploy   - Trigger bad deployment (code bug in checkout)
  POST /reset          - Reset container to healthy state
  GET  /logs           - Get recent in-memory log buffer
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
import threading
import time
from flask import Flask, jsonify, request

app = Flask(__name__)

# State
container_state = {
    "status": "healthy",
    "version": "v2.4.0",
    "db_connected": True,
    "memory_pressure": 0.3,
    "bad_deploy_active": False,
    "request_count": 0,
    "error_count": 0,
    "last_reset": datetime.datetime.utcnow().isoformat() + "Z",
}

# In-memory log buffer
log_buffer: list[str] = []
buffer_lock = threading.Lock()


def emit_log(level: str, source: str, message: str) -> str:
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"{now} {level:<5} [{source}] {message}"
    with buffer_lock:
        log_buffer.append(entry)
        if len(log_buffer) > 200:
            log_buffer.pop(0)
    print(entry, flush=True)
    return entry


@app.route("/", methods=["GET"])
def index():
    container_state["request_count"] += 1
    emit_log("INFO", "web-server", "Handled request: GET / - 200 OK")
    return jsonify({
        "app": "demo-app",
        "status": container_state["status"],
        "version": container_state["version"],
        "healthy": container_state["status"] == "healthy",
    })


@app.route("/health", methods=["GET"])
def health():
    container_state["request_count"] += 1
    if container_state["status"] != "healthy":
        container_state["error_count"] += 1
        emit_log("ERROR", "health-checker", f"Health check FAILED: status={container_state['status']}")
        return jsonify({
            "status": "unhealthy",
            "reason": container_state["status"],
            "version": container_state["version"],
        }), 500

    emit_log("INFO", "health-checker", "Health check OK: all systems operational")
    return jsonify({
        "status": "healthy",
        "version": container_state["version"],
        "memory_usage": f"{container_state['memory_pressure'] * 100:.1f}%",
        "database": "connected" if container_state["db_connected"] else "disconnected",
    }), 200


@app.route("/crash/oom", methods=["POST"])
def crash_oom():
    """Simulate Java/Python heap exhaustion leading to OOM crash."""
    container_state["status"] = "oom_killed"
    container_state["memory_pressure"] = 0.99
    container_state["error_count"] += 1

    emit_log("WARN", "web-server", "Heap usage at 85% (1.70GB / 2.0GB)")
    emit_log("WARN", "web-server", "GC pause: 450ms (threshold: 200ms)")
    emit_log("WARN", "web-server", "Heap usage at 98% (1.96GB / 2.0GB)")
    emit_log("ERROR", "web-server", "Request failed: POST /api/orders - 500 Internal Server Error")
    emit_log("ERROR", "web-server", "java.lang.OutOfMemoryError: Java heap space")
    emit_log("FATAL", "health-checker", "Service demo-app marked UNHEALTHY after OutOfMemoryError")
    emit_log("ERROR", "load-balancer", "Removed demo-app from rotation - container unresponsive")

    return jsonify({
        "message": "OOM Crash triggered on demo-app",
        "status": "crashed",
        "heap_usage": "99%",
    }), 500


@app.route("/crash/db", methods=["POST"])
def crash_db():
    """Simulate Database connection pool exhaustion and backend timeout."""
    container_state["status"] = "db_connection_failure"
    container_state["db_connected"] = False
    container_state["error_count"] += 1

    emit_log("WARN", "db-pool", "Active connections: 20/20, idle: 0/20 - POOL EXHAUSTED")
    emit_log("ERROR", "db-pool", "Connection to postgres-primary:5432 refused")
    emit_log("ERROR", "web-server", "Request failed: GET /api/users - 503 Service Unavailable")
    emit_log("ERROR", "web-server", "org.postgresql.util.PSQLException: Connection refused")
    emit_log("FATAL", "health-checker", "Service demo-app marked DEGRADED - database backend unreachable")

    return jsonify({
        "message": "Database connection crash triggered on demo-app",
        "status": "degraded",
        "db_connected": False,
    }), 503


@app.route("/crash/deploy", methods=["POST"])
def crash_deploy():
    """Simulate bad deployment v2.4.1 that introduced a syntax/runtime bug."""
    container_state["status"] = "bad_deploy_v2.4.1"
    container_state["version"] = "v2.4.1"
    container_state["bad_deploy_active"] = True
    container_state["error_count"] += 1

    emit_log("INFO", "deploy-bot", "Deploying image: demo-app:v2.4.1")
    emit_log("WARN", "web-server", "Experimental feature flag 'CHECKOUT_V2' active")
    emit_log("ERROR", "web-server", "Request failed: POST /api/checkout - 500 Internal Server Error")
    emit_log("ERROR", "web-server", "TypeError: Cannot read properties of undefined (reading 'calculate_discount')")
    emit_log("WARN", "monitoring", "Checkout failure rate >80% after v2.4.1 deployment")

    return jsonify({
        "message": "Bad deployment v2.4.1 triggered on demo-app",
        "version": "v2.4.1",
        "error": "TypeError in calculate_discount",
    }), 500


@app.route("/reset", methods=["POST"])
def reset():
    """Reset the container to a healthy state (simulates restart/rollback)."""
    version = request.json.get("version", "v2.4.0") if request.is_json else "v2.4.0"
    container_state["status"] = "healthy"
    container_state["version"] = version
    container_state["db_connected"] = True
    container_state["memory_pressure"] = 0.25
    container_state["bad_deploy_active"] = False
    container_state["last_reset"] = datetime.datetime.utcnow().isoformat() + "Z"

    emit_log("INFO", "system", f"Container restarted successfully. Restored healthy state (version={version})")
    emit_log("INFO", "health-checker", "Health check PASSED: demo-app is healthy")
    emit_log("INFO", "load-balancer", "demo-app returned to load balancer rotation")

    return jsonify({
        "message": "Container reset successfully",
        "status": "healthy",
        "version": version,
    }), 200


@app.route("/logs", methods=["GET"])
def get_logs():
    with buffer_lock:
        return "\n".join(log_buffer), 200, {"Content-Type": "text/plain"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    emit_log("INFO", "system", f"Demo app starting on port {port} (version={container_state['version']})")
    app.run(host="0.0.0.0", port=port, debug=False)
