# Runbook: Bad Deployment / Rollback

## Symptoms
- Errors started immediately after or shortly after a deployment
- Specific endpoints failing while others work fine
- Error messages reference new code paths (e.g., `checkout_v2.js`)
- Monitoring shows success rate drop correlated with deploy timestamp

## Diagnosis Checklist
1. Correlate error start time with deployment timestamp
2. Identify which endpoints are affected vs. unaffected
3. Check error stack traces for new file/function names
4. Review deployment diff for breaking changes

## Remediation Steps

### Fix 1: Roll Back Deployment (MEDIUM RISK)
**When to use**: High confidence that the new deployment is the cause.
```bash
docker stop demo-app
docker rm demo-app
docker run -d --name demo-app -p 5050:5050 incident-demo-app:previous
```
- Estimated downtime: 1-2 minutes
- Rollback: Re-deploy the new version after fix

### Fix 2: Restart with Feature Flag Disabled (LOW RISK)
**When to use**: Issue is in a feature-flagged code path.
```bash
docker exec demo-app /bin/sh -c "echo 'FEATURE_NEW_CHECKOUT=false' >> /etc/app/.env"
docker restart demo-app
```
- Estimated downtime: < 30 seconds
- Rollback: Re-enable feature flag

### Fix 3: Hot-Patch the Container (HIGH RISK)
**When to use**: Only if rollback is not possible and fix is trivial.
```bash
docker exec demo-app sed -i 's/calculate_discount/calculateDiscount/g' /app/checkout_v2.js
docker restart demo-app
```
- Estimated downtime: < 30 seconds
- Rollback: Restart with original image
- **WARNING**: Modifying running container — changes lost on next deployment

## Prevention
- Always deploy behind feature flags for new functionality
- Implement canary deployments (10% traffic first)
- Add integration tests for critical paths (checkout, payment)
- Require manual approval for production deployments of high-risk changes
