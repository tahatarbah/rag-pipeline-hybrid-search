# Engineering On-Call SOP

Document owner: Platform Engineering
Effective: 2026-03-01
Runbook ID: ENG-ONCALL-4

## Who is on-call

Northstar runs a primary + secondary on-call rotation for production. The **primary on-call** is the engineer whose PagerDuty schedule is "prod-primary". The **secondary on-call** is "prod-secondary" and steps in if the primary does not ack within 10 minutes.

The current rotation is weekly, Monday 10:00 UTC. Handoff happens in #oncall-handoff with a written summary of open incidents (SEV-1 and SEV-2 only).

## Severity ladder

Use this ladder; do not invent extra levels.

- **SEV-1**: Customer-facing outage or data loss. Page primary and secondary. Incident commander is the primary unless they hand off. Target ack: 5 minutes. Public status page update within 15 minutes.
- **SEV-2**: Major degradation (elevated error rate, a single region down, payments delayed). Page primary. Target ack: 10 minutes.
- **SEV-3**: Minor impact, workaround exists. Slack #eng-incidents, no page. Ticket in Jira under OPS.
- **SEV-4**: Cosmetic or internal-only. Ticket only.

## First 15 minutes

1. Ack the page in PagerDuty.
2. Join the Zoom bridge linked in the PagerDuty note (default: "Northstar IR bridge").
3. Check Grafana dashboard "prod-golden-signals" and the last deploy in Argo CD.
4. If the last deploy is under 60 minutes old and golden signals are red, roll back. Do not wait for the author.
5. Declare severity in #eng-incidents using the template: `SEV-x | service | symptom | IC @name`.

## Escalation

If a SEV-1 lasts more than 30 minutes, page the **incident commander backup** (the Platform EM on the "ic-backup" schedule) and notify #exec-airgap with a one-line impact statement. Customer-data questions during an incident go to the Security on-call, not to Legal.

## After-incident

SEV-1 and SEV-2 require a written postmortem in `docs/postmortems/` within 3 business days. The blameless template lives in the Engineering Handbook. Action items must have an owner and a date; "investigate later" is not an acceptable owner.
