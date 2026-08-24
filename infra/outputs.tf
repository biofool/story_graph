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
