# Story Graph — AI Context Index

> **Repository revision:** `fb82bbf` (HEAD of `main`, 2026-08-22)
> **Analysis timestamp:** 2026-08-22
> **Staleness check:** compare `git rev-parse HEAD` against the revision above.
> If they differ, run incremental refresh (see `manifest.yaml` → `pass_plan`).

## What This Repo Is

A Python property-graph pipeline that crawls memoir blogs, critique sites,
and interviews about **The Source Family / Father Yod** (Jim Baker), then
extracts entities (persons, groups, places, works, events) and contested
**claims** into a SQLite graph. The schema separates *facts* from *claims* —
storing "who said what about whom, and where" rather than declaring one
canonical truth. An optional Gemini (Google Gen AI) layer adds LLM-based
seed discovery, structured extraction, and graph Q&A.

**Stack:** Python 3.10+, SQLite, spaCy NER, Pydantic v2, Click CLI, Rich
console output, requests/httpx for crawling, tenacity for retries.
**No web server, no CI/CD pipeline, no Dockerfile, no deployment config.**

## Navigation Map

| You want to... | Read this |
|---|---|
| Run the pipeline | [`quickstart.md`](quickstart.md) |
| Understand the architecture | [`architecture/system-overview.md`](architecture/system-overview.md) |
| Understand a specific component | [`components/index.md`](components/index.md) |
| Trace an end-to-end workflow | [`workflows/index.md`](workflows/index.md) |
| Assess change impact before editing | [`change-impact/relationships.yaml`](change-impact/relationships.yaml) |
| Follow coding conventions | [`conventions/index.md`](conventions/index.md) |
| Find the right test command | [`testing/test-map.yaml`](testing/test-map.yaml) |
| Check known debt / risks | [`debt/register.yaml`](debt/register.yaml) |
| Check unresolved unknowns | [`unknowns/register.yaml`](unknowns/register.yaml) |
| Check contradictions | [`decisions/conflicts.yaml`](decisions/conflicts.yaml) |

## Major Components (OBSERVED)

| Component | Path | Responsibility |
|---|---|---|
| Pipeline CLI | `scripts/01_crawl_and_build_graph.py` | Orchestrates crawl → extract → store → detect |
| Pipeline helpers | `scripts/_pipeline_helpers.py` | `process_page()`: per-page entity/claim/relation storage |
| Gemini CLI | `scripts/02_gemini_search.py` | `discover` / `extract` / `ask` subcommands |
| Web crawler | `src/crawler/web_crawler.py` | BFS crawl with domain filtering + depth cap |
| Entity extractor | `src/extractor/entity_extractor.py` | spaCy NER + rule-based entity/relation extraction |
| Alias resolver | `src/extractor/alias_resolver.py` | Canonical name normalization + stable ID generation |
| Claim extractor | `src/extractor/claim_extractor.py` | Wraps entity extractor's claim detection with IDs |
| Contradiction detector | `src/extractor/contradiction_detector.py` | Opposite-stance detection + timeline edges |
| Graph DB | `src/storage/graph_db.py` | SQLite property graph: nodes, edges, sources, claim-source links |
| Data models | `src/storage/models.py` | Pydantic models + enums (NodeType, RelationType, etc.) |
| Text utils | `src/utils/text_utils.py` | Normalization, hashing, HTML cleaning, date extraction |
| Gemini client | `src/llm/gemini_client.py` | Thin wrapper over google-genai SDK |
| LLM extractor | `src/llm/entity_claim_extractor.py` | Gemini-based drop-in for EntityExtractor |
| Graph Q&A | `src/llm/graph_qa.py` | Keyword retrieval + Gemini synthesis |
| Seed discoverer | `src/llm/seed_discoverer.py` | Gemini + Google Search grounding for new seed URLs |
| Config | `config/settings.py` | Pydantic settings from `.env` |

## Key Architectural Boundaries

1. **Default pipeline** (spaCy + rules) runs without Gemini. Gemini features
   degrade gracefully when `GEMINI_API_KEY` is unset.
2. **`process_page()`** is the shared integration point — both the rule-based
   and Gemini extractors produce the same dict shape, making them
   interchangeable.
3. **SQLite is the only data store.** No external DB, queue, or cache.
4. **No web server.** The only entry points are the two CLI scripts.

## Highest-Risk Areas

- `src/storage/graph_db.py` — all persistence; schema changes are high-impact
- `scripts/_pipeline_helpers.py` — `process_page()` ties extractors to storage
- `src/extractor/entity_extractor.py` — 565 LOC, core extraction logic
- `src/llm/entity_claim_extractor.py` — Gemini structured-output schema
