# Security & SOC 2 Control Notes

Document owner: Security
Effective: 2026-02-15
Control set: SOC2-2026

## Trust services

Northstar is in-scope for SOC 2 Type II (Security, Availability, Confidentiality). The audit window is February 1 through January 31. Evidence requests from the auditor go through the Security GRC channel, not through Engineering Slack DMs.

## Customer data at rest

Customer data at rest is stored in **RDS Postgres (encrypted with AWS KMS key alias/northstar-data)** in `us-east-1` only. Object storage for attachments is S3 bucket `northstar-customer-uploads` with default encryption SSE-KMS. Redis is cache-only: no customer PII in Redis. Logs in Datadog must be scrubbed of access tokens; the `pii-scrub` pipeline is mandatory on every new service.

Engineers must not copy production data to laptops. The approved path is a masked subset via the `prod-anonymizer` job.

## SOC 2 control exception

A **SOC2 exception** (also written **SOC 2 control exception**) is a documented, time-boxed deviation from a trust-services control. It is not a risk acceptance, and it is not a vendor shipping miss.

To file a SOC 2 control exception:

1. Open a ticket in Jira project **GRC** with type "Exception".
2. Name it with the control ID, e.g. `SOC2 exception CC6.1 — SSH bastion MFA bypass for vendor X`.
3. Include compensating controls, an expiry date (90 days max), and a Security approver.
4. The Security Director (currently Dana Okonkwo) is the only person who can approve a SOC 2 control exception. Engineering managers cannot.

Expired exceptions auto-fail the next control test. There is currently one open exception: **SOC2 exception CC7.2** — log retention on the legacy billing exporter is 14 days instead of 30, expires 2026-09-30, compensating control is a nightly S3 export to `northstar-log-archive`.

## Access reviews

Quarterly access reviews cover Okta, AWS IAM, GitHub org, and PagerDuty. Managers have 10 business days to certify. Uncertified accounts are revoked on day 11.

## Incident reporting

Suspected account compromise, malware, or data leakage: page Security on-call (`sec-primary`) immediately. Do not discuss suspected breaches in public Slack channels.
