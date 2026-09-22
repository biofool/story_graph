#!/usr/bin/env python3
"""
Oracle host trigger script for story_graph targeted-research.

This script lets the Oracle host trigger a scrape run on GCP via API calls,
without needing docker or local build tools. It uses the gcloud CLI to:

  1. (Optional) Trigger Cloud Build to construct a fresh image
  2. (Optional) Apply Terraform to update the Cloud Run Job with the new image
  3. Trigger a one-off execution of the Cloud Run Job
  4. Wait for the execution to complete and report status

Usage:
    python scripts/trigger_research.py                    # Trigger a run
    python scripts/trigger_research.py --build            # Build + deploy + run
    python scripts/trigger_research.py --build --apply    # Build + apply + run
    python scripts/trigger_research.py --status           # Show recent runs
    python scripts/trigger_research.py --wait             # Wait for completion
    python scripts/trigger_research.py --dry-run          # Print commands only

Environment:
    PROJECT_ID   (required) GCP project id
    REGION       (optional) GCP region, default us-central1
    JOB_NAME     (optional) Cloud Run Job name, default story-graph-targeted-research

Examples:
    # Just trigger a run with the current deployed image
    PROJECT_ID=quantum-aikido-coaching python scripts/trigger_research.py

    # Build a fresh image, deploy it, then run
    PROJECT_ID=quantum-aikido-coaching python scripts/trigger_research.py --build --apply

    # Check status of recent runs
    PROJECT_ID=quantum-aikido-coaching python scripts/trigger_research.py --status
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def run_cmd(cmd: list[str], dry_run: bool = False, capture: bool = True) -> str:
    """Run a gcloud command, returning stdout. Raises on failure."""
    cmd_str = " ".join(cmd)
    if dry_run:
        print(f"  [dry-run] {cmd_str}")
        return ""
    print(f"  $ {cmd_str}")
    result = subprocess.run(
        cmd, capture_output=capture, text=True, check=False
    )
    if result.returncode != 0:
        print(f"  ERROR (exit {result.returncode}): {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip() if capture else ""


def trigger_build(project_id: str, region: str, script_dir: Path, dry_run: bool) -> str:
    """Trigger Cloud Build to construct the image. Returns build ID."""
    print("\n==> Triggering Cloud Build (GCP-side image construction)")
    build_id = run_cmd([
        "gcloud", "builds", "submit", str(script_dir),
        "--config=" + str(script_dir / "cloudbuild.yaml"),
        f"--project={project_id}",
        f"--substitutions=_REGION={region},_REPO_NAME=story-graph,_IMAGE_NAME=targeted-research,_IMAGE_TAG=latest",
        "--format=value(id)",
    ], dry_run=dry_run)
    if not dry_run and build_id:
        print(f"  Build ID: {build_id}")
    return build_id


def resolve_digest(project_id: str, region: str, dry_run: bool) -> str:
    """Resolve the pushed image digest from Artifact Registry."""
    image_uri = f"{region}-docker.pkg.dev/{project_id}/story-graph/targeted-research:latest"
    print(f"\n==> Resolving digest for {image_uri}")
    digest = run_cmd([
        "gcloud", "artifacts", "docker", "images", "describe", image_uri,
        f"--project={project_id}",
        "--format=value(image_summary.digest)",
    ], dry_run=dry_run)
    if not dry_run and digest:
        full_uri = f"{image_uri.rsplit(':', 1)[0]}@{digest}"
        print(f"  Resolved: {full_uri}")
        return full_uri
    return image_uri


def terraform_apply(project_id: str, region: str, image_uri: str, infra_dir: Path, dry_run: bool) -> None:
    """Run terraform apply with the resolved image."""
    print(f"\n==> terraform apply (project={project_id}, image={image_uri})")
    run_cmd(["terraform", "-chdir=" + str(infra_dir), "init"], dry_run=dry_run, capture=False)
    run_cmd([
        "terraform", "-chdir=" + str(infra_dir), "apply", "-auto-approve",
        f"-var=project_id={project_id}",
        f"-var=region={region}",
        f"-var=image={image_uri}",
    ], dry_run=dry_run, capture=False)


def trigger_job(project_id: str, region: str, job_name: str, dry_run: bool) -> str:
    """Trigger a one-off execution of the Cloud Run Job. Returns execution name."""
    print(f"\n==> Triggering Cloud Run Job: {job_name}")
    execution = run_cmd([
        "gcloud", "run", "jobs", "execute", job_name,
        f"--project={project_id}",
        f"--region={region}",
        "--format=value(metadata.name)",
    ], dry_run=dry_run)
    if not dry_run and execution:
        print(f"  Execution: {execution}")
    return execution


def show_status(project_id: str, region: str, job_name: str, dry_run: bool) -> None:
    """Show recent Cloud Run Job executions."""
    print(f"\n==> Recent executions for {job_name}")
    run_cmd([
        "gcloud", "run", "jobs", "executions", "list",
        f"--job={job_name}",
        f"--project={project_id}",
        f"--region={region}",
        "--limit=5",
        "--format=table(name,status,startTime,completionTime)",
    ], dry_run=dry_run, capture=False)


def wait_for_execution(project_id: str, region: str, execution_name: str, dry_run: bool, timeout: int = 1800) -> None:
    """Wait for a Cloud Run Job execution to complete."""
    if dry_run or not execution_name:
        print("\n  [dry-run] would wait for execution to complete")
        return
    print(f"\n==> Waiting for {execution_name} (timeout {timeout}s)")
    start = time.time()
    while time.time() - start < timeout:
        status = run_cmd([
            "gcloud", "run", "jobs", "executions", "describe", execution_name,
            f"--project={project_id}",
            f"--region={region}",
            "--format=value(status)",
        ], dry_run=False)
        if status in ("SUCCEEDED", "FAILED", "CANCELLED", "DELETED"):
            print(f"\n  Execution {execution_name}: {status}")
            if status != "SUCCEEDED":
                print(f"  Logs: gcloud run jobs executions logs {execution_name} --project={project_id} --region={region}")
                sys.exit(1)
            return
        elapsed = int(time.time() - start)
        print(f"  [{elapsed}s] status={status or 'PENDING'}...", end="\r", flush=True)
        time.sleep(10)
    print(f"\n  TIMEOUT waiting for {execution_name} after {timeout}s")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Trigger story_graph targeted-research from the Oracle host."
    )
    parser.add_argument("--build", action="store_true", help="Trigger Cloud Build to construct a fresh image")
    parser.add_argument("--apply", action="store_true", help="Run terraform apply after building")
    parser.add_argument("--status", action="store_true", help="Show recent execution status")
    parser.add_argument("--wait", action="store_true", help="Wait for the triggered execution to complete")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    args = parser.parse_args()

    project_id = os.environ.get("PROJECT_ID", "")
    if not project_id:
        print("ERROR: PROJECT_ID is not set. export PROJECT_ID=<your-gcp-project-id>", file=sys.stderr)
        sys.exit(1)
    region = os.environ.get("REGION", "us-central1")
    job_name = os.environ.get("JOB_NAME", "story-graph-targeted-research")

    script_dir = Path(__file__).resolve().parent.parent
    infra_dir = script_dir / "infra"

    if args.status:
        show_status(project_id, region, job_name, args.dry_run)
        return

    image_uri = None
    if args.build:
        trigger_build(project_id, region, script_dir, args.dry_run)
        image_uri = resolve_digest(project_id, region, args.dry_run)
        if args.apply:
            terraform_apply(project_id, region, image_uri, infra_dir, args.dry_run)

    execution = trigger_job(project_id, region, job_name, args.dry_run)

    if args.wait:
        wait_for_execution(project_id, region, execution, args.dry_run)
    elif not args.dry_run and execution:
        print(f"\n  Check status: PROJECT_ID={project_id} python scripts/trigger_research.py --status")
        print(f"  Stream logs:  gcloud run jobs executions logs {execution} --project={project_id} --region={region}")


if __name__ == "__main__":
    main()
