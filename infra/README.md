# Scheduled deployment -- targeted entity research

Terraform in this directory provisions a GCP Cloud Run Job that runs
`scripts/03_targeted_entity_research.py`, plus a Cloud Scheduler cron
trigger, matching the `0 6 * * *` schedule the script's own module docstring
already proposed. See the repo root `Dockerfile` for the image and
`deploy.sh` for the build+push+apply wrapper.

## What gets created

| Resource | Purpose |
|---|---|
| `google_cloud_run_v2_job.targeted_research` | Runs the container. `parallelism=1`, `task_count=1` (see caveat below). |
| `google_cloud_scheduler_job.daily_trigger` | Fires the job daily via the Cloud Run Admin API. |
| `google_service_account.job_runtime` | Identity the job executes as. Secret Manager access to `GEMINI_API_KEY` + (if enabled) Vertex AI + the state bucket. Nothing else. |
| `google_service_account.scheduler_invoker` | Identity Cloud Scheduler uses to call the job. Only `roles/run.invoker` on that one job. |
| `google_secret_manager_secret.gemini_api_key` (optional, `create_secret=true`) | Container for the API key. Terraform never writes the value. |
| `google_storage_bucket.state` (optional, `create_state_bucket=true`) | Persists the job's local SQLite working DB + exported JSON snapshot across scheduled runs. Also backs the overlap-guard lock file (see caveat below). |
| `google_monitoring_notification_channel.job_failure_email` / `google_monitoring_alert_policy.job_execution_failed` (optional, `notification_email` set) | Emails `var.notification_email` when an execution logs an ERROR-severity entry, so a failed scheduled run doesn't silently go unnoticed. |

## First-time setup

1. `gcloud auth login` and `gcloud auth application-default login` against
   the target project.
2. Create the Artifact Registry repo the image will live in (once):
   ```
   gcloud artifacts repositories create story-graph \
     --repository-format=docker --location=<region> --project=<project_id>
   ```
3. `cp terraform.tfvars.example terraform.tfvars` and fill in `project_id`
   (and `image`, though `deploy.sh` passes `-var=image=...` itself so you
   can leave it out of `terraform.tfvars` if you always use `deploy.sh`).
4. From the repo root: `PROJECT_ID=<project_id> ./deploy.sh apply`.
5. **Add the actual `GEMINI_API_KEY` value** (Terraform only creates the
   empty secret container):
   ```
   printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add \
     GEMINI_API_KEY --project=<project_id> --data-file=-
   ```
   Or reuse the key already documented in the repo root README (Secret
   Manager, `aiqa-coaching` / `quantum-aikido-coaching` projects) by setting
   `create_secret = false` and `gemini_secret_id =
   "projects/<num>/secrets/GEMINI_API_KEY"` in `terraform.tfvars` instead of
   creating a new one.
6. Trigger a first run without waiting for 06:00 UTC:
   `terraform output manual_run_command` prints the exact `gcloud run jobs
   execute ...` command, or use the Cloud Console.
7. **Set `notification_email` in `terraform.tfvars`** to get emailed when a
   scheduled execution fails (see `terraform.tfvars.example`). Left unset,
   no alert policy or notification channel is created at all -- a failed
   run would only show up as a "Failed" row in Cloud Run's execution
   history and a traceback in Cloud Logging, with nothing pushed to you.

## Known limitations -- read before relying on this unattended

This was built and validated **without live GCP credentials**, across two
sessions, neither with network access to `registry.terraform.io` (the
second attempt got an outright 403 rather than a timeout, so `terraform
validate`/`init` could not be re-run at all for this round of fixes --
only `terraform fmt -check` ran, and it's clean). The Dockerfile was built
and smoke-tested locally in the first session (`--dry-run` and
`--skip-search` both ran correctly inside the built image). Nothing here
has been applied against a real project, and none of the following has
been exercised end-to-end against live GCP:

- **`terraform plan`/`apply` themselves**, including the new
  `google_monitoring_notification_channel`/`google_monitoring_alert_policy`
  resources -- these parse and format cleanly but have not been through
  `terraform validate` (needs the `hashicorp/google` provider schema,
  which this session couldn't fetch) or a real `apply`. Double-check the
  `condition_matched_log` block's filter syntax and the alert policy
  schema against the provider docs before trusting it silently.
- **The GCS state-bucket volume mount actually working under
  `EXECUTION_ENVIRONMENT_GEN2`** -- the Terraform for it is written per
  the documented Cloud Run v2 Job schema, but was never applied.
- **Cross-project secret access**, if you set `create_secret = false` to
  point at the existing `aiqa-coaching`/`quantum-aikido-coaching` secret --
  Cloud Run v2's cross-project `secretKeyRef` support should work per
  Google's docs but was not exercised here.
- **Vertex AI fallback actually firing from inside the job** on a real 429 --
  `enable_vertexai_fallback` wires the IAM role and env vars (now including
  `GEMINI_VERTEXAI_MODEL`, previously missing -- see below), but the
  free-tier-exhausted-then-falls-back-to-paid path itself was only
  exercised previously via kkron's manual run (see
  `docs/targeted_research_validation_2026-08-23.md`), not from this
  container/job identity.
- **`deploy.sh`'s digest-resolution step**
  (`gcloud artifacts docker images describe ... --format='value(image_summary.digest)'`)
  -- logically sound and matches Google's documented output for that
  command, but has never actually been run against a real Artifact
  Registry repo.
- **The overlap-guard lock** (`scripts/_run_lock.py`, `JOB_LOCK_DIR`) --
  covered by unit tests against a plain local filesystem, but never
  exercised against the actual GCS FUSE-backed volume mount Cloud Run Jobs
  use, which may have different write/rename/exists semantics under
  concurrent access than a real POSIX filesystem.

**kkron: please run `terraform plan` (and then `apply`) yourself against
the real target project before trusting the daily schedule, and watch the
first couple of scheduled runs' logs -- and confirm you actually receive
the failure-alert email (e.g. by triggering a deliberate failure once).**

## Other things worth knowing going in

- **Concurrency: `parallelism=1`/`task_count=1` stops fan-out within one
  execution; the application-level lock stops overlap across executions.**
  Cloud Run Jobs have no native "reject if another execution is already
  running" switch, so if someone ran `gcloud run jobs execute` by hand
  while the 06:00 UTC scheduled run was still in flight, both would race
  the same Gemini free-tier quota at the GCP layer. `scripts/_run_lock.py`
  closes that gap: at startup the script acquires a marker-file lock in
  the mounted state bucket (`JOB_LOCK_DIR`, only set when
  `create_state_bucket=true`) and exits early (exit code 0, logged at
  WARNING so it doesn't trip the failure alert above) if another
  execution's lock is already held and not stale. A lock older than
  `lock_stale_after_seconds` (default 2 hours; `LOCK_STALE_SECONDS` env
  var) is treated as abandoned by a crashed/killed run and reclaimed, so a
  bad run can never permanently deadlock future scheduled runs. This is
  intentionally simple (a narrow check-then-create race remains, see the
  module docstring), not a distributed-systems-grade mutex -- adequate for
  this job's actual traffic (one daily cron trigger, plus rare manual
  runs). Without the state bucket (`create_state_bucket=false`) there is
  no shared directory to lock against, so locking is skipped entirely and
  this caveat still applies as before.
- **The tracked `graph_snapshot/` JSON source-of-truth does not round-trip
  back into git automatically.** The script's own docstring describes a
  workflow where a human reviews the script's output as a git diff and
  commits it as an MR. This infra does not build that automation -- the
  optional state bucket (`create_state_bucket`, on by default) only makes
  the job's *own* working state (SQLite DB + exported snapshot) persist
  across scheduled runs so daily convergence actually works in the cloud;
  it does not open an MR or push anything to GitLab. Turning a day's
  findings into a reviewed git commit is still a manual step (pull the
  exported JSONL from the bucket, diff against `graph_snapshot/`, commit)
  unless/until a follow-up automates that too.
- **Image tags:** `deploy.sh` builds/pushes `:latest` (for a stable,
  human-readable name in Artifact Registry), but after pushing it
  immediately resolves the pushed image's actual digest (`gcloud artifacts
  docker images describe ... --format='value(image_summary.digest)'`) and
  passes Terraform `-var=image=...@sha256:...` instead of the mutable tag
  string. This avoids the well-documented Cloud Run + Terraform footgun
  where a config pinned to `:latest` either shows a spurious diff every
  plan or silently fails to pick up a rebuild, depending on
  provider/API-version resolution behavior -- with the digest passed
  explicitly, each `./deploy.sh apply` is deterministic and a real image
  change is always visible in `terraform plan`. Re-run `./deploy.sh apply`
  (not just `docker push`) to roll the job onto a new build.
- **`GEMINI_VERTEXAI_MODEL` is now set** (previously missing): it defaults
  to the same value as `GEMINI_MODEL` (`var.gemini_model`, currently
  `gemini-3.6-flash` -- see `docs/targeted_research_validation_2026-08-23.md`
  on why `gemini-2.5-flash` 404s), via a separate `var.vertexai_model`
  override only if the free and paid tiers ever need to diverge. Leaving
  it unset previously meant `config/settings.py`'s stale
  `gemini-2.5-flash` default was used for the Vertex AI paid fallback --
  the exact mechanism meant to survive a free-tier 429 would likely have
  404'd too.
- **`CLOUDMANAGEMENT_*` cost-hub integration is left at its default
  (disabled)** -- this infra does not wire up the CloudManagement hub
  URL/token. It can be added later as additional secrets + env vars on the
  container if kkron wants to opt in from this deployment too.

## Follow-up recommendation not built here: local daily-quota short-circuit

The task that produced this deployment considered wiring
`src/llm/cost_tracker.py`'s `free_calls`/`paid_calls` counters into the
script's entrypoint so a run could detect "the free-tier quota is already
known exhausted from an earlier run today" and skip Phase 2 early instead
of hitting 429 again. This was **not** implemented, because it isn't
actually a small wiring change given the current code:

- `GeminiCostTracker`'s counters (`src/llm/cost_tracker.py`) are per-process,
  reset on every run, and only populated when `CLOUDMANAGEMENT_ENABLED=true`
  (opt-in, off by default) -- there is no local persistence today that
  would let a later run know an earlier run already exhausted the free
  tier.
- `TieredGeminiClient`'s own `free_calls`/`free_keys_exhausted` counters
  (`src/llm/gemini_client.py`) are the ones actually populated by default,
  and are equally in-memory-only, per-run.
- A real "skip early" feature needs a small persisted state file (e.g.
  `data/.free_quota_state.json`, git-ignored, dated to the calendar day)
  written when `TieredGeminiClient.stats()['free_keys_exhausted'] ==
  free_keys_total`, checked at the top of `main()`, with UTC-day-rollover
  handling and its own test coverage.

This is a reasonable, appropriately small follow-up -- but it's a new
persistence mechanism, not just "read an existing counter," so it's called
out here rather than bundled into this infra change.
