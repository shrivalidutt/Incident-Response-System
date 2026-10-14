"""Docker command executor with dry-run safety mode and simulated container fallback.

Executes approved fix commands against Docker containers.
Supports:
1. Real execution via the Docker SDK / Docker CLI (when daemon is running)
2. Dry-run mode (logs what *would* happen without modifying containers)
3. Simulated container engine fallback (when Docker daemon is unavailable, ensuring
   portability and offline demo execution without external dependencies).
"""

from __future__ import annotations

import logging
import shlex
from typing import Optional

from agents.models import ExecutionResult, ProposedFix
from agents.container_manager import ContainerManager

logger = logging.getLogger("incident_response.docker")

# Commands that are safe to execute (whitelist approach)
ALLOWED_COMMAND_PREFIXES = [
    "docker restart",
    "docker stop",
    "docker start",
    "docker rm",
    "docker run",
    "docker exec",
    "docker logs",
    "docker update",
    "docker ps",
    "docker inspect",
]


class DockerExecutor:
    """Executes Docker commands from approved fixes."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self._docker_client = None
        self._container_manager = ContainerManager()

    @property
    def docker_client(self):
        """Lazy-load Docker client only when needed for real execution."""
        if self._docker_client is None:
            try:
                import docker
                self._docker_client = docker.from_env()
                logger.info("Docker client connected successfully")
            except Exception as e:
                logger.warning("Docker daemon not running: %s. Using simulated container fallback.", e)
                return None
        return self._docker_client

    def execute_fix(self, fix: ProposedFix | dict) -> ExecutionResult:
        """Execute all commands in a proposed fix.

        Args:
            fix: A ProposedFix dataclass or dict with 'id', 'commands', etc.

        Returns:
            ExecutionResult with success status and command outputs.
        """
        if isinstance(fix, dict):
            fix_id = fix.get("id", 0)
            commands = fix.get("commands", [])
            title = fix.get("title", "Unknown Fix")
        else:
            fix_id = fix.id
            commands = fix.commands
            title = fix.title

        logger.info(
            "%s fix #%d: %s (%d commands)",
            "DRY-RUN" if self.dry_run else "EXECUTING",
            fix_id,
            title,
            len(commands),
        )

        outputs: list[str] = []
        commands_run: list[str] = []

        for cmd in commands:
            # Validate command before execution
            if not self._is_command_allowed(cmd):
                error_msg = f"BLOCKED: Command not in allowlist: {cmd}"
                logger.warning(error_msg)
                return ExecutionResult(
                    fix_id=fix_id,
                    commands_run=commands_run,
                    outputs=outputs + [error_msg],
                    success=False,
                    error=error_msg,
                    dry_run=self.dry_run,
                )

            if self.dry_run:
                output = f"[DRY-RUN] Would execute: {cmd}"
                logger.info(output)
                outputs.append(output)
                commands_run.append(cmd)
            else:
                try:
                    output = self._execute_command(cmd)
                    outputs.append(output)
                    commands_run.append(cmd)
                    logger.info("Command succeeded: %s", cmd)
                except Exception as e:
                    error_msg = f"Command failed: {cmd} — {e}"
                    logger.error(error_msg)
                    return ExecutionResult(
                        fix_id=fix_id,
                        commands_run=commands_run,
                        outputs=outputs + [error_msg],
                        success=False,
                        error=error_msg,
                        dry_run=self.dry_run,
                    )

        return ExecutionResult(
            fix_id=fix_id,
            commands_run=commands_run,
            outputs=outputs,
            success=True,
            dry_run=self.dry_run,
        )

    def _is_command_allowed(self, command: str) -> bool:
        """Check if a command is in the allowed whitelist."""
        cmd_stripped = command.strip()
        return any(
            cmd_stripped.startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES
        )

    def _execute_command(self, command: str) -> str:
        """Execute a single Docker command and return the output."""
        client = self.docker_client
        if client is not None:
            parts = shlex.split(command)
            action = parts[1] if len(parts) > 1 else ""

            try:
                if action == "restart":
                    return self._restart_container(parts)
                elif action == "stop":
                    return self._stop_container(parts)
                elif action == "start":
                    return self._start_container(parts)
                elif action == "exec":
                    return self._exec_in_container(parts)
                elif action == "rm":
                    return self._remove_container(parts)
                elif action == "run":
                    return self._run_container(command)
                elif action == "update":
                    return self._update_container(command)
                elif action == "logs":
                    return self._get_logs(parts)
            except Exception as e:
                logger.warning("Docker SDK failed (%s), delegating to container manager", e)

        # Container Manager fallback (real or simulated)
        return self._container_manager.execute_docker_command(command)

    def _restart_container(self, parts: list[str]) -> str:
        container_name = parts[-1]
        container = self.docker_client.containers.get(container_name)
        container.restart()
        return f"Container '{container_name}' restarted successfully"

    def _stop_container(self, parts: list[str]) -> str:
        container_name = parts[-1]
        container = self.docker_client.containers.get(container_name)
        container.stop()
        return f"Container '{container_name}' stopped successfully"

    def _start_container(self, parts: list[str]) -> str:
        container_name = parts[-1]
        container = self.docker_client.containers.get(container_name)
        container.start()
        return f"Container '{container_name}' started successfully"

    def _exec_in_container(self, parts: list[str]) -> str:
        container_name = parts[2]
        exec_cmd = parts[3:]
        container = self.docker_client.containers.get(container_name)
        exit_code, output = container.exec_run(exec_cmd)
        result = output.decode("utf-8", errors="replace")
        if exit_code != 0:
            raise DockerExecutionError(
                f"exec in '{container_name}' exited with code {exit_code}: {result}"
            )
        return result

    def _remove_container(self, parts: list[str]) -> str:
        container_name = parts[-1]
        container = self.docker_client.containers.get(container_name)
        container.remove(force=True)
        return f"Container '{container_name}' removed"

    def _run_container(self, command: str) -> str:
        import subprocess
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            raise DockerExecutionError(f"docker run failed: {result.stderr.strip()}")
        return result.stdout.strip() or "Container started"

    def _update_container(self, command: str) -> str:
        import subprocess
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise DockerExecutionError(f"docker update failed: {result.stderr.strip()}")
        return result.stdout.strip() or "Container updated"

    def _get_logs(self, parts: list[str]) -> str:
        container_name = parts[-1]
        container = self.docker_client.containers.get(container_name)
        logs = container.logs(tail=50).decode("utf-8", errors="replace")
        return logs

    def check_connection(self) -> bool:
        """Test Docker daemon connectivity."""
        try:
            if self.docker_client:
                self.docker_client.ping()
                return True
        except Exception:
            pass
        return False


class DockerExecutionError(Exception):
    """Raised when a Docker command execution fails."""
    pass
