"""Deterministic, realistic mock responses for testing, benchmarks, and offline demo execution.

Covers:
- oom_crash
- db_connection_failure
- bad_deploy
- live_container
"""

from __future__ import annotations

import json
from typing import Any


def get_mock_response(system_prompt: str, user_message: str) -> dict[str, Any] | str:
    """Generate realistic mock data based on agent persona and scenario detected in user_message."""
    msg_lower = user_message.lower()
    prompt_lower = system_prompt.lower()

    is_oom = "outofmemory" in msg_lower or "oom" in msg_lower or "heap" in msg_lower
    is_db = "postgresql" in msg_lower or "connection refused" in msg_lower or "db-pool" in msg_lower or "hikaripool" in msg_lower or "5432" in msg_lower
    is_deploy = "deploy" in msg_lower or "checkout_v2" in msg_lower or "calculate_discount" in msg_lower or "v2.4.1" in msg_lower

    # 0. Single-Prompt Baseline (for evaluation benchmark)
    if "do everything" in prompt_lower or "1. identify the root cause." in prompt_lower or "single-prompt" in prompt_lower:
        if is_oom:
            rc = "Java heap space OutOfMemoryError in UserService"
            cmds = ["docker restart demo-app", "docker rm -f demo-app"]
            pm = "Incident Postmortem: OOM Error\nThe server ran out of memory. We restarted it and force removed old temporary containers. Action item: monitor memory."
        elif is_db:
            rc = "PostgreSQL database connection refused on port 5432"
            cmds = ["docker restart demo-app", "docker exec demo-app drop database if exists temp"]
            pm = "Incident Postmortem: DB Connection Dropped\nDatabase connections refused. Restarted container. Action item: check DB server."
        else:
            rc = "Deployment v2.4.1 caused TypeError in checkout calculation"
            cmds = ["docker restart demo-app", "docker exec demo-app sed -i s/calculate_discount/noop/g /app/checkout_v2.js"]
            pm = "Incident Postmortem: Deploy Bug\nBad release caused 500 errors. Modified container in place. Action item: test before deploying."
        return {
            "root_cause": rc,
            "commands": cmds,
            "postmortem": pm,
        }

    # 1. Log Analyst
    if "log analysis expert" in prompt_lower or "error_types" in prompt_lower:
        if is_oom:
            return {
                "error_types": ["OutOfMemoryError: Java heap space", "GC overhead limit exceeded", "HealthCheckFailed"],
                "error_count": 14,
                "first_error_at": "2026-10-08T02:12:45Z",
                "last_error_at": "2026-10-08T02:15:03Z",
                "timeline": [
                    {"timestamp": "2026-10-08T02:11:00Z", "event": "Heap usage at 78% (1.56GB / 2.0GB)", "severity": "WARN"},
                    {"timestamp": "2026-10-08T02:12:15Z", "event": "GC pause spiked to 450ms exceeding threshold", "severity": "WARN"},
                    {"timestamp": "2026-10-08T02:12:46Z", "event": "java.lang.OutOfMemoryError in UserService.loadAllUsers", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T02:13:32Z", "event": "GC overhead limit exceeded during request processing", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T02:14:01Z", "event": "Health check FAILED for web-server (attempt 1/3)", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T02:15:01Z", "event": "Service web-server marked UNHEALTHY after 3 consecutive failures", "severity": "FATAL"},
                    {"timestamp": "2026-10-08T02:15:03Z", "event": "Removed web-server from load balancer rotation", "severity": "ERROR"},
                ],
                "affected_services": ["web-server", "health-checker", "load-balancer"],
                "summary": "The web-server container suffered memory exhaustion due to unbounded memory allocation in UserService.loadAllUsers, leading to persistent OutOfMemoryError exceptions, failed health checks, and removal from the load balancer rotation.",
            }
        elif is_db:
            return {
                "error_types": ["PSQLException: Connection refused", "SQLTransientConnectionException", "PoolExhaustionError"],
                "error_count": 18,
                "first_error_at": "2026-10-08T04:21:30Z",
                "last_error_at": "2026-10-08T04:24:02Z",
                "timeline": [
                    {"timestamp": "2026-10-08T04:20:10Z", "event": "Database pool connections normal: 8/20 active", "severity": "INFO"},
                    {"timestamp": "2026-10-08T04:21:00Z", "event": "Checkout time 850ms exceeded threshold", "severity": "WARN"},
                    {"timestamp": "2026-10-08T04:21:30Z", "event": "Connection refused to db-primary.internal:5432", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T04:21:46Z", "event": "Connection pool completely exhausted (20/20 active, 0 idle)", "severity": "WARN"},
                    {"timestamp": "2026-10-08T04:22:30Z", "event": "Evicted 5 dead connections with Connection reset by peer", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T04:23:02Z", "event": "Automated failover to replica db-replica also failed", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T04:24:01Z", "event": "api-gateway marked DEGRADED as database backend unreachable", "severity": "FATAL"},
                ],
                "affected_services": ["api-gateway", "db-pool", "health-checker"],
                "summary": "Primary PostgreSQL database backend became unreachable on port 5432, causing connection pool exhaustion in HikariPool, cascading 503 errors across customer API endpoints, and a failed replica failover.",
            }
        else:  # Bad deploy
            return {
                "error_types": ["TypeError: Cannot read properties of undefined", "EndpointFailure", "HighErrorRateAlert"],
                "error_count": 12,
                "first_error_at": "2026-10-08T09:03:00Z",
                "last_error_at": "2026-10-08T09:05:02Z",
                "timeline": [
                    {"timestamp": "2026-10-08T09:00:40Z", "event": "Deploy bot deployed container web-service:v2.4.1", "severity": "INFO"},
                    {"timestamp": "2026-10-08T09:00:51Z", "event": "Experimental flag FEATURE_NEW_CHECKOUT activated", "severity": "WARN"},
                    {"timestamp": "2026-10-08T09:01:05Z", "event": "Container started and passed initial health check", "severity": "INFO"},
                    {"timestamp": "2026-10-08T09:03:00Z", "event": "TypeError in CheckoutServiceV2.processPayment (calculate_discount undefined)", "severity": "ERROR"},
                    {"timestamp": "2026-10-08T09:04:16Z", "event": "Checkout endpoint error rate surged past 80%", "severity": "WARN"},
                    {"timestamp": "2026-10-08T09:05:00Z", "event": "Checkout success dropped from 99.8% to 16.7%", "severity": "WARN"},
                    {"timestamp": "2026-10-08T09:05:02Z", "event": "Critical revenue impact alert triggered: $2,400/hr estimated loss", "severity": "ERROR"},
                ],
                "affected_services": ["web-service", "checkout-api", "monitoring"],
                "summary": "Deployment v2.4.1 introduced a regression in CheckoutServiceV2 where 'calculate_discount' was referenced on an undefined object, causing >80% of checkout transactions to fail with 500 errors immediately after launch.",
            }

    # 2. Fix Proposer (check before Root Cause to avoid "root cause" substring collision!)
    if "fix-recommendation agent" in prompt_lower or "proposed_fixes" in prompt_lower:
        has_feedback = "rejected" in msg_lower or "feedback" in msg_lower or "alternative" in msg_lower

        if is_oom:
            return {
                "proposed_fixes": [
                    {
                        "id": 1,
                        "title": "Restart Container and Increase JVM Heap Limit",
                        "description": "Restart the demo-app container to release leaked memory and apply updated memory limits",
                        "commands": [
                            "docker restart demo-app",
                            "docker logs --tail 20 demo-app"
                        ],
                        "risk_level": "LOW",
                        "estimated_downtime": "< 10 seconds",
                        "rollback_plan": "If restart fails, run 'docker start demo-app' with previous configuration."
                    },
                    {
                        "id": 2,
                        "title": "Update Container Memory Allocation via Docker Update",
                        "description": "Dynamically increase container memory allocation from 2GB to 4GB to provide operational headroom",
                        "commands": [
                            "docker update --memory 4g --memory-swap 4g demo-app",
                            "docker restart demo-app"
                        ],
                        "risk_level": "MEDIUM",
                        "estimated_downtime": "< 15 seconds",
                        "rollback_plan": "docker update --memory 2g demo-app"
                    },
                    {
                        "id": 3,
                        "title": "Force Delete Container and Volume",
                        "description": "Aggressively remove container and destroy attached temporary data volumes",
                        "commands": [
                            "docker rm -f demo-app"
                        ],
                        "risk_level": "HIGH",
                        "estimated_downtime": "> 5 minutes",
                        "rollback_plan": "Rebuild container from docker-compose."
                    }
                ],
                "recommended_fix_id": 1 if not has_feedback else 2
            }
        elif is_db:
            return {
                "proposed_fixes": [
                    {
                        "id": 1,
                        "title": "Restart Application Container to Clear Dead Connection Pool",
                        "description": "Restart demo-app container to flush exhausted sockets and re-establish fresh pool connections",
                        "commands": [
                            "docker restart demo-app",
                            "docker logs --tail 20 demo-app"
                        ],
                        "risk_level": "LOW",
                        "estimated_downtime": "< 15 seconds",
                        "rollback_plan": "docker restart demo-app"
                    },
                    {
                        "id": 2,
                        "title": "Switch Database Endpoint to Standby Cluster",
                        "description": "Inject environment variable update directing container to secondary database cluster",
                        "commands": [
                            "docker exec demo-app sh -c 'export DB_HOST=db-standby.internal'",
                            "docker restart demo-app"
                        ],
                        "risk_level": "MEDIUM",
                        "estimated_downtime": "< 30 seconds",
                        "rollback_plan": "Revert DB_HOST to db-primary.internal and restart."
                    },
                    {
                        "id": 3,
                        "title": "Drop and Recreate Database Connection Tables",
                        "description": "Execute database drop table queries directly across connections",
                        "commands": [
                            "docker exec demo-app sh -c 'drop database if exists production;'"
                        ],
                        "risk_level": "HIGH",
                        "estimated_downtime": "Catastrophic data loss",
                        "rollback_plan": "Restore from yesterday's cold backup."
                    }
                ],
                "recommended_fix_id": 1 if not has_feedback else 2
            }
        else:  # Bad deploy
            return {
                "proposed_fixes": [
                    {
                        "id": 1,
                        "title": "Rollback Container Image to Stable Release v2.4.0",
                        "description": "Immediately revert container image tag to known-stable version v2.4.0 to restore checkout endpoint",
                        "commands": [
                            "docker restart demo-app",
                            "docker logs --tail 25 demo-app"
                        ],
                        "risk_level": "MEDIUM",
                        "estimated_downtime": "< 30 seconds",
                        "rollback_plan": "docker restart demo-app"
                    },
                    {
                        "id": 2,
                        "title": "Disable Experimental Feature Flag via Environment Variable",
                        "description": "Keep v2.4.1 running but turn off FEATURE_NEW_CHECKOUT to fallback to v1 checkout logic",
                        "commands": [
                            "docker restart demo-app",
                            "docker logs --tail 25 demo-app"
                        ],
                        "risk_level": "LOW",
                        "estimated_downtime": "< 10 seconds",
                        "rollback_plan": "Re-enable flag if needed."
                    },
                    {
                        "id": 3,
                        "title": "Purge Checkout Tables and Hot-patch Code in Container",
                        "description": "Directly edit production files inside running container without version control",
                        "commands": [
                            "docker exec demo-app sh -c 'sed -i s/calculate_discount/noop/g /app/checkout_v2.js'"
                        ],
                        "risk_level": "HIGH",
                        "estimated_downtime": "Unpredictable state drift",
                        "rollback_plan": "None."
                    }
                ],
                "recommended_fix_id": 1 if not has_feedback else 2
            }

    # 3. Root Cause Analyst
    if "senior sre diagnosing" in prompt_lower or "alternative_causes" in prompt_lower or "root-cause" in prompt_lower:
        if is_oom:
            return {
                "root_cause": "Java Virtual Machine heap memory exhaustion caused by unbounded data fetching in UserService.loadAllUsers()",
                "confidence": 0.94,
                "evidence": [
                    "Repeated java.lang.OutOfMemoryError: Java heap space thrown at UserService.java:142",
                    "Heap usage progressively climbed from 78% (1.56GB) to 98% (1.96GB) before crash",
                    "GC overhead limit exceeded indicating the JVM spent >98% CPU time in garbage collection with <2% heap reclaimed",
                    "Container removed by health checker after 3 consecutive health check timeouts",
                ],
                "alternative_causes": [
                    {
                        "cause": "External memory leak in native libraries or JVM buffer pools",
                        "confidence": 0.20,
                        "why_less_likely": "Stack trace explicitly isolates java.lang.OutOfMemoryError: Java heap space to UserService.loadAllUsers, pointing to application heap data rather than native memory.",
                    }
                ],
                "category": "resource_exhaustion",
            }
        elif is_db:
            return {
                "root_cause": "Primary PostgreSQL database process unreachable on port 5432, exhausting application connection pools and triggering cascading 503 errors",
                "confidence": 0.92,
                "evidence": [
                    "Direct PSQLException: Connection refused to db-primary.internal:5432",
                    "HikariPool pool exhaustion (20/20 active connections locked waiting on socket I/O)",
                    "Connection reset by peer during connection eviction",
                    "Secondary failover replica also refused connections",
                ],
                "alternative_causes": [
                    {
                        "cause": "Network partitioning or firewall rule misconfiguration between API gateway and DB subnet",
                        "confidence": 0.30,
                        "why_less_likely": "Connection refused typically signifies the port is closed or the daemon is not running, rather than packet dropping seen in network partitions.",
                    }
                ],
                "category": "dependency",
            }
        else:  # Bad deploy
            return {
                "root_cause": "Runtime regression in v2.4.1 due to null pointer exception in CheckoutServiceV2 calling calculate_discount on undefined pricing context",
                "confidence": 0.97,
                "evidence": [
                    "TypeError: Cannot read properties of undefined (reading 'calculate_discount') in checkout_v2.js:87",
                    "Issue started immediately after deploy-bot activated container v2.4.1 at 09:00:40Z",
                    "Only /api/checkout failed (80%+ error rate); other endpoints (/api/products, /api/users) remained 200 OK",
                    "FEATURE_NEW_CHECKOUT flag was enabled as part of v2.4.1 deployment",
                ],
                "alternative_causes": [
                    {
                        "cause": "Database schema mismatch following migration 0042_add_checkout_v2_tables.sql",
                        "confidence": 0.15,
                        "why_less_likely": "Error is an in-memory JavaScript TypeError before database query execution occurs.",
                    }
                ],
                "category": "deployment",
            }

    # 4. Safety Checker
    if "safety gate" in prompt_lower or "safety checker" in prompt_lower or "evaluations" in prompt_lower:
        evaluations = [
            {
                "fix_id": 1,
                "risk_classification": "LOW" if not is_deploy else "MEDIUM",
                "reasoning": "Restarting container uses standard stateless restart semantics with minimal downtime." if not is_deploy else "Rolling back an image tag modifies the active running version; requires operational confirmation to ensure database migrations remain backwards compatible.",
                "potential_impact": "Brief request interruption under 15 seconds." if not is_deploy else "Temporary interruption during container swap; checkout transactions will recover.",
                "safeguards_present": True
            },
            {
                "fix_id": 2,
                "risk_classification": "MEDIUM" if not is_deploy else "LOW",
                "reasoning": "Modifying runtime memory allocation or feature flags changes operational profile." if not is_deploy else "Graceful restart and feature flag toggle is non-destructive.",
                "potential_impact": "Host memory pressure if overallocated." if not is_deploy else "Brief container restart pause.",
                "safeguards_present": True
            },
            {
                "fix_id": 3,
                "risk_classification": "HIGH",
                "reasoning": "REJECTED: Destructive action that risks data loss, unversioned in-place tampering, or service deletion.",
                "potential_impact": "Irreversible data destruction or outage extension.",
                "safeguards_present": False
            }
        ]

        if is_deploy:
            approved_fix_id = 1
            approved_fix = {
                "id": 1,
                "title": "Rollback Container Image to Stable Release v2.4.0",
                "description": "Immediately revert container image tag to known-stable version v2.4.0 to restore checkout endpoint",
                "commands": [
                    "docker restart demo-app",
                    "docker logs --tail 25 demo-app"
                ],
                "risk_level": "MEDIUM",
                "estimated_downtime": "< 30 seconds",
                "rollback_plan": "docker restart demo-app"
            }
            requires_human_approval = True
        else:
            approved_fix_id = 1
            approved_fix = {
                "id": 1,
                "title": "Restart Container and Flush System State",
                "description": "Restart the demo-app container to release leaked memory / reset pool sockets",
                "commands": [
                    "docker restart demo-app",
                    "docker logs --tail 20 demo-app"
                ],
                "risk_level": "LOW",
                "estimated_downtime": "< 10 seconds",
                "rollback_plan": "docker start demo-app"
            }
            requires_human_approval = False

        return {
            "evaluations": evaluations,
            "approved_fix_id": approved_fix_id,
            "approved_fix": approved_fix,
            "requires_human_approval": requires_human_approval,
            "rejection_reasons": ["Fix #3 was REJECTED outright due to HIGH risk classification (destructive operations / data loss hazard)."]
        }

    # 5. Postmortem Writer
    if "postmortem" in prompt_lower or "technical writer" in prompt_lower:
        scenario_title = "OutOfMemory Heap Exhaustion Outage" if is_oom else ("Database Backend Connection Failure" if is_db else "Checkout Service Regression post-v2.4.1 Deploy")
        return f"""# Incident Postmortem: {scenario_title}

## Summary
On October 8, 2026, our automated incident response system detected and remediated a critical production degradation affecting the `demo-app` service. The incident initiated at approximately 02:12 UTC and was fully resolved within 4 minutes following autonomous agent diagnosis, safety gate verification, and targeted runbook execution.

## Impact
- **Services Affected:** `demo-app` (core API endpoints)
- **Duration:** 3 minutes 48 seconds
- **User Impact:** Approximately 120 customer requests experienced 500/503 errors during peak failure window. Zero permanent data loss occurred.
- **SLA Violation:** Minor transient error rate breach (resolved before triggering secondary pager escalation).

## Timeline
- **02:10:00 UTC** — Service operating under baseline load; normal response latencies observed (<50ms).
- **02:11:00 UTC** — Log Analyst flagged warning: resource pressure indicators exceeding warning thresholds.
- **02:12:46 UTC** — First fatal application failure recorded; health check probe failed (1/3).
- **02:14:01 UTC** — Service marked UNHEALTHY by internal health monitor and pulled from traffic rotation.
- **02:14:30 UTC** — Multi-agent incident pipeline triggered; Root Cause Analyst isolated fault to high-confidence root cause.
- **02:14:45 UTC** — Fix Proposer recommended automated remediation; Safety Checker validated commands and rejected hazardous alternatives.
- **02:15:05 UTC** — Runbook Executor ran approved recovery sequence against container `demo-app`.
- **02:15:20 UTC** — Container restored to healthy state; health check returned 200 OK. Load balancer traffic re-enabled.

## Root Cause
{"The root cause was JVM heap exhaustion in UserService.loadAllUsers() triggered by an unpaginated database fetch under concurrent load, leading to excessive GC pauses and OutOfMemoryError exceptions." if is_oom else ("The root cause was an unhandled connection drop to the primary PostgreSQL instance on port 5432, which exhausted HikariPool connection slots and stalled incoming HTTP requests." if is_db else "The root cause was a software regression in deployment v2.4.1 where CheckoutServiceV2 attempted to invoke calculate_discount on an undefined object when feature flag FEATURE_NEW_CHECKOUT was enabled.")}

## Resolution
The approved remediation plan was executed:
1. Validated that fix was classified safely by the Safety Checker agent.
2. Executed container restart and state reset commands against `demo-app`.
3. Verified container health endpoints (`/health`) returned HTTP 200 OK with memory pressure normalized.

## Lessons Learned
- **What went well:** The multi-agent pipeline identified the root cause in under 15 seconds, and the Safety Checker successfully filtered out dangerous destructive commands.
- **What went poorly:** Monitoring alerts fired after user requests had already begun failing rather than proactively on memory/pool saturation slopes.
- **Where we got lucky:** The failure occurred when redundant replicas were able to absorb partial traffic, and rollback commands executed without delay.

## Action Items
1. **[TODO - SRE Team]** [P1] Implement strict query pagination and memory caps on the UserService data layer.
2. **[TODO - Infrastructure]** [P1] Configure automatic container restart limits and circuit breakers in Docker container daemon.
3. **[TODO - DevSecOps]** [P2] Add automated pre-deployment regression integration tests for critical business endpoints.

---
*Generated by Incident Response Room — AI Postmortem System*"""

    # 6. Status Communicator
    if "status communicator" in prompt_lower or "communications specialist" in prompt_lower:
        return ("UPDATE: Our engineering team has identified and resolved the issue impacting our demo application. "
                "All services have been restored to full functionality, and our automated health checks indicate normal response times. "
                "We are actively monitoring traffic and will follow up with a complete technical postmortem. "
                "Thank you for your patience.")

    # Generic fallback
    return {
        "status": "success",
        "message": "Processed by incident agent",
    }
