locals {
  vertexai_project_id = var.vertexai_project_id != "" ? var.vertexai_project_id : var.project_id
  # GEMINI_VERTEXAI_MODEL: defaults to the same model as GEMINI_MODEL
  # (var.gemini_model) rather than being left unset. Leaving this unset
  # left TieredGeminiClient's Vertex AI (paid) fallback pointed at
  # config/settings.py's stale gemini-2.5-flash default, which 404s per
  # docs/targeted_research_validation_2026-08-23.md -- i.e. the paid
  # fallback this deployment exists to rely on would fail exactly when the
  # free tier's 429 makes it needed. Override via var.vertexai_model if the
  # two ever need to diverge (e.g. a model available on AI Studio but not
  # yet on Vertex AI for this project).
  vertexai_model    = var.vertexai_model != "" ? var.vertexai_model : var.gemini_model
  state_bucket_name = var.state_bucket_name != "" ? var.state_bucket_name : "${var.project_id}-story-graph-state"
  state_mount_path  = "/mnt/state"

  # Secret Manager reference used in the container's env. Cloud Run v2's
  # secretKeyRef "secret" field accepts either a bare secret id (resolved
  # in the Cloud Run resource's own project) or a full
  # "projects/<p>/secrets/<id>" resource name for a secret elsewhere.
  gemini_secret_ref = var.create_secret ? google_secret_manager_secret.gemini_api_key[0].secret_id : var.gemini_secret_id
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "run" {
  project            = var.project_id
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "scheduler" {
  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  project            = var.project_id
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "aiplatform" {
  count              = var.enable_vertexai_fallback ? 1 : 0
  project            = var.project_id
  service            = "aiplatform.googleapis.com"
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Service accounts (least privilege, one per role rather than one shared SA)
# ---------------------------------------------------------------------------

resource "google_service_account" "job_runtime" {
  project      = var.project_id
  account_id   = "story-graph-job-runtime"
  display_name = "story_graph targeted-research Cloud Run Job runtime identity"
  description  = "Identity the scheduled targeted-entity-research Cloud Run Job executes as. Holds only: Secret Manager access to the GEMINI_API_KEY secret, and (if enabled) Vertex AI + the job's state bucket."
}

resource "google_service_account" "scheduler_invoker" {
  project      = var.project_id
  account_id   = "story-graph-scheduler-invoker"
  display_name = "story_graph Cloud Scheduler -> Cloud Run Job invoker"
  description  = "Identity Cloud Scheduler uses to call the targeted-research Cloud Run Job's :run endpoint. Holds only run.invoker on that one job."
}

# ---------------------------------------------------------------------------
# Secret Manager: GEMINI_API_KEY
#
# Terraform only manages the secret *container* here, never its value --
# no plaintext key material belongs in .tf files or state. After apply, add
# the actual value out of band, e.g.:
#
#   printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add \
#     GEMINI_API_KEY --project=<project_id> --data-file=-
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "gemini_api_key" {
  count     = var.create_secret ? 1 : 0
  project   = var.project_id
  secret_id = var.gemini_secret_id

  replication {
    auto {}
  }

  depends_on = [google_project_service.secretmanager]

  lifecycle {
    # Terraform never touches secret *versions*; guard against a future
    # config accidentally trying to delete/recreate the container.
    prevent_destroy = false
  }
}

resource "google_secret_manager_secret_iam_member" "job_runtime_secret_accessor" {
  secret_id = var.create_secret ? google_secret_manager_secret.gemini_api_key[0].id : var.gemini_secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.job_runtime.email}"
}

# ---------------------------------------------------------------------------
# Vertex AI fallback access (paid tier, used once free AI Studio keys 429)
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "job_runtime_aiplatform_user" {
  count   = var.enable_vertexai_fallback ? 1 : 0
  project = local.vertexai_project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.job_runtime.email}"

  depends_on = [google_project_service.aiplatform]
}

# ---------------------------------------------------------------------------
# GCS bucket: persists the local SQLite working DB + exported JSON snapshot
# across scheduled runs (see infra/README.md "known limitations" -- this
# does NOT sync back into git; it only keeps the job's own state so runs
# converge rather than starting from the image's baked-in snapshot every
# time).
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "state" {
  count                       = var.create_state_bucket ? 1 : 0
  project                     = var.project_id
  name                        = local.state_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      num_newer_versions = 10
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket_iam_member" "job_runtime_state_access" {
  count  = var.create_state_bucket ? 1 : 0
  bucket = google_storage_bucket.state[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.job_runtime.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run Job
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "targeted_research" {
  project             = var.project_id
  name                = var.job_name
  location            = var.region
  deletion_protection = false

  template {
    # parallelism/task_count = 1: exactly one task instance per execution.
    # This is the Cloud Run Jobs equivalent of a Service's max-instances=1
    # -- it stops a single execution from ever fanning the script out into
    # multiple concurrent copies competing for the same shared Gemini
    # free-tier daily quota. It does NOT by itself prevent two separate
    # *executions* (e.g. the daily scheduled run overlapping with someone
    # manually running `gcloud run jobs execute`) -- Cloud Run Jobs have no
    # native "reject if already running" switch. That cross-execution case
    # is instead handled at the application layer: scripts/_run_lock.py
    # acquires a staleness-checked lock file in the mounted state bucket
    # (JOB_LOCK_DIR, set below when create_state_bucket=true) before doing
    # any work, and exits early rather than racing an in-progress run; see
    # infra/README.md.
    parallelism = 1
    task_count  = 1

    template {
      service_account       = google_service_account.job_runtime.email
      max_retries           = var.max_retries
      timeout               = "${var.task_timeout_seconds}s"
      execution_environment = var.create_state_bucket ? "EXECUTION_ENVIRONMENT_GEN2" : "EXECUTION_ENVIRONMENT_GEN1"

      containers {
        image = var.image
        args  = var.job_args

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        env {
          name  = "GEMINI_MODEL"
          value = var.gemini_model
        }
        env {
          name  = "GEMINI_VERTEXAI_ENABLED"
          value = tostring(var.enable_vertexai_fallback)
        }
        env {
          name  = "GEMINI_VERTEXAI_PROJECT"
          value = local.vertexai_project_id
        }
        env {
          name  = "GEMINI_VERTEXAI_LOCATION"
          value = var.region
        }
        env {
          name  = "GEMINI_VERTEXAI_MODEL"
          value = local.vertexai_model
        }
        env {
          name = "GEMINI_API_KEY"
          value_source {
            secret_key_ref {
              secret  = local.gemini_secret_ref
              version = "latest"
            }
          }
        }

        dynamic "env" {
          for_each = var.create_state_bucket ? [1] : []
          content {
            name  = "GRAPH_SNAPSHOT_DIR"
            value = "${local.state_mount_path}/graph_snapshot"
          }
        }
        dynamic "env" {
          for_each = var.create_state_bucket ? [1] : []
          content {
            name  = "GRAPH_DB_PATH"
            value = "${local.state_mount_path}/data/graph.db"
          }
        }
        dynamic "env" {
          # Overlap guard (scripts/_run_lock.py): only meaningful when there
          # is shared storage to lock against. Without the state bucket,
          # each execution is independent/ephemeral anyway and there is
          # nowhere shared to put a marker file, so JOB_LOCK_DIR is left
          # unset and the script skips locking entirely -- see
          # infra/README.md.
          for_each = var.create_state_bucket ? [1] : []
          content {
            name  = "JOB_LOCK_DIR"
            value = local.state_mount_path
          }
        }

        dynamic "volume_mounts" {
          for_each = var.create_state_bucket ? [1] : []
          content {
            name       = "state"
            mount_path = local.state_mount_path
          }
        }
      }

      dynamic "volumes" {
        for_each = var.create_state_bucket ? [1] : []
        content {
          name = "state"
          gcs {
            bucket    = google_storage_bucket.state[0].name
            read_only = false
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.run,
    google_secret_manager_secret_iam_member.job_runtime_secret_accessor,
  ]
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.targeted_research.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

# ---------------------------------------------------------------------------
# Cloud Scheduler: daily trigger (matches the script's own documented
# "0 6 * * *" cron intent)
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "daily_trigger" {
  project   = var.project_id
  name      = "${var.job_name}-daily"
  region    = var.region
  schedule  = var.schedule_cron
  time_zone = var.schedule_timezone
  # NOT how long the job execution is allowed to run -- Scheduler calls the
  # Cloud Run Admin API's `:run` endpoint, which is fire-and-forget: the
  # HTTP call returns as soon as the execution is *created*, not when it
  # finishes (the execution's own runtime is bounded separately by
  # var.task_timeout_seconds on the Cloud Run Job itself, above). This only
  # needs to cover how long Scheduler waits for that one HTTP call to be
  # accepted, so a short fixed value is correct here regardless of how long
  # the script itself might run.
  attempt_deadline = "30s"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.targeted_research.name}:run"

    oauth_token {
      service_account_email = google_service_account.scheduler_invoker.email
    }
  }

  retry_config {
    retry_count = 0
  }

  depends_on = [
    google_project_service.scheduler,
    google_cloud_run_v2_job_iam_member.scheduler_invoker,
  ]
}

# ---------------------------------------------------------------------------
# Alerting: a failed scheduled execution otherwise just becomes a "Failed"
# row in Cloud Run's execution history plus a traceback in Cloud Logging,
# with nothing pushed to a human -- reproducing, one layer up, the exact
# "a human had to remember to check" gap this deployment exists to fix.
#
# Gated on var.notification_email being set (not hardcoded -- see
# infra/terraform.tfvars.example) so this is opt-in rather than forcing an
# address at apply time; leave it unset to skip creating these resources
# entirely.
# ---------------------------------------------------------------------------

resource "google_project_service" "monitoring" {
  count              = var.notification_email != "" ? 1 : 0
  project            = var.project_id
  service            = "monitoring.googleapis.com"
  disable_on_destroy = false
}

resource "google_monitoring_notification_channel" "job_failure_email" {
  count        = var.notification_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "story_graph targeted-research job failure alerts"
  type         = "email"

  labels = {
    email_address = var.notification_email
  }

  depends_on = [google_project_service.monitoring]
}

resource "google_monitoring_alert_policy" "job_execution_failed" {
  count        = var.notification_email != "" ? 1 : 0
  project      = var.project_id
  display_name = "story_graph targeted-research Cloud Run Job execution failed"
  combiner     = "OR"

  conditions {
    display_name = "Execution logged an ERROR-severity entry"

    # Cloud Run Jobs write an ERROR-severity log entry for a failed
    # execution/task. This is a log-based (not metric-based) condition so
    # it fires on the underlying log line directly rather than needing a
    # separate log-based metric resource.
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_job"
        resource.labels.job_name="${google_cloud_run_v2_job.targeted_research.name}"
        resource.labels.location="${var.region}"
        severity>=ERROR
      EOT
    }
  }

  notification_channels = [google_monitoring_notification_channel.job_failure_email[0].name]

  alert_strategy {
    notification_rate_limit {
      # This job runs at most once a day (plus rare manual executions) --
      # one notification per failed execution is plenty; this just guards
      # against a single execution's multiple ERROR log lines paging twice.
      period = "3600s"
    }
  }

  depends_on = [google_project_service.monitoring]
}
