"""Tests for DockerExecutor, command whitelist, and dry-run execution."""

import pytest
from agents.docker_executor import DockerExecutor
from agents.container_manager import ContainerManager


def test_dry_run_execution():
    executor = DockerExecutor(dry_run=True)
    fix = {
        "id": 1,
        "title": "Restart Container",
        "commands": ["docker restart demo-app", "docker logs --tail 20 demo-app"],
    }
    res = executor.execute_fix(fix)
    assert res.success is True
    assert res.dry_run is True
    assert len(res.commands_run) == 2
    assert "[DRY-RUN]" in res.outputs[0]


def test_command_whitelist_blocks_dangerous_unapproved_commands():
    executor = DockerExecutor(dry_run=True)
    fix = {
        "id": 2,
        "title": "Unapproved command",
        "commands": ["rm -rf /var/lib/docker", "docker restart demo-app"],
    }
    res = executor.execute_fix(fix)
    assert res.success is False
    assert "BLOCKED: Command not in allowlist" in res.error


def test_container_manager_crash_and_recover():
    cm = ContainerManager()
    # Trigger simulated crash
    ok, msg, log_path = cm.trigger_crash("oom_crash")
    assert ok is True
    assert cm.get_status()["crashed"] is True

    # Execute simulated recovery
    out = cm.execute_docker_command("docker restart demo-app")
    assert "restarted successfully" in out
    assert cm.get_status()["crashed"] is False
    assert cm.get_status()["health"] == "healthy"
