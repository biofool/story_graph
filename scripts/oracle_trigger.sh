#!/usr/bin/env bash
#
# oracle_trigger.sh — trigger story_graph builds and runs from the Oracle
# host via GCP APIs, with all image construction on Google's infrastructure
# (issue #18).
#
# The Oracle host (Always Free A1 ARM instance, see CloudManagement
# terraform-oracle/shared-a1.tf) has gcloud installed but NO docker. This
# script uses gcloud to:
#   1. Trigger a Cloud Build that builds the Dockerfile on GCP and pushes
#      the image to Artifact Registry (no local docker build).
#   2. (Optionally) wait for the build to finish.
#   3. Trigger an on-demand Cloud Run Job execution of the
#      targeted-research pipeline.
#   4. Check the latest execution status.
#
# Prerequisites (one-time, on the Oracle host):
#   - gcloud CLI installed and authenticated:
#       gcloud auth login
#       gcloud auth application-default login
#   - gcloud configured with the target project:
#       gcloud config set project <PROJECT_ID>
#   - The Cloud Build + Artifact Registry + Cloud Run Job resources
#     provisioned via Terraform (enable_cloudbuild=true in terraform.tfvars,
#     then `./deploy.sh apply` from a machine with terraform, OR apply
#     infra/ directly).
#
# Usage:
#   ./scripts/oracle_trigger.sh build        # trigger GCP-side image build
#   ./scripts/oracle_trigger.sh build --wait # trigger build and wait for it
#   ./scripts/oracle_trigger.sh run          # trigger an on-demand scrape run
#   ./scripts/oracle_trigger.sh status       # check latest execution status
#   ./scripts/oracle_trigger.sh all          # build --wait, then run
#
# Environment:
#   PROJECT_ID   (required) GCP project id
#   REGION       (optional) GCP region, default us-central1
#   JOB_NAME     (optional) Cloud Run Job name, default story-graph-targeted-research

set -euo pipefail

REGION="${REGION:-us-central1}"
JOB_NAME="${JOB_NAME:-story-graph-targeted-research}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "${PROJECT_ID:-}" ]]; then
  echo "ERROR: PROJECT_ID is not set. export PROJECT_ID=<your-gcp-project-id>" >&2
  exit 1
fi

cmd="${1:-}"
wait_build=0
if [[ "${2:-}" == "--wait" ]]; then
  wait_build=1
fi

usage() {
  cat <<EOF
Usage: ./scripts/oracle_trigger.sh [build|run|status|all]

  build [--wait]  Trigger a GCP-side Cloud Build (no local docker). With
                  --wait, block until the build completes.
  run             Trigger an on-demand Cloud Run Job execution.
  status          Show the latest job execution status.
  all             build --wait then run.

Environment:
  PROJECT_ID   (required) GCP project id.
  REGION       (optional) GCP region, default us-central1.
  JOB_NAME     (optional) Cloud Run Job name.
EOF
}

trigger_build() {
  echo "==> Triggering GCP-side Cloud Build (project=${PROJECT_ID}, region=${REGION})"
  echo "    Image construction happens on Google's infrastructure — no local docker."
  local build_id
  build_id="$(gcloud builds submit "$REPO_ROOT" --config="$REPO_ROOT/cloudbuild.yaml" --project="$PROJECT_ID" --region="$REGION" --format='value(id)')"
  echo "==> Build started: id=${build_id}"
  echo "    Stream logs: gcloud builds log ${build_id} --project=${PROJECT_ID} --region=${REGION}"
  if [[ "$wait_build" -eq 1 ]]; then
    echo "==> Waiting for build ${build_id} to complete..."
    gcloud builds wait "$build_id" --project="$PROJECT_ID" --region="$REGION"
    echo "==> Build ${build_id} complete."
  fi
  echo "$build_id"
}

trigger_run() {
  echo "==> Triggering on-demand Cloud Run Job execution: ${JOB_NAME}"
  gcloud run jobs execute "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" --format='value(name)'
  echo "==> Execution triggered. Check status with: ./scripts/oracle_trigger.sh status"
}

show_status() {
  echo "==> Latest executions for job ${JOB_NAME}:"
  gcloud run jobs executions list --job="$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" --limit=5 --format='table(name,status.createTime,format("%-10s",status.conditions[0].type),status.conditions[0].status)'
}

case "$cmd" in
  -h|--help|help) usage; exit 0 ;;
  build)
    trigger_build
    ;;
  run)
    trigger_run
    ;;
  status)
    show_status
    ;;
  all)
    wait_build=1
    trigger_build
    echo
    trigger_run
    ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    usage
    exit 1
    ;;
esac
