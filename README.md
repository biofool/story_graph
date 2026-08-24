# Story Graph — The Source Family / Father Yod

A property-graph pipeline for crawling, extracting, and graphing information about
people who may have worked at **The Source** restaurant on the Sunset Strip in Los
Angeles, and the surrounding **Source Family** commune led by Jim Baker / Father Yod.

## Overview

The pipeline crawls memoir blogs, critique sites, interviews, and linked media,
then extracts entities (people, groups, places, works, events) and contested
claims into a property graph stored in SQLite. The schema separates **facts**
from **claims** — storing "who said what about whom, and where" rather than
prematurely declaring one canonical truth.

## Graph schema

Six core node types:

| Node type | Key fields |
|---|---|
| **Person** | `id`, `name`, `aliases[]`, `roles[]`, `bio_summary`, `source_urls[]` |
| **Group** | `id`, `name`, `aliases[]`, `group_type`, `founded_date`, `source_urls[]` |
| **Place** | `id`, `name`, `place_type`, `address`, `geo_hint`, `source_urls[]` |
| **Work** | `id`, `title`, `work_type`, `creator_ids[]`, `publish_date`, `url`, `source_urls[]` |
| **Event** | `id`, `label`, `event_type`, `start_date`, `end_date`, `description`, `source_urls[]` |
| **Claim** | `id`, `claim_text`, `claim_type`, `stance`, `confidence`, `quoted_speaker_id`, `about_ids[]`, `source_work_id`, `source_urls[]` |

Key relations: `ALIAS_OF`, `FOUNDED`, `MEMBER_OF`, `WORKED_AT`, `LIVED_AT`,
`CREATED`, `PUBLISHED_AT`, `DESCRIBES`, `ABOUT`, `ASSERTED_BY`, `CONTRADICTS`,
`SUPPORTED_BY`, `LOCATED_IN`, `PRECEDES`, `MENTIONS`, `CONTAINS`.

## Pipeline phases

1. **Crawl** — `scripts/01_crawl_and_build_graph.py` fetches seed URLs and
   follows links up to a configurable depth, filtering by allowed domains.
2. **Extract** — Entity extraction (spaCy NER + rule patterns), alias
   normalization, claim extraction with stance labels.
3. **Store** — All nodes, edges, sources, and claim-source links written to
   SQLite incrementally.
4. **Detect** — Contradiction detection between claims with opposite stances
   targeting the same entity/event. Timeline edges from date mentions.

## Scheduled deployment

`scripts/03_targeted_entity_research.py` is meant to run daily (see its
module docstring). It's packaged as a container (`Dockerfile`, repo root)
and deployed as a GCP Cloud Run Job on a Cloud Scheduler cron trigger via
the Terraform in `infra/` — build/push/apply with `./deploy.sh`. See
`infra/README.md` for first-time setup and, importantly, the "known
limitations" section: this was built and validated without live GCP
credentials and has not yet been applied against a real project.

## Quick start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# Copy environment config
cp .env.example .env

# Run the pipeline
python scripts/01_crawl_and_build_graph.py
```

## Secrets & API keys

Production keys are **not** stored in this repository. They live in
**Google Secret Manager**:

| Secret | Project | Used by |
|---|---|---|
| `GEMINI_API_KEY` | `aiqa-coaching`, `quantum-aikido-coaching` | Gemini seed discovery, LLM extraction, graph Q&A |

- **Local development:** copy `.env.example` to `.env` and fill in values.
  `.env` is gitignored — never commit it or any key material.
- **Fetching a secret for local use:**
  `gcloud secrets versions access latest --secret=GEMINI_API_KEY --project=aiqa-coaching`
  (requires appropriate IAM on the project).
- The full secret-name inventory is maintained in the CloudManagement repo's
  `AGENTS.md`. Never paste secret values into code, logs, docs, or commits.

### Cost tracking (optional, opt-in)

The targeted-research script (`scripts/03_targeted_entity_research.py`) can
optionally declare an intent with the **CloudManagement** hub before making
paid Gemini calls and report actual costs incrementally, enabling
centralized budget gating and kill-switch integration across the biofool
portfolio. The `cloud_management_client` package is vendored at
`src/cloud_management_client/` (stdlib-only — no pip dependency).

The integration is **disabled by default**. To enable it, set these env vars
in `.env` (see `.env.example`):

| Env var | Purpose |
|---|---|
| `CLOUDMANAGEMENT_ENABLED` | Set to `true` to opt in (default `false`) |
| `CLOUDMANAGEMENT_URL` | Hub base URL (default `http://127.0.0.1:8080`) |
| `CLOUDMANAGEMENT_PROJECT_ID` | Project ID registered in the hub |
| `CLOUDMANAGEMENT_REPORT_TOKEN` | Report token (secret — never log) |
| `CLOUDMANAGEMENT_APPLICATION` | App name for attribution (default `StoryGraph`) |
| `CLOUDMANAGEMENT_SOURCE_REPO` | Source repo (default `biofool/story_graph`) |
| `CLOUDMANAGEMENT_STRICT` | Raise on hub errors instead of logging (default `false`) |
| `CLOUDMANAGEMENT_TIMEOUT` | HTTP timeout in seconds (default `5`) |
| `CLOUDMANAGEMENT_INTENT_TIMEOUT` | Intent declaration timeout (default `3`) |

When disabled, the pipeline runs exactly as before with zero behavior change.
When enabled and the hub is unreachable, the tracker enters degraded mode:
calls proceed without blocking and a warning is logged. If the hub denies the
intent, Phase 2 (paid API calls) is skipped. See `src/llm/cost_tracker.py`.

## Seed URLs

- `https://lifeinthesourcefamily.blogspot.com/`
- `https://cultnews.com/2016/08/documentary-about-source-family-cult-doesnt-tell-the-whole-story/`
- `https://www.lamag.com/askchris/source-on-the-sunset-strip/`
- `https://martinostimemachine.blogspot.com/2021/06/the-source-restaurant.html`
- `https://en.wikipedia.org/wiki/Father_Yod`
- `https://pleasekillme.com/father-yod/`

## Allowed crawl domains

`cultnews.com`, `lifeinthesourcefamily.blogspot.com`, `blogspot.com`,
`yahowha.org`, `youtube.com`, `wordpress.com`, `lamag.com`,
`en.wikipedia.org`, `pleasekillme.com`, `latimes.com`

## Project structure

```
story_graph/
├── config/settings.py          # Pydantic settings, reads .env
├── src/
│   ├── storage/
│   │   ├── models.py           # Node/Edge Pydantic data models
│   │   └── graph_db.py         # SQLite graph storage
│   ├── crawler/
│   │   └── web_crawler.py      # Domain-filtered BFS crawler
│   ├── extractor/
│   │   ├── entity_extractor.py # NER + rule-based entity extraction
│   │   ├── alias_resolver.py   # Name normalization / alias tables
│   │   ├── claim_extractor.py  # Claim extraction with stance labels
│   │   └── contradiction_detector.py
│   └── utils/
│       └── text_utils.py       # Text cleaning, URL hashing, normalization
├── scripts/
│   ├── 01_crawl_and_build_graph.py
│   └── 03_targeted_entity_research.py  # scheduled — see infra/README.md
├── tests/
├── Dockerfile                    # Container image for scripts/03 (Cloud Run Job)
├── deploy.sh                      # Build/push/terraform-apply wrapper — see infra/README.md
├── infra/                         # Terraform: Cloud Run Job + Cloud Scheduler + IAM
├── graph_snapshot/              # Tracked JSON/JSONL graph (source of truth)
└── data/                        # data/graph.db: local SQLite working copy (git-ignored)
```

## Data storage: JSON snapshot is the source of truth, SQLite is a local working copy

The graph is stored two ways, deliberately with different lifecycles:

- **`graph_snapshot/`** (repo root) — the tracked, version-controlled source
  of truth. One JSONL file per entity type (`nodes.jsonl`, `edges.jsonl`,
  `sources.jsonl`, `claim_sources.jsonl`), one JSON object per line, sorted
  deterministically by id. This is what reviewers see change in an MR diff.
- **`data/graph.db`** — a disposable local SQLite working copy, git-ignored.
  `GraphDB` (`src/storage/graph_db.py`) still does all the actual
  reading/writing/querying during a run; nothing else changes about how the
  pipeline works internally.

`src/storage/json_export.py` translates between the two:
`import_from_json`/`load_from_json` rebuilds a fresh `data/graph.db` from
`graph_snapshot/` at the start of a run, and `export_to_json` writes the
resulting graph back out to `graph_snapshot/` when the run finishes.
`scripts/03_targeted_entity_research.py` does both automatically; see its
module docstring for the exact phases.

JSON was chosen over committing `data/graph.db` directly because a JSONL
diff shows exactly which nodes/edges/sources changed, one readable line at
a time, where a SQLite file would only ever show as an opaque binary diff
in a merge request. The tradeoff is JSON/JSONL's usual limits — no indexes,
no concurrent writers, a full-file rewrite on every export. **This can be
revisited** (e.g. back to SQLite as the tracked format, or a real
server-side DB) if the graph ever grows large enough for JSON export/import
or diffing to become an actual performance problem; until then, GraphDB
remains the only code that understands the graph's schema, so switching the
tracked format later should not require touching call sites elsewhere.

## Querying the graph

The SQLite database can be explored with `datasette`:

```bash
datasette data/graph.db
```

Nodes and edges are stored generically (see `src/storage/models.py` and
`src/storage/graph_db.py`): every `GraphNode` has a single `metadata` dict,
persisted as an unindexed `metadata_json` TEXT column on the `nodes` table.
Type-specific fields such as a claim's text, type, or stance are *not*
separate columns — they live inside that JSON blob and must be pulled out
with SQLite's `json_extract()`. A claim's relationship to the page it came
from is likewise not a column on `nodes`; it's a row in the `claim_sources`
join table (`claim_id`, `source_id`) pointing at `sources.id`.

Example SQL queries:

```sql
-- All critical claims about Father Yod
SELECT
    json_extract(c.metadata_json, '$.claim_text') AS claim_text,
    json_extract(c.metadata_json, '$.claim_type') AS claim_type,
    s.url AS source_url
FROM nodes c
JOIN edges e ON e.src_id = c.id AND e.rel_type = 'ABOUT'
JOIN nodes p ON e.dst_id = p.id AND p.type = 'Person'
JOIN claim_sources cs ON cs.claim_id = c.id
JOIN sources s ON s.id = cs.source_id
WHERE c.type = 'Claim'
  AND json_extract(c.metadata_json, '$.stance') = 'critical'
  AND p.canonical_name = 'James Edward Baker';

-- Everyone connected to The Source Restaurant
SELECT p.label, e.rel_type
FROM edges e
JOIN nodes p ON e.src_id = p.id AND p.type = 'Person'
JOIN nodes g ON e.dst_id = g.id AND g.type = 'Group'
WHERE g.label LIKE '%Source%';

-- Narrative conflicts
SELECT
    json_extract(c1.metadata_json, '$.claim_text') AS claim1_text,
    json_extract(c2.metadata_json, '$.claim_text') AS claim2_text
FROM edges e
JOIN nodes c1 ON e.src_id = c1.id AND c1.type = 'Claim'
JOIN nodes c2 ON e.dst_id = c2.id AND c2.type = 'Claim'
WHERE e.rel_type = 'CONTRADICTS';
```
