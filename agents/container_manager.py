"""Container Manager supporting both real Docker daemon and in-process simulation.

Provides:
- Checking Docker daemon status
- Managing demo-app container (start, stop, restart, inspect, logs)
- Triggering live crashes (OOM, DB connection failure, bad deploy)
- Full in-process simulated container engine if Docker daemon is not active.
"""

from __future__ import annotations

import datetime
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("incident_response.container_manager")

LIVE_LOG_PATH = Path("data/incidents/live_container.log")


class ContainerManager:
    """Manages real or simulated demo-app container."""

    def __init__(self, container_name: str = "demo-app", port: int = 5050):
        self.container_name = container_name
        self.port = port
        self.is_docker_available = self._check_docker()

        # Simulated container state if Docker daemon is not active
        self._sim_state = {
            "status": "running",
            "health": "healthy",
            "version": "v2.4.0",
            "memory_usage": "24%",
            "db_connected": True,
            "last_action": "initialized",
            "crashed": False,
            "crash_scenario": None,
        }

    def _check_docker(self) -> bool:
        """Check if Docker CLI and daemon are reachable."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return res.returncode == 0
        except Exception:
            return False

    def get_status(self) -> dict:
        """Get container status (real Docker or simulated)."""
        if self.is_docker_available:
            try:
                res = subprocess.run(
                    ["docker", "inspect", self.container_name, "--format", "{{json .State}}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0:
                    import json
                    state_data = json.loads(res.stdout.strip())
                    return {
                        "mode": "real_docker",
                        "status": state_data.get("Status", "running"),
                        "running": state_data.get("Running", False),
                        "started_at": state_data.get("StartedAt"),
                    }
            except Exception as e:
                logger.warning("Failed to inspect real docker container: %s", e)

        return {
            "mode": "simulated",
            "status": self._sim_state["status"],
            "health": self._sim_state["health"],
            "version": self._sim_state["version"],
            "crashed": self._sim_state["crashed"],
            "scenario": self._sim_state["crash_scenario"],
            "memory_usage": self._sim_state["memory_usage"],
            "db_connected": self._sim_state["db_connected"],
        }

    def trigger_crash(self, scenario: str) -> tuple[bool, str, str]:
        """Trigger an incident on the container (real or simulated).

        Returns:
            (success: bool, message: str, log_file_path: str)
        """
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        LIVE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        if scenario == "oom_crash":
            self._sim_state.update({
                "status": "crashed",
                "health": "unhealthy",
                "crashed": True,
                "crash_scenario": "oom_crash",
                "memory_usage": "99.2%",
                "last_action": f"OOM crash triggered at {now}",
            })
            logs = f"""{now} INFO  [demo-app] Handling traffic: POST /api/orders (heap at 65%)
{now} WARN  [demo-app] Heap usage surging: 85% (1.70GB / 2.0GB)
{now} WARN  [demo-app] GC pause: 450ms (threshold: 200ms)
{now} WARN  [demo-app] Heap usage critical: 98% (1.96GB / 2.0GB)
{now} ERROR [demo-app] Request failed: GET /api/users - 500 Internal Server Error (timeout)
{now} ERROR [demo-app] java.lang.OutOfMemoryError: Java heap space
{now} ERROR [demo-app]     at com.example.service.UserService.loadAllUsers(UserService.java:142)
{now} ERROR [demo-app]     at com.example.controller.UserController.getUsers(UserController.java:58)
{now} ERROR [health-checker] Health check FAILED for demo-app (attempt 1/3)
{now} ERROR [health-checker] Health check FAILED for demo-app (attempt 2/3)
{now} FATAL [health-checker] Service demo-app marked UNHEALTHY after OutOfMemoryError
{now} ERROR [load-balancer] Removed demo-app from rotation - container unresponsive
"""
            msg = "Triggered OutOfMemoryError crash in demo-app container"

        elif scenario in ("db_connection_failure", "db_failure"):
            self._sim_state.update({
                "status": "degraded",
                "health": "unhealthy",
                "crashed": True,
                "crash_scenario": "db_connection_failure",
                "db_connected": False,
                "last_action": f"DB connection crash triggered at {now}",
            })
            logs = f"""{now} INFO  [demo-app] Connection checkout pool status: active=18/20, idle=2/20
{now} WARN  [demo-app] Connection pool latency 950ms exceeds SLA
{now} ERROR [demo-app] Connection to db-primary.internal:5432 refused
{now} ERROR [demo-app] org.postgresql.util.PSQLException: Connection to db-primary.internal:5432 refused.
{now} WARN  [db-pool] Active connections: 20/20, idle: 0/20 - POOL EXHAUSTED
{now} ERROR [demo-app] Request failed: GET /api/dashboard - 503 Service Unavailable
{now} ERROR [demo-app] Failover to replica db-replica.internal:5432 also failed: connection refused
{now} FATAL [health-checker] Service demo-app marked DEGRADED - database backend unreachable
{now} WARN  [alerting] ALERT TRIGGERED: demo-app returning 503 errors (error_rate=95%)
"""
            msg = "Triggered Database Connection Failure on demo-app container"

        elif scenario in ("bad_deploy", "bad_deployment"):
            self._sim_state.update({
                "status": "degraded",
                "health": "unhealthy",
                "crashed": True,
                "version": "v2.4.1",
                "crash_scenario": "bad_deploy",
                "last_action": f"Bad deployment v2.4.1 applied at {now}",
            })
            logs = f"""{now} INFO  [deploy-bot] Stopping container demo-app:v2.4.0
{now} INFO  [deploy-bot] Starting container demo-app:v2.4.1
{now} WARN  [demo-app] Experimental flag 'CHECKOUT_V2' active in v2.4.1
{now} INFO  [demo-app] Application started on port 5050
{now} ERROR [demo-app] Request failed: POST /api/checkout - 500 Internal Server Error
{now} ERROR [demo-app] TypeError: Cannot read properties of undefined (reading 'calculate_discount')
{now} ERROR [demo-app]     at CheckoutServiceV2.processPayment (checkout_v2.js:87)
{now} ERROR [demo-app] Request failed: POST /api/checkout - 500 Internal Server Error (attempt 2)
{now} WARN  [monitoring] Checkout success rate dropped from 99.8% to 15.0% after v2.4.1 deployment
{now} ERROR [monitoring] Revenue impact detected: customer transactions failing on checkout
"""
            msg = "Triggered Bad Deployment (v2.4.1) on demo-app container"

        else:
            return False, f"Unknown scenario: {scenario}", ""

        LIVE_LOG_PATH.write_text(logs, encoding="utf-8")
        return True, msg, str(LIVE_LOG_PATH)

    def execute_docker_command(self, cmd: str) -> str:
        """Execute or simulate a docker command against demo-app."""
        cmd_clean = cmd.strip()

        if self.is_docker_available:
            try:
                res = subprocess.run(
                    cmd_clean,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if res.returncode == 0:
                    return res.stdout.strip() or f"Command succeeded: {cmd_clean}"
                else:
                    logger.warning("Docker CLI error: %s, falling back to simulated execution", res.stderr)
            except Exception as e:
                logger.warning("Subprocess failed: %s", e)

        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if "restart" in cmd_clean:
            self._sim_state.update({
                "status": "running",
                "health": "healthy",
                "crashed": False,
                "memory_usage": "22%",
                "db_connected": True,
                "version": "v2.4.0",
                "last_action": f"Restarted at {now}",
            })
            return f"Container '{self.container_name}' restarted successfully [simulated]. Health check: PASSED."

        elif "stop" in cmd_clean:
            self._sim_state["status"] = "stopped"
            return f"Container '{self.container_name}' stopped successfully [simulated]."

        elif "start" in cmd_clean:
            self._sim_state["status"] = "running"
            return f"Container '{self.container_name}' started successfully [simulated]."

        elif "rollback" in cmd_clean or ("run" in cmd_clean and "v2.4.0" in cmd_clean):
            self._sim_state.update({
                "status": "running",
                "health": "healthy",
                "crashed": False,
                "version": "v2.4.0",
                "last_action": f"Rolled back to v2.4.0 at {now}",
            })
            return f"Container '{self.container_name}' rolled back to image tag v2.4.0 [simulated]. Health check: PASSED."

        elif "exec" in cmd_clean:
            return f"Executed command in '{self.container_name}' [simulated]: exit code 0."

        elif "logs" in cmd_clean:
            if LIVE_LOG_PATH.exists():
                return LIVE_LOG_PATH.read_text(encoding="utf-8")
            return f"No recent logs for '{self.container_name}'."

        return f"Executed: {cmd_clean} [simulated output: OK]"
