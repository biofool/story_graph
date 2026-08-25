# Container image for scripts/03_targeted_entity_research.py, built to run
# as a GCP Cloud Run Job (see infra/ for the Terraform that provisions the
# Job + a daily Cloud Scheduler trigger).
#
# This is the only entrypoint this image supports. It is not a general
# story_graph runtime image for scripts/01 or scripts/02.
#
# Notes on what is deliberately NOT here:
#   - No spaCy model download (`python -m spacy download en_core_web_sm`).
#     scripts/03_targeted_entity_research.py never instantiates the
#     spaCy-backed EntityExtractor (src/extractor/entity_extractor.py) --
#     it uses GeminiExtractor/GeminiClaimExtractor for everything. That
#     module's spaCy import is already lazy/guarded (falls back to
#     rule-based extraction if the model is missing), so skipping the
#     model download here is safe and keeps the image smaller. If a
#     future change makes this script use the spaCy path, add the
#     `python -m spacy download en_core_web_sm` line back in.
#   - No git. The container never commits back to the repo; see the
#     "known limitation" note in infra/README.md about graph_snapshot/
#     persistence.

# mirror.gcr.io is Google's public read-through mirror of Docker Hub --
# avoids Docker Hub pull-rate-limiting from within GCP build/run
# environments (Cloud Build, Cloud Run) and resolves reliably there.
FROM mirror.gcr.io/library/python:3.12-slim

# lxml/beautifulsoup4 normally resolve to prebuilt manylinux wheels on this
# base image; no compiler toolchain should be needed. If a future dependency
# bump ever fails to find a wheel, add build-essential + libxml2-dev +
# libxslt1-dev here (and remove them again in the same layer to keep the
# image small).

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the repo the script needs at runtime.
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/
COPY graph_snapshot/ graph_snapshot/

# Run as a non-root user.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Cloud Run Jobs run the container to completion (no HTTP server, no PORT
# env var to serve). CLI flags (--dry-run, --max-results-per-lead, etc.)
# can be appended per-execution via the Cloud Run Job's `args`
# (see infra/main.tf's job_args variable), which are appended after this
# entrypoint's own argv.
ENTRYPOINT ["python", "scripts/03_targeted_entity_research.py"]
