# On-call runbook

What to do when something goes wrong. Written for a small team, so every step says exactly what to run.
Replace `PROJECT`, `REGION` and `ENV` (for example `staging`) with your values. Names follow `nguit-ENV-<service>`.

## First, the three switches

| I need to... | Do this |
| --- | --- |
| **Stop all calling** | Calling to real phones does not exist yet and `CALLING_ENABLED` is `false` in Terraform on purpose. If you add phone calling later, this command must work: `gcloud run services update nguit-ENV-gateway --region REGION --update-env-vars CALLING_ENABLED=false`. Browser demo calls cannot be switched off this way, so scale the gateway to zero instead (next row). |
| **Stop the voice gateway** | `gcloud run services update nguit-ENV-gateway --region REGION --min-instances 0 --max-instances 0` stops new calls at once. Restore with `--min-instances 1 --max-instances 3`. |
| **Go back to the last good version** | `PROJECT_ID=PROJECT infra/scripts/rollback.sh <web\|api\|gateway\|worker>` takes seconds. Database changes are not undone, by design. |

## Alerts, and what to do

### Calls are failing
More than 3 calls ended as `failed` in 15 minutes.
1. Open the dashboard tile **Call outcomes**. Is it one reason or many?
2. `gcloud logging read 'jsonPayload.event="call_ended" AND jsonPayload.status="failed"' --limit 20 --format='table(timestamp,jsonPayload.reason,jsonPayload.call_id)'`
3. Reasons you will see: `reconnect_failed` (Gemini or network), `no_consent` (an owner opted out mid-call, usually harmless), `internal_error` (a bug, read the matching error line), `disclosure_missing` (see below).
4. If the cause is Gemini (quota, outage), check the model id and quota in the console. The app falls back to `GEMINI_LIVE_FALLBACK_MODEL` by itself.
5. If a new release caused it, roll back the gateway.

### A call did not say it is an AI
**Treat this as serious.** The agent must say who is calling and that it is an AI at the start of every call. The gateway ends a call that does not.
1. Stop the voice gateway (above) until you understand why.
2. Check whether the prompt or the model id changed recently. Roll back if so.
3. Re-run the call tests before turning it back on (PRD: every prompt or model change must pass them).

### Owners are opting out
More than 5 opt-outs in an hour.
1. Read a few transcripts: `select call_id, speaker, text from transcript_segments where call_id in (...) order by offset_ms`.
2. Is the agent too pushy, calling at a bad time, or misunderstanding? Fix the instruction, test, release.
3. An opt-out is permanent and applies to every mover. That is correct. Do not reverse one by hand.

### A service is down, or there are server errors
1. Which service? The alert name says. Open Cloud Run > that service > **Logs**.
2. If it started right after a release, roll that service back.
3. If it is `api` and the logs mention the database, check **Database under pressure** and the SQL instance status.
4. The web app showing "We cannot reach the service" means the web app is up and the API is not.

### API is slow
95th percentile above 3 seconds for 10 minutes.
1. Check instance count on the dashboard. At the limit? Raise `max_instances` in Terraform (it also caps cost, so do it on purpose).
2. Check database CPU. Cloud SQL Query Insights shows the slowest queries.
3. Area ranking calls Google Maps and the model. A slow Maps response shows up here first.

### Database under pressure
- **CPU high:** look at Query Insights. Do not just buy a bigger machine; find the query. If it is genuinely load, raise `db_tier`.
- **Disk above 85%:** storage auto-grows, but find what is growing: `select relname, pg_size_pretty(pg_total_relation_size(oid)) from pg_class order by pg_total_relation_size(oid) desc limit 10`. Transcripts and the audit log grow fastest.

### Files were not deleted on time
The daily retention job could not delete a file. The next run retries it, so this is only urgent if it repeats for days.
1. `gcloud scheduler jobs run nguit-ENV-retention --location REGION` runs it now.
2. Check the worker logs for `retention_file_failed`. Usually a storage permission or a missing bucket.
3. Agreements are deleted after 90 days and call audio after 30. These are promises in the privacy notice, so do not let this stay broken.

## Data

### Someone asks us to delete their data
They can do it themselves: **Account > Delete my account and data**. It removes everything straight away.
If they cannot sign in, use the same code the button uses:
```bash
# Point DATABASE_URL (and DOCUMENT_BUCKET / AUDIO_BUCKET) at the right environment first.
# For staging, connect through the Cloud SQL Auth Proxy.
python scripts/delete_account.py --email their@email --confirm DELETE
```
It removes their plans, calls, transcripts, facts, agreements, files and audio, and says what it deleted. Running it twice is harmless. Never delete rows by hand in other tables, or files will be orphaned (the daily job would catch them, but do not rely on that). The audit log keeps a record with no personal data.

### Restoring the database
Backups run daily, with point-in-time recovery for 7 days.
```bash
# Clone to a new instance at a moment in time. Does not touch the live one.
gcloud sql instances clone nguit-ENV-db nguit-ENV-db-restore --point-in-time 2026-01-01T10:00:00Z
```
Check the clone, then point the `database-url` secret at it, or copy the data back. **Practise this once before you need it** (PRD production checklist: one tested restore).

### Rotating a secret
`printf 'NEW_VALUE' | gcloud secrets versions add nguit-ENV-google-api-key --data-file=-`, then deploy any new revision (or `gcloud run services update ... --update-env-vars ROTATED=$(date +%s)`) so services pick up `latest`.
Do not rotate `phone-encryption-key` without a plan: stored phone numbers are encrypted with it and would become unreadable.

## Cost

- Budget alerts fire at 50%, 90%, 100% and on forecast, to the alert email.
- The database is the main fixed cost. To pause staging between uses: `gcloud sql instances patch nguit-ENV-db --activation-policy NEVER` (and `ALWAYS` to resume). Nothing works while it is stopped.
- Everything else scales to zero, except the voice gateway, which keeps one instance warm on purpose.

## Who to tell

Wrong or missing consent, a call that did not disclose it is an AI, or a complaint from a PG owner: stop calling first, then write down what happened, then fix it. The PRD's compliance gate lists the complaint process; keep it updated here.
