# Runbook: Out-of-Memory (OOM) Crash

## Symptoms
- HTTP 500 errors across multiple endpoints
- `OutOfMemoryError: Java heap space` or `GC overhead limit exceeded` in logs
- Heap usage consistently above 90%
- Increasing GC pause times

## Diagnosis Checklist
1. Confirm OOM errors in application logs
2. Check heap usage metrics (Grafana/CloudWatch)
3. Identify if memory leak is gradual or sudden
4. Check if a recent deployment introduced the issue

## Remediation Steps

### Fix 1: Restart Container (LOW RISK)
**When to use**: Immediate relief needed, root cause investigation can follow.
```bash
docker restart demo-app
```
- Estimated downtime: < 30 seconds
- Rollback: N/A (non-destructive)

### Fix 2: Roll Back to Previous Version (MEDIUM RISK)
**When to use**: OOM started after a specific deployment.
```bash
docker stop demo-app
docker run -d --name demo-app -p 5050:5050 incident-demo-app:previous
```
- Estimated downtime: 1-2 minutes
- Rollback: Re-deploy the new version

### Fix 3: Increase Memory Limit (MEDIUM RISK)
**When to use**: Application genuinely needs more memory, not a leak.
```bash
docker update --memory=4g --memory-swap=4g demo-app
docker restart demo-app
```
- Estimated downtime: < 30 seconds
- Rollback: Reset memory limit to original value

## Prevention
- Set up memory usage alerts at 70% and 85% thresholds
- Implement heap dump on OOM for post-incident analysis
- Add memory leak detection to CI/CD pipeline
- Consider horizontal scaling instead of vertical
