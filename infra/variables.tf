variable "project_id" {
  description = "GCP project to deploy the Cloud Run Job + Cloud Scheduler trigger into."
  type        = string
}

variable "region" {
  description = "GCP region for the Cloud Run Job, Cloud Scheduler job, and (if created) the state bucket."
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = <<-EOT
    Full container image URI to run (e.g.
    "us-central1-docker.pkg.dev/PROJECT/story-graph/targeted-research:latest").
    Terraform does not build or push the image -- build it from the repo's
    Dockerfile and push it (deploy.sh does this) before running `terraform apply`.
  EOT
  type        = string
}

variable "job_name" {
  description = "Cloud Run Job name."
  type        = string
  default     = "story-graph-targeted-research"
}

variable "job_args" {
  description = <<-EOT
    Extra CLI args appended to the container's entrypoint
    (`python scripts/03_targeted_entity_research.py`), e.g.
    ["--max-results-per-lead", "3"]. Empty by default (script's own defaults).
  EOT
  type        = list(string)
  default     = []
}

variable "cpu" {
  description = "Cloud Run Job container CPU limit."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Cloud Run Job container memory limit."
  type        = string
  default     = "512Mi"
}

variable "task_timeout_seconds" {
  description = <<-EOT
    Max seconds a single job execution may run before Cloud Run kills it.
    The script does web search + crawl + Gemini extraction across several
    leads, which can take a while; default gives it headroom.
  EOT
  type        = number
  default     = 1800
}

variable "max_retries" {
  description = <<-EOT
    Cloud Run task retry count on failure. Kept at 0 by default: a retry
    would re-run the whole script and burn additional free/paid Gemini
    quota on a day where the first attempt already failed (e.g. on 429) --
    the script's own free->paid tiered fallback is the intended way to
    survive a quota exhaustion, not a Cloud Run-level retry.
  EOT
  type        = number
  default     = 0
}

variable "schedule_cron" {
  description = "Cron schedule for the daily Cloud Scheduler trigger. Matches the script's own documented intent (see its module docstring)."
  type        = string
  default     = "0 6 * * *"
}

variable "schedule_timezone" {
  description = "IANA time zone the cron schedule is evaluated in."
  type        = string
  default     = "Etc/UTC"
}

variable "gemini_model" {
  description = <<-EOT
    Value for the GEMINI_MODEL env var (AI Studio / free-tier model).
    Defaults to gemini-3.6-flash, not the repo's .env.example default of
    gemini-2.5-flash -- per docs/targeted_research_validation_2026-08-23.md,
    gemini-2.5-flash now 404s for new AI Studio callers and 3.6-flash is
    required. Override if that changes again.
  EOT
  type        = string
  default     = "gemini-3.6-flash"
}

variable "enable_vertexai_fallback" {
  description = <<-EOT
    Whether the job's service account is granted Vertex AI access
    (roles/aiplatform.user) and GEMINI_VERTEXAI_ENABLED=true is set, so
    TieredGeminiClient can fall back to Vertex AI (paid) once free-tier
    AI Studio keys hit their daily 429 -- the exact failure mode that
    prompted this deployment.
  EOT
  type        = bool
  default     = true
}

variable "vertexai_project_id" {
  description = "GCP project used for Vertex AI billing/fallback calls (GEMINI_VERTEXAI_PROJECT). Defaults to project_id."
  type        = string
  default     = ""
}

variable "gemini_secret_id" {
  description = <<-EOT
    Secret Manager secret id/name holding the GEMINI_API_KEY value.
    When create_secret = true, this is the id of a new secret Terraform
    creates in var.project_id (you still add the actual value manually --
    see infra/README.md). When create_secret = false, pass the FULL
    resource id of an existing secret instead (e.g.
    "projects/123456789/secrets/GEMINI_API_KEY") -- e.g. to reuse the
    GEMINI_API_KEY secret story_graph's README already documents in the
    aiqa-coaching / quantum-aikido-coaching projects.
  EOT
  type        = string
  default     = "GEMINI_API_KEY"
}

variable "create_secret" {
  description = "Whether Terraform creates the Secret Manager secret container (true) or references an existing one by full resource id via gemini_secret_id (false)."
  type        = bool
  default     = true
}

variable "create_state_bucket" {
  description = <<-EOT
    Whether to create a GCS bucket, mounted into the job container, to hold
    the local SQLite working DB and the exported JSON snapshot across
    scheduled runs. Without this, GRAPH_SNAPSHOT_DIR/GRAPH_DB_PATH fall back
    to the copy baked into the container image at build time and every run
    starts from that same fixed state -- see infra/README.md's "known
    limitations" section for what this does and does not solve.
  EOT
  type        = bool
  default     = true
}

variable "state_bucket_name" {
  description = "GCS bucket name for job state (must be globally unique). Empty string computes a default of \"<project_id>-story-graph-state\"."
  type        = string
  default     = ""
}
