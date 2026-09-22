###############################################################################
# Cloud Build trigger + Artifact Registry repo — GCP-side image construction
# (issue #18: make story_graph cloud-deployable from Oracle host via API).
#
# With these resources, the Oracle host never runs docker locally. It
# triggers a build on Google's infrastructure and GCP constructs the image
# in Artifact Registry. The Oracle host then runs the job via
# `gcloud run jobs execute`.
#
# Resources:
#   google_artifacts_repository.story_graph   Docker repo in Artifact Registry
#   google_project_service.cloudbuild         Cloud Build API
#   google_cloudbuild_trigger.github_push     (optional) push-to-main trigger
#   google_service_account.cloudbuild_sa      CI build identity
###############################################################################

# Cloud Build API
resource "google_project_service" "cloudbuild" {
  project            = var.project_id
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

# Artifact Registry API (needed to create the repo)
resource "google_project_service" "artifactregistry" {
  project            = var.project_id
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

# Artifact Registry docker repository. Created once; deploy.sh's
# first-time setup step `gcloud artifacts repositories create` is replaced
# by this resource when enable_cloudbuild = true.
resource "google_artifacts_repository" "story_graph" {
  count         = var.enable_cloudbuild ? 1 : 0
  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repo_name
  description   = "Docker images for story_graph targeted-research Cloud Run Job"
  format        = "DOCKER"
  depends_on    = [google_project_service.artifactregistry]
}

# Service account for Cloud Build (used by the trigger to push images).
resource "google_service_account" "cloudbuild_sa" {
  count        = var.enable_cloudbuild ? 1 : 0
  project      = var.project_id
  account_id   = "story-graph-cloudbuild"
  display_name = "story_graph Cloud Build trigger identity"
  description  = "Identity used by the Cloud Build trigger to build and push the targeted-research image to Artifact Registry."
}

# Grant the Cloud Build SA push/pull on the Artifact Registry repo.
resource "google_artifacts_repository_iam_member" "cloudbuild_writer" {
  count      = var.enable_cloudbuild ? 1 : 0
  project    = var.project_id
  location   = var.region
  repository = google_artifacts_repository.story_graph[0].name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.cloudbuild_sa[0].email}"
}

# Optional GitHub-connected Cloud Build trigger that builds on push to the
# configured branch. Set enable_github_trigger = true and fill in
# github_owner / github_repo / github_branch to use it. Otherwise the
# Oracle host triggers builds manually via `gcloud builds submit` or
# `gcloud builds trigger run`.
resource "google_cloudbuild_trigger" "github_push" {
  count       = var.enable_cloudbuild && var.enable_github_trigger ? 1 : 0
  project     = var.project_id
  location    = var.region
  name        = "story-graph-build-${var.github_branch}"
  description = "Build story_graph targeted-research image on push to ${var.github_branch}"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^${var.github_branch}$"
    }
  }

  filename        = "cloudbuild.yaml"
  service_account = google_service_account.cloudbuild_sa[0].email

  substitutions = {
    _REGION        = var.region
    _ARTIFACT_REPO = var.artifact_repo_name
    _IMAGE_NAME    = var.cloudbuild_image_name
  }

  depends_on = [
    google_project_service.cloudbuild,
    google_artifacts_repository.story_graph,
  ]
}
