# Story Graph Email Ingest — Setup Guide

This guide covers setting up the email-based URL ingestion pipeline for
the story graph. The pipeline lets you email URLs to
`story@magicsolutions.biz` and have them automatically extracted and
queued for batch processing into the graph.

## Architecture

```
  Email sender
      │
      ▼
  story@magicsolutions.biz
      │  (Cloudflare Email Routing)
      ▼
  Cloudflare Email Worker (story-graph-email)
      │  extracts URLs from email body/subject
      ▼
  Cloudflare KV (STORY_URLS namespace)
      │  (pending:<timestamp>:<url_hash> keys)
      ▼
  Batch ingestion script (scripts/17_ingest_from_kv.py)
      │  pulls pending URLs, processes through pipeline
      ▼
  Story Graph API (Oracle Cloud, port 8091)
      │  graph_snapshot/ JSONL + data/graph.db SQLite
      ▼
  Git commit (graph_snapshot/ changes)
```

## Components

| Component | Location | Purpose |
|---|---|---|
| Email Worker | `email-worker/` | Receives emails, extracts URLs, stores in KV |
| KV namespace | Cloudflare | Stores pending URLs for batch processing |
| Graph API Dockerfile | `Dockerfile.graph-api` | Slim container image (Flask + GraphDB only, no spaCy — ~57 MB RSS) |
| Graph API requirements | `requirements-graph-api.txt` | Minimal deps: flask, pillow, requests, pydantic |
| Batch ingestion script | `scripts/17_ingest_from_kv.py` | Pulls URLs from KV, processes into graph |
| Aikidojournal ingestion | `scripts/16_ingest_aikidojournal.py` | Single-URL ingestion (used by batch script) |
| Terraform | `CloudManagement/terraform-oracle/` | Provisions the Oracle server + DNS + security list |

## Setup steps

### 1. Deploy the Story Graph API to Oracle

The terraform in `CloudManagement/terraform-oracle/` has been updated to
provision a second Docker container on the Oracle Always Free instance
alongside CloudManagement.

```bash
cd ~/projects/github/CloudManagement/terraform-oracle

# Add story_graph settings to terraform.tfvars
cat >> terraform.tfvars <<'EOF'
story_graph_enabled        = true
story_graph_port           = 8091
story_graph_origin_hostname = "graph-origin.magicsolutions.biz"
story_graph_repo_url       = "https://github.com/biofool/story_graph.git"
story_graph_repo_branch    = "main"
story_graph_auth_token     = "$(openssl rand -hex 32)"
EOF

# Apply (will recreate the instance to update cloud-init)
terraform plan
terraform apply
```

After apply, the Oracle server will:
- Clone the story_graph repo
- Build the `story-graph-api:latest` Docker image (includes spaCy model)
- Start the `story-graph-api.service` systemd unit on port 8091
- Create a DNS A record for `graph-origin.magicsolutions.biz`

Verify: `curl http://graph-origin.magicsolutions.biz:8091/api/graph`

### 2. Deploy the Email Worker

```bash
cd ~/projects/github/story_graph/email-worker

# Install dependencies
npm install

# Create the KV namespace
npx wrangler kv namespace create STORY_URLS
# Copy the ID into wrangler.jsonc → kv_namespaces[0].id

# Set the auth token as a secret
npx wrangler secret put STORY_GRAPH_AUTH_TOKEN
# Paste the same token you set in terraform.tfvars

# Update wrangler.jsonc with your Worker URL and allowed senders
# (edit GRAPH_API_URL and ALLOWED_SENDERS)

# Deploy
npx wrangler deploy
```

Note the Worker URL (e.g. `https://story-graph-email.<account>.workers.dev`).

### 3. Set up Cloudflare Email Routing

In the Cloudflare dashboard for `magicsolutions.biz`:

1. Go to **Email > Email Routing**
2. Enable Email Routing (adds MX + SPF records automatically)
3. Go to **Routing Rules > Catch-all** or create a custom address:
   - **Custom address:** `story@magicsolutions.biz`
   - **Action:** Send to a Worker
   - **Worker:** `story-graph-email` (the Worker you deployed in step 2)
4. Save

Now any email sent to `story@magicsolutions.biz` will be processed by
the Email Worker, which extracts URLs and stores them in KV.

### 4. Run batch ingestion

The batch ingestion script pulls pending URLs from the Worker's KV and
processes them through the story graph pipeline:

```bash
cd ~/projects/github/story_graph

# Set the auth token (same as in terraform.tfvars and wrangler secret)
export STORY_GRAPH_AUTH_TOKEN="<your-token>"

# Dry run — list pending URLs without processing
.venv/bin/python scripts/17_ingest_from_kv.py \
  --worker-url https://story-graph-email.<account>.workers.dev \
  --dry-run

# Process all pending URLs
.venv/bin/python scripts/17_ingest_from_kv.py \
  --worker-url https://story-graph-email.<account>.workers.dev

# Process a limited number
.venv/bin/python scripts/17_ingest_from_kv.py \
  --worker-url https://story-graph-email.<account>.workers.dev \
  --limit 5
```

Successfully processed URLs are automatically deleted from KV. Failed
URLs remain in KV for retry.

### 5. Commit graph changes

After batch ingestion, the `graph_snapshot/` JSONL files will have
changed. Commit them:

```bash
cd ~/projects/github/story_graph
git add graph_snapshot/
git commit -m "Ingest URLs from email pipeline"
```

## Email format

Send emails to `story@magicsolutions.biz` with URLs in the body or
subject. The Worker extracts all `http(s)://` URLs from the email.

Example email:
```
To: story@magicsolutions.biz
Subject: New Aikido Journal article

Check this out:
https://aikidojournal.com/2025/05/12/a-journey-through-aikido-robert-nadeau-on-spirituality-o-sensei-and-the-golden-age-of-aikido-in-california/

Also relevant:
https://pleasekillme.com/father-yod/
```

Both URLs will be extracted and stored in KV for batch processing.

## Security notes

- The Email Worker checks an optional sender allowlist (`ALLOWED_SENDERS`
  in `wrangler.jsonc`). Only listed email addresses can submit URLs.
- The Worker's HTTP API (for listing/deleting pending URLs) requires a
  bearer token (`STORY_GRAPH_AUTH_TOKEN`).
- The Oracle security list only allows port 8091 from Cloudflare IPs,
  not from the open internet.
- The story graph API has no auth — it relies on network-level
  restrictions (Cloudflare IP ranges only). Do not expose it to
  `0.0.0.0/0` without adding auth.
