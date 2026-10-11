# Runbook: Database Connection Failure

## Symptoms
- HTTP 503 errors on all database-dependent endpoints
- `Connection refused` or `Connection reset by peer` in logs
- Connection pool exhausted (0 idle connections)
- Failover to replica also failing

## Diagnosis Checklist
1. Verify database server is running: `docker ps | grep postgres`
2. Check network connectivity: `docker exec demo-app ping db-primary.internal`
3. Check database logs for crash or shutdown events
4. Verify connection pool configuration (max connections, timeout)

## Remediation Steps

### Fix 1: Restart Database Container (MEDIUM RISK)
**When to use**: Database process has crashed or become unresponsive.
```bash
docker restart demo-db
```
- Estimated downtime: 1-2 minutes (database recovery)
- Rollback: Check database integrity after restart

### Fix 2: Restart Application to Reset Connection Pool (LOW RISK)
**When to use**: Database is healthy but app's connection pool is corrupted.
```bash
docker restart demo-app
```
- Estimated downtime: < 30 seconds
- Rollback: N/A (non-destructive)

### Fix 3: Kill and Recreate Database Container (HIGH RISK)
**When to use**: Last resort when database is in an unrecoverable state.
```bash
docker stop demo-db
docker rm demo-db
docker run -d --name demo-db -e POSTGRES_PASSWORD=secret -p 5432:5432 postgres:15
```
- Estimated downtime: 5-10 minutes
- Rollback: Restore from backup
- **WARNING**: Data loss possible if volume is not mounted

## Prevention
- Configure connection pool health checks (validation query)
- Set up database monitoring with automatic failover
- Implement circuit breaker pattern in application
- Regular database health checks every 30 seconds
