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

## Seed URLs

- `https://lifeinthesourcefamily.blogspot.com/`
- `https://cultnews.com/2016/08/documentary-about-source-family-cult-doesnt-tell-the-whole-story/`
- `https://sourcerestaurants.com/`
- `https://en.wikipedia.org/wiki/Father_Yod`
- `https://pleasekillme.com/father-yod/`

## Allowed crawl domains

`cultnews.com`, `lifeinthesourcefamily.blogspot.com`, `blogspot.com`,
`yahowha.org`, `youtube.com`, `wordpress.com`, `sourcerestaurants.com`,
`en.wikipedia.org`, `pleasekillme.com`, `latimes.com`

## Project structure

```
story_graph/
├── config/settings.py          # Pydantic settings, reads .env
├── src/
│   ├── storage/
│   │   ├── models.py           # Node/Edge Pydantic data models
│   │   └── graph_db.py         # SQLite graph storage
│   ├── scrapers/
│   │   └── web_crawler.py      # Domain-filtered BFS crawler
│   ├── extractors/
│   │   ├── entity_extractor.py # NER + rule-based entity extraction
│   │   ├── alias_resolver.py   # Name normalization / alias tables
│   │   ├── claim_extractor.py  # Claim extraction with stance labels
│   │   └── contradiction_detector.py
│   └── utils/
│       └── text_utils.py       # Text cleaning, URL hashing, normalization
├── scripts/
│   └── 01_crawl_and_build_graph.py
├── tests/
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

Example SQL queries:

```sql
-- All critical claims about Father Yod
SELECT c.claim_text, c.claim_type, s.url
FROM nodes c
JOIN edges e ON e.src_id = c.id AND e.rel_type = 'ABOUT'
JOIN nodes p ON e.dst_id = p.id AND p.type = 'Person'
JOIN sources s ON s.id = c.source_work_id
WHERE c.type = 'Claim' AND c.stance = 'critical'
  AND p.canonical_name = 'James Edward Baker';

-- Everyone connected to The Source Restaurant
SELECT p.label, e.rel_type
FROM edges e
JOIN nodes p ON e.src_id = p.id AND p.type = 'Person'
JOIN nodes g ON e.dst_id = g.id AND g.type = 'Group'
WHERE g.label LIKE '%Source%';

-- Narrative conflicts
SELECT c1.claim_text, c2.claim_text
FROM edges e
JOIN nodes c1 ON e.src_id = c1.id
JOIN nodes c2 ON e.dst_id = c2.id
WHERE e.rel_type = 'CONTRADICTS';
```
