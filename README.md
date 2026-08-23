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
│   └── 01_crawl_and_build_graph.py
├── tests/
└── data/
```

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
