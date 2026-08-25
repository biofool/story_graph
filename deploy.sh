#!/usr/bin/env bash
#
# deploy.sh -- build + push the targeted-research container image, then
# apply/destroy the Terraform in infra/ that runs it as a daily-scheduled
# Cloud Run Job.
#
# Usage:
#   ./deploy.sh apply     Build image, push it, terraform apply (default)
#   ./deploy.sh plan       Build image, push it, terraform plan (no changes)
#   ./deploy.sh destroy   terraform destroy (does NOT touch the image)
#   ./deploy.sh build     Build + push the image only, skip Terraform
#
# Required environment variables (or set them in infra/terraform.tfvars --
# see infra/terraform.tfvars.example):
#   PROJECT_ID   GCP project id, e.g. export PROJECT_ID=my-project
#   REGION       GCP region (default: us-central1)
#
# Prerequisites:
#   - gcloud CLI, authenticated (`gcloud auth login` and
#     `gcloud auth application-default login`) against PROJECT_ID
#   - terraform >= 1.5
#   - docker
#   - Artifact Registry repo named "story-graph" in PROJECT_ID/REGION
#     (create once: gcloud artifacts repositories create story-graph
#      --repository-format=docker --location=$REGION --project=$PROJECT_ID)
#
# This script does NOT create the GEMINI_API_KEY secret's value, grant you
# gcloud/IAM access, or run terraform init for you the first time -- see
# infra/README.md for the full first-time setup checklist.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/infra"
IMAGE_NAME="targeted-research"
REGION="${REGION:-us-central1}"

usage() {
  cat <<'EOF'
Usage: ./deploy.sh [apply|plan|destroy|build]

  apply     (default) Build + push the container image, then `terraform apply`.
  plan      Build + push the container image, then `terraform plan` (no changes made).
  destroy   `terraform destroy` only -- does not touch the container image.
  build     Build + push the container image only, skip Terraform entirely.

Environment:
  PROJECT_ID   (required) GCP project id.
  REGION       (optional) GCP region, default us-central1.

Example:
  PROJECT_ID=my-story-graph-project ./deploy.sh apply
EOF
}

command="${1:-apply}"

case "$command" in
  -h|--help|help)
    usage
    exit 0
    ;;
  apply|plan|destroy|build)
    ;;
  *)
    echo "Unknown command: $command" >&2
    usage
    exit 1
    ;;
esac

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "ERROR: PROJECT_ID is not set. export PROJECT_ID=<your-gcp-project-id>" >&2
  exit 1
fi

IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/story-graph/${IMAGE_NAME}:latest"

build_and_push() {
  echo "==> Building ${IMAGE_URI}"
  docker build -t "$IMAGE_URI" "$SCRIPT_DIR"
  echo "==> Configuring docker auth for ${REGION}-docker.pkg.dev"
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
  echo "==> Pushing ${IMAGE_URI}"
  docker push "$IMAGE_URI"
}

# Cloud Run Job + Terraform is a known footgun with a mutable tag like
# ":latest" -- depending on provider/API version, the resource's `image`
# field either shows a spurious diff every plan (GCP resolves the tag to a
# digest in state) or fails to pick up a rebuild at all (the config string
# ":latest" never changes between applies). Resolving the actual pushed
# digest and pinning Terraform to `...@sha256:...` makes each deploy
# deterministic and visible in `terraform plan`, rather than relying on
# tag-resolution behavior. Sets IMAGE_URI_DIGEST.
resolve_pushed_digest() {
  echo "==> Resolving pushed digest for ${IMAGE_URI}"
  local digest
  digest="$(gcloud artifacts docker images describe "$IMAGE_URI" \
    --project="$PROJECT_ID" --format='value(image_summary.digest)')"
  if [[ -z "$digest" ]]; then
    echo "ERROR: could not resolve a digest for ${IMAGE_URI} (gcloud artifacts docker images describe returned nothing)" >&2
    exit 1
  fi
  IMAGE_URI_DIGEST="${IMAGE_URI%%:*}@${digest}"
  echo "==> Resolved: ${IMAGE_URI_DIGEST}"
}

case "$command" in
  build)
    build_and_push
    echo "Image pushed: $IMAGE_URI"
    ;;
  destroy)
    echo "==> terraform destroy (project=${PROJECT_ID}, region=${REGION})"
    terraform -chdir="$INFRA_DIR" destroy \
      -var="project_id=${PROJECT_ID}" \
      -var="region=${REGION}" \
      -var="image=${IMAGE_URI}"
    ;;
  apply|plan)
    build_and_push
    resolve_pushed_digest
    echo "==> terraform init"
    terraform -chdir="$INFRA_DIR" init
    echo "==> terraform ${command} (project=${PROJECT_ID}, region=${REGION}, image=${IMAGE_URI_DIGEST})"
    terraform -chdir="$INFRA_DIR" "$command" \
      -var="project_id=${PROJECT_ID}" \
      -var="region=${REGION}" \
      -var="image=${IMAGE_URI_DIGEST}"
    ;;
esac
