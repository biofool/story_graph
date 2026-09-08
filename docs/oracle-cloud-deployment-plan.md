# Oracle → GCP Cloud Deployment Plan (issue #18)

## Goal

Make the story_graph targeted-research pipeline deployable and triggerable
from the **Oracle host** via API, with **GCP doing all image construction**.

- **Oracle host** triggers builds and scrape runs via `gcloud` API calls
- **Google Cloud** handles all container image construction (Artifact Registry
  + Cloud Build) — no local docker on Oracle
- The deployed job runs `scripts/03_targeted_entity_research.py` on a schedule
  (Cloud Scheduler, daily 06:00 UTC) or on-demand via API

## Architecture

```
Oracle host (Always Free A1, ARM)            Google Cloud
┌─────────────────────────────┐      ┌──────────────────────────────────┐
│  gcloud CLI (no docker)     │      │  Cloud Build  ──►  Artifact Registry
│  scripts/oracle_trigger.sh  │ ───► │  (builds Dockerfile on GCP)        │
│                             │      │         │                          │
│  build  →  triggers build   │      │         ▼                          │
│  run    →  triggers job exec│ ───► │  Cloud Run Job (targeted-research) │
│  status→  checks exec status│ ◄─── │  runs 03_targeted_entity_research  │
└─────────────────────────────┘      │         ▲                          │
                                     │  Cloud Scheduler (0 6 * * * UTC)   │
                                     │  Secret Manager (GEMINI_API_KEY)   │
                                     │  GCS state bucket (graph snapshot) │
                                     └──────────────────────────────────┘
```

## What was implemented

### 1. GCP-side image construction — `cloudbuild.yaml`

A Cloud Build config at the repo root that builds the `Dockerfile` on
Google's infrastructure and pushes the image to Artifact Registry in one
step (Cloud Build authenticates to Artifact Registry automatically — no
`gcloud auth configure-docker` needed). It tags the image with both
`:latest` and `:$SHORT_SHA` for traceability and deterministic deploys.

### 2. Terraform for Cloud Build + Artifact Registry — `infra/cloudbuild.tf`

New Terraform resources (gated behind `enable_cloudbuild = true`):

| Resource | Purpose |
|---|---|
| `google_project_service.cloudbuild` | Cloud Build API |
| `google_project_service.artifactregistry` | Artifact Registry API |
| `google_artifacts_repository.story_graph` | Docker repo (replaces the manual `gcloud artifacts repositories create` step) |
| `google_service_account.cloudbuild_sa` | CI build identity |
| `google_artifacts_repository_iam_member.cloudbuild_writer` | Grant push access to the build SA |
| `google_cloudbuild_trigger.github_push` | (optional) push-to-`main` trigger — set `enable_github_trigger = true` |

New variables: `enable_cloudbuild`, `artifact_repo_name`,
`cloudbuild_image_name`, `enable_github_trigger`, `github_owner`,
`github_repo`, `github_branch`.

New outputs: `artifact_registry_repo`, `cloudbuild_trigger_name`,
`oracle_trigger_build_command`, `oracle_run_job_command`,
`oracle_run_status_command`.

### 3. Oracle-host trigger script — `scripts/oracle_trigger.sh`

A bash script the Oracle host runs (gcloud only, no docker):

- `build [--wait]` — triggers a GCP-side Cloud Build; with `--wait`,
  blocks until it completes
- `run` — triggers an on-demand Cloud Run Job execution
- `status` — shows the latest 5 job executions
- `all` — build (waiting) then run

### 4. This plan document

## Oracle host context

The Oracle host is the Always Free Ampere A1 ARM instance provisioned in
`CloudManagement/terraform-oracle/shared-a1.tf` (2 OCPU / 12 GB, aarch64).
It runs several Docker workloads (WorldStudioFinder, AIRichardMoon staging)
but for story_graph it acts purely as a **control plane** — it issues
`gcloud` API calls to GCP and never builds or runs the story_graph
container locally. The container runs as a Cloud Run Job on GCP.

## First-time setup

1. **Authenticate gcloud on the Oracle host** (once):
   ```
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project <PROJECT_ID>
   ```

2. **Provision the infrastructure** (from a machine with terraform, or
   eventually from Oracle once terraform is installed there):
   ```
   cp infra/terraform.tfvars.example infra/terraform.tfvars
   # Edit terraform.tfvars: set project_id, enable_cloudbuild = true
   # Optionally: enable_github_trigger = true, github_owner/repo/branch
   ./deploy.sh apply
   ```
   Or apply `infra/` directly:
   ```
   terraform -chdir=infra init
   terraform -chdir=infra apply -var=project_id=<PROJECT_ID> -var=enable_cloudbuild=true
   ```

3. **Add the GEMINI_API_KEY secret value** (Terraform only creates the
   empty container):
   ```
   printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add GEMINI_API_KEY --project=<PROJECT_ID> --data-file=-
   ```
   Or reuse the existing secret in `quantum-aikido-coaching` /
   `aiqa-coaching` by setting `create_secret = false` and
   `gemini_secret_id = "projects/<num>/secrets/GEMINI_API_KEY"`.

4. **Trigger the first build + run from Oracle**:
   ```
   PROJECT_ID=<PROJECT_ID> ./scripts/oracle_trigger.sh all
   ```

## Daily operation from the Oracle host

```
# Rebuild the image after a code push (GCP builds it, not Oracle)
PROJECT_ID=<PROJECT_ID> ./scripts/oracle_trigger.sh build --wait

# Trigger an on-demand scrape run
PROJECT_ID=<PROJECT_ID> ./scripts/oracle_trigger.sh run

# Check the latest run status
PROJECT_ID=<PROJECT_ID> ./scripts/oracle_trigger.sh status
```

The scheduled daily run (06:00 UTC) happens automatically via Cloud
Scheduler — no Oracle intervention needed.

## Remaining work (not yet implemented)

### Fix the Vertex AI `invalid_scope` OAuth error (requirement #5)

The paid-tier Vertex AI fallback fails with
`invalid_scope: Invalid OAuth scope or ID token audience provided` when
free-tier Gemini keys hit 429. This is an authentication issue, not an
infrastructure one. Likely fixes to investigate (in priority order):

1. **Application Default Credentials with the right scopes** — the Cloud
   Run Job's runtime SA (`story-graph-job-runtime`) is already granted
   `roles/aiplatform.user` when `enable_vertexai_fallback = true`. The
   `invalid_scope` error suggests the ADC token presented to the Vertex AI
   endpoint doesn't carry the `https://www.googleapis.com/auth/cloud-platform`
   scope. The Vertex AI client library should request this scope
   automatically when using ADC; verify the
   `TieredGeminiClient` (in `src/llm/`) is using
   `google.auth.default()` and the Vertex AI SDK rather than a manually
   constructed OAuth token.
2. **Ensure the aiplatform API is enabled** on `vertexai_project_id`
   (`google_project_service.aiplatform` is provisioned when
   `enable_vertexai_fallback = true`, but only on `var.project_id` — if
   `vertexai_project_id` differs, enable it there too).
3. **Verify the model name** — `GEMINI_VERTEXAI_MODEL` must be a Vertex AI
   -published model (e.g. `gemini-2.0-flash-001`), not an AI Studio model
   id. The Terraform `vertexai_model` local defaults to `gemini_model`
   (`gemini-3.6-flash`); confirm that model is available on Vertex AI for
   the project.

This requires live GCP credentials to debug and is best done in a session
with access to the target project's Cloud Logging.

### Graph snapshot persistence across runs (requirement: GCS state bucket)

The Terraform already provisions a GCS state bucket
(`create_state_bucket = true`) mounted into the job container, but the
script's `GRAPH_SNAPSHOT_DIR` / `GRAPH_DB_PATH` env vars must be pointed
at the mount path (`/mnt/state`) in the Cloud Run Job env config. Verify
the job's env block sets these to the mounted volume so runs accumulate
state instead of starting from the image-baked snapshot each time. See
`infra/README.md` "known limitations" for the full discussion.

### Connect the GitHub repo to Cloud Build (for the push trigger)

If `enable_github_trigger = true`, the GitHub repo must be connected to
Cloud Build via the Cloud Console (Cloud Build > Triggers > Connect
repository) before the trigger can fire. This is a one-time manual step
that can't be done in Terraform.

## Test plan (from the issue)

- [x] Cloud Build config exists (`cloudbuild.yaml`) — builds + pushes to Artifact Registry
- [x] `gcloud builds submit` trigger path implemented (`oracle_trigger.sh build`)
- [x] `gcloud run jobs execute` on-demand path implemented (`oracle_trigger.sh run`)
- [x] Scheduled daily run configured (Cloud Scheduler, existing Terraform)
- [x] Secret management for GEMINI_API_KEY (existing Terraform + Secret Manager)
- [x] Oracle host can check run status via API (`oracle_trigger.sh status`)
- [ ] Cloud Build trigger creates image on push (needs live GCP + GitHub connection)
- [ ] `gcloud run jobs execute` triggers a run from Oracle host (needs live GCP)
- [ ] Scheduled daily run executes successfully (needs live GCP)
- [ ] Free-tier Gemini keys work from within the Cloud Run Job (needs live run)
- [ ] Vertex AI paid-tier fallback works on 429 (blocked on `invalid_scope` fix)
- [ ] Graph snapshot persisted to GCS state bucket across runs (needs env var wiring)

## CloudManagement coordination

Per the cloud-strategy coordination rule, this deployment adds a new cloud
resource (Cloud Build trigger + Artifact Registry repo) to the target GCP
project. When applied against a real project, update:

1. `CloudManagement/config/accounts.yaml` — add the Artifact Registry repo
   and Cloud Build trigger to the project's resource inventory.
2. `CloudManagement/docs/PRD.md` — note the job-placement policy addition
   (story_graph targeted-research now runs as a Cloud Run Job in this
   project, built by Cloud Build).
3. `biofool/starter` template cloud-strategy section — if the
   Oracle-triggers-GCP-build pattern is reused by other repos.
