# Staging infrastructure

Terraform for Google Cloud, **staging only** for now. Production is the same module with different values, added later.

> **Nothing here has been applied.** It was checked with `terraform validate` and with tests that tie it to the application code, but it has never run against a real Google Cloud project. Read the plan below, and apply only when you approve it.

## The plan to approve

Everything lives in one Google Cloud project that you create for staging. `terraform apply` will create these:

| Group | What | Why it matters |
| --- | --- | --- |
| **Services** | 4 Cloud Run services: `web`, `api`, `voice-gateway`, `worker`, plus a `migrate` job | The app. The gateway keeps **1 instance warm** so a call never waits for a cold start. Everything else scales to zero. |
| **Database** | Cloud SQL PostgreSQL 16, smallest size (`db-f1-micro`), single zone. Daily backups, point-in-time recovery for 7 days, delete protection on | The **main fixed cost**. Reachable only through the Cloud SQL connector, with no authorised networks. |
| **Files** | 2 private buckets: agreements and call audio. No public access. **Soft delete off**, so deleted means deleted | Backstop deletion at 100 days (agreements) and 32 days (audio), behind the retention job's 90 and 30. |
| **Secrets** | 5 Secret Manager secrets. 3 are generated (database URL, session secret, phone-encryption key). 2 you fill in (Maps key, Gemini key) | Each service can read only the secrets it needs. |
| **Jobs** | A Cloud Tasks queue (1 call per second, 1 retry) and a daily Cloud Scheduler job at 03:30 India time that runs the retention cleanup | Pacing for call jobs later. Retention is your 90-day and 30-day promise. |
| **Monitoring** | 3 uptime checks, 10 alert policies, 5 log-based metrics, 1 dashboard, email notifications | Alerts for outages, server errors, slow API, database load, failing calls, opt-out spikes, a call that did not say it is an AI, and files that were not deleted. |
| **Budget** | Alerts at 50%, 90%, 100% and on forecast, if you give a billing account | Skipped if you leave the billing account empty. |
| **Delivery** | An Artifact Registry repository, 7 service accounts with narrow roles, and a keyless GitHub deploy identity limited to this repository's `main` branch | No keys are stored anywhere. |

What it will **not** do: it does not turn on real phone calls (`CALLING_ENABLED` is fixed to `false` in code, not a setting), it does not enable demo mode, and it does not create a production environment.

### Decisions I made for you, so you can change them

| Decision | Default | Why |
| --- | --- | --- |
| Region | `asia-south1` (Mumbai) | Close to Hyderabad. **Unverified:** whether the Gemini Live API is offered in this region. Check before relying on it. |
| Web, API and gateway are public | Yes | Browsers must reach them. Every API request still needs a signed-in session, and a call link works once. Tighten later with a load balancer if you want. |
| Worker is public | **No.** Only Cloud Scheduler and Cloud Tasks can call it | It can delete data. |
| Database size and availability | Smallest, single zone | Cheap for staging. Production should use `REGIONAL`. |
| Max instances | 3 per service | Also caps cost. |

## Before you apply

1. **A new Google Cloud project** for staging, with billing on. Keep it separate from production, which will get its own.
2. **A private bucket for Terraform's state.** The state holds the generated secrets, so nobody else may read it.
   ```bash
   gcloud storage buckets create gs://YOUR-STATE-BUCKET --location=asia-south1 \
     --uniform-bucket-level-access --public-access-prevention
   gcloud storage buckets update gs://YOUR-STATE-BUCKET --versioning
   ```
3. **Install** Terraform 1.9 or newer and the `gcloud` CLI. Sign in with an account that can create resources in the project (the Owner role is simplest for the first apply).
4. **Check pricing.** I have not verified current prices. The main drivers are Cloud SQL and the always-warm voice gateway instance. Use the Google Cloud pricing calculator with the table above, and set `budget_amount` to something you are happy to lose.
5. **Check your organisation policy** allows public Cloud Run services (`allUsers` as invoker). Some organisations block it, and the web app would not load.

## Apply, step by step

```bash
cd infra/envs/staging
cp terraform.tfvars.example terraform.tfvars      # fill in project_id and alert_email
cp backend.hcl.example backend.hcl                # fill in your state bucket
terraform init -backend-config=backend.hcl

# 1. Create only the registry and switch on the APIs, so there is somewhere to push images.
terraform apply \
  -target=module.platform.google_project_service.apis \
  -target=module.platform.google_artifact_registry_repository.main

# 2. Build and push the four images (from the repository root).
gcloud auth configure-docker asia-south1-docker.pkg.dev
PROJECT_ID=YOUR_PROJECT infra/scripts/build_push.sh latest

# 3. Review the full plan. THIS is the moment to approve or stop.
terraform plan -out=tfplan
terraform apply tfplan
```

Then:

```bash
# 4. Fill in the two secrets you hold. Until then, maps and AI features show a clear error.
printf '%s' 'YOUR_MAPS_KEY'   | gcloud secrets versions add nguit-staging-maps-api-key   --data-file=-
printf '%s' 'YOUR_GEMINI_KEY' | gcloud secrets versions add nguit-staging-google-api-key --data-file=-

# 5. Create the database tables.
gcloud run jobs execute nguit-staging-migrate --region asia-south1 --wait

# 6. Seed the sample areas and PGs (fake data only).  See "Seeding" below.
```

7. **Look at `terraform output computed_urls_match`.** The web app and the gateway use addresses computed from the project number. If any says `false`, or Terraform warns `service_urls_match`, the services cannot find each other. Fix `local.service_url` in `modules/platform/main.tf` to match the real addresses, then apply again.
8. Add three GitHub repository **variables**: `GCP_PROJECT_ID` (your project), and `GCP_WORKLOAD_IDENTITY_PROVIDER` and `GCP_DEPLOYER_SERVICE_ACCOUNT` (both printed by `terraform output deployer`). Create a GitHub environment named `staging` and require a reviewer, so a deploy waits for a person.
9. Open the web URL and sign in.

### Seeding

The seed script needs the database and the phone-encryption key. For staging, run it through the Cloud SQL Auth Proxy with the secrets fetched by hand. Only seed fake data into staging. Real PG data goes in through the owner consent flow, which is a pilot task.

## How deploys work

`deploy-staging.yml` runs after CI passes on `main` and a reviewer approves. For each service:
the new version gets **no traffic** and its own test URL, a smoke test hits it, then **10% of users** are sent to it for 3 minutes while the logs are watched for server errors. If there are none, it takes 100%. If there are any, traffic goes straight back. Database changes run first as a job and must also work with the old code (add first, remove in a later release).

```bash
PROJECT_ID=YOUR_PROJECT infra/scripts/rollback.sh api    # by hand, takes seconds
```

Terraform deliberately ignores the image and traffic split, so it never fights a deploy.

## Being able to trust it

| Check | Result |
| --- | --- |
| `terraform fmt` and `terraform validate` | Pass (in CI too) |
| 29 contract tests tying Terraform to the code | Pass. They check that health paths exist, environment variables are spelled the way the code reads them, buckets are private with real deletion, the worker is not public, no broad roles, services wait for their secrets, and alerts watch events the code really logs |
| `shellcheck` on the deploy scripts | Clean |
| **`terraform plan` and `apply` against a real project** | **Not done.** Needs your project |
| Canary deploy, rollback, scheduler, alerts, dashboard | **Never run.** Try them on staging with a harmless change |

Things I could not verify offline, and where to look first if the first apply fails:
- the deterministic Cloud Run addresses (step 7 above);
- `db-f1-micro` being offered for PostgreSQL 16 in your region;
- Cloud Scheduler and the Gemini Live API being available in `asia-south1`;
- the exact metric filters in the alert policies (open each alert after the first apply and check it shows data).

## Production later

Copy `envs/staging` to `envs/production` with a **separate project** and: `db_availability = "REGIONAL"`, `gateway_min_instances = 2`, `db_deletion_protection = true`, a real `billing_account`, and a custom domain with a load balancer. Do not enable real phone calls until the PRD's compliance gate is complete.
