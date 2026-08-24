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
| `google_storage_bucket.state` (optional, `create_state_bucket=true`) | Persists the job's local SQLite working DB + exported JSON snapshot across scheduled runs. |

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

## Known limitations -- read before relying on this unattended

This was built and validated **without live GCP credentials** in the
session that wrote it. `terraform validate` passes and the Dockerfile was
built and smoke-tested locally (`--dry-run` and `--skip-search` both ran
correctly inside the built image), but nothing here has been applied
against a real project, and none of the following has been exercised
end-to-end against live GCP:

- **`terraform plan`/`apply` themselves** -- validated for syntax and
  internal consistency only (`terraform validate`); the actual GCP API
  calls (service enablement, IAM propagation, Cloud Run Job creation,
  Scheduler->Job invocation) still need a real run against a real project.
- **The GCS state-bucket volume mount actually working under
  `EXECUTION_ENVIRONMENT_GEN2`** -- the Terraform for it is written per
  the documented Cloud Run v2 Job schema, but was never applied.
- **Cross-project secret access**, if you set `create_secret = false` to
  point at the existing `aiqa-coaching`/`quantum-aikido-coaching` secret --
  Cloud Run v2's cross-project `secretKeyRef` support should work per
  Google's docs but was not exercised here.
- **Vertex AI fallback actually firing from inside the job** on a real 429 --
  `enable_vertexai_fallback` wires the IAM role and env vars, but the
  free-tier-exhausted-then-falls-back-to-paid path itself was only
  exercised previously via kkron's manual run (see
  `docs/targeted_research_validation_2026-08-23.md`), not from this
  container/job identity.

**kkron: please run `terraform plan` (and then `apply`) yourself against
the real target project before trusting the daily schedule, and watch the
first couple of scheduled runs' logs.**

## Other things worth knowing going in

- **Concurrency really means "1 task per execution," not "1 execution ever."**
  Cloud Run Jobs have no native "reject if another execution is already
  running" switch. `parallelism=1`/`task_count=1` guarantees a single
  execution never fans the script out into parallel copies competing for
  the same Gemini free-tier quota, but if someone runs `gcloud run jobs
  execute` by hand while the 06:00 UTC scheduled run is still in flight,
  GCP will not stop that -- both would run. In practice the only thing
  that fires the job on a schedule is the one Cloud Scheduler cron job
  below, so this is a manual-collision risk only, not a scheduling one.
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
- **Image tags:** `deploy.sh` always builds/pushes `:latest` and the
  Cloud Run Job pins whatever `:latest` resolved to at `apply` time (Cloud
  Run Jobs pin by digest under the hood). Re-run `./deploy.sh apply` after
  pushing a new image to roll the job onto it -- pushing `:latest` alone
  does not update a job that's already been applied.
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
