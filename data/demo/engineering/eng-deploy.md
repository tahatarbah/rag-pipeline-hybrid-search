# Production deploy policy

Document owner: Platform Engineering
Effective: 2026-02-01
Policy ID: DEPLOY-7

## When you may deploy

Production deploys are allowed **Monday–Thursday, 14:00–20:00 UTC**. No production deploys on Friday, weekends, or company holidays unless a SEV-1 is in progress.

## How to deploy

1. Open a pull request with at least one reviewer who is not the author.
2. CI must be green on `main`.
3. Use the Argo CD application for the service. Do not kubectl-apply in prod.
4. After deploy, watch Grafana "prod-golden-signals" for 15 minutes.

## Rollback

If error rate exceeds 2% or p95 latency doubles versus the prior hour, the on-call **must** roll back. Do not wait for the change author. Rollback is the previous Argo CD revision, not a forward fix, unless the previous revision is known-bad.

## Feature flags

Risky behavior ships behind a flag in LaunchDarkly. Default new flags to off. The on-call can disable a flag without a deploy.
