output "job_name" {
  description = "Cloud Run Job name."
  value       = google_cloud_run_v2_job.targeted_research.name
}

output "scheduler_job_name" {
  description = "Cloud Scheduler job name."
  value       = google_cloud_scheduler_job.daily_trigger.name
}

output "job_runtime_service_account_email" {
  description = "Service account the Cloud Run Job executes as."
  value       = google_service_account.job_runtime.email
}

output "scheduler_invoker_service_account_email" {
  description = "Service account Cloud Scheduler uses to invoke the job."
  value       = google_service_account.scheduler_invoker.email
}

output "gemini_secret_resource" {
  description = "Secret Manager secret the job reads GEMINI_API_KEY from. Add the actual key value out-of-band -- see infra/README.md."
  value       = var.create_secret ? google_secret_manager_secret.gemini_api_key[0].id : var.gemini_secret_id
}

output "state_bucket_name" {
  description = "GCS bucket holding the job's persistent working state (SQLite DB + exported JSON snapshot), if created."
  value       = var.create_state_bucket ? google_storage_bucket.state[0].name : null
}

output "manual_run_command" {
  description = "gcloud command to trigger the job immediately without waiting for the scheduler."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.targeted_research.name} --region=${var.region} --project=${var.project_id}"
}

output "failure_alerting_enabled" {
  description = "Whether the Cloud Monitoring alert policy + email notification channel for failed executions was created (true iff var.notification_email is set)."
  value       = var.notification_email != ""
}

# --- Cloud Build / Artifact Registry (issue #18) ---

output "artifact_registry_repo" {
  description = "Artifact Registry docker repository holding the built image (if enable_cloudbuild)."
  value       = var.enable_cloudbuild ? google_artifacts_repository.story_graph[0].name : null
}

output "cloudbuild_trigger_name" {
  description = "Cloud Build trigger name (if enable_github_trigger)."
  value       = var.enable_cloudbuild && var.enable_github_trigger ? google_cloudbuild_trigger.github_push[0].name : null
}

output "oracle_trigger_build_command" {
  description = "gcloud command the Oracle host runs to trigger a GCP-side build (no local docker)."
  value       = "gcloud builds submit --config cloudbuild.yaml --project=${var.project_id} --region=${var.region}"
}

output "oracle_run_job_command" {
  description = "gcloud command the Oracle host runs to trigger a scrape run on-demand."
  value       = "gcloud run jobs execute ${google_cloud_run_v2_job.targeted_research.name} --region=${var.region} --project=${var.project_id}"
}

output "oracle_run_status_command" {
  description = "gcloud command the Oracle host runs to check the latest execution status."
  value       = "gcloud run jobs executions list --job=${google_cloud_run_v2_job.targeted_research.name} --region=${var.region} --project=${var.project_id} --limit=1"
}
