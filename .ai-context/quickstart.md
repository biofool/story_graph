# Quickstart — Story Graph

## System Shape

Single-process Python CLI pipeline. No server, no API, no queue.
Crawl → Extract → Store (SQLite) → Detect contradictions + timeline.
Optional Gemini layer for LLM extraction, seed discovery, and Q&A.

## Major Entry Points

```bash
# Default pipeline (spaCy + rules, no Gemini needed)
python scripts/01_crawl_and_build_graph.py [--max-depth N] [--max-pages N] [--skip-crawl] [--db-path PATH]

# Gemini-powered features (requires GEMINI_API_KEY in .env)
python scripts/02_gemini_search.py discover [--query "..."]
python scripts/02_gemini_search.py extract --url https://... | --text "..."
python scripts/02_gemini_search.py ask "question"

# Explore the SQLite graph
datasette data/graph.db
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
cp .env.example .env  # fill in GEMINI_API_KEY if using Gemini features
```

## Architectural Boundaries

- **Default vs Gemini:** spaCy+rules pipeline works standalone. Gemini
  features degrade gracefully when `GEMINI_API_KEY` is unset.
- **`process_page()`** (`scripts/_pipeline_helpers.py`) is the shared
  integration point. Both `EntityExtractor` and `GeminiExtractor` produce
  the same dict shape (`persons`, `groups`, `places`, `events`, `claims`,
  `relations`), making them interchangeable.
- **SQLite only.** Schema in `src/storage/graph_db.py:SCHEMA_SQL`.

## Dependency Rules (OBSERVED)

- `scripts/` → `src/`, `config/`
- `src/extractor/` → `src/utils/`, `src/extractor/alias_resolver.py`
- `src/llm/` → `src/extractor/alias_resolver.py`, `src/storage/`, `config/`
- `src/storage/` → `src/storage/models.py` (no cross-package deps)
- `src/crawler/` → `src/utils/text_utils.py`
- `config/` → standalone (Pydantic + dotenv)
- No circular dependencies observed.

## Coding Patterns

- Pydantic v2 models for all data structures (`src/storage/models.py`)
- Enums for all controlled vocabularies (NodeType, RelationType, etc.)
- `from __future__ import annotations` in every module
- `logging.getLogger(__name__)` per module (no structlog usage despite dep)
- Click for CLI, Rich for console output
- Stable IDs via `slugify(canonical_name)` prefixed by type

## Test Commands

```bash
pytest                          # all tests
pytest tests/unit/              # unit tests only (fast, no network)
pytest tests/integration/       # integration tests
pytest -m unit                  # by marker
ruff check .                    # lint (line-length=100, py310 target)
```

## Highest-Risk Areas

1. **`src/storage/graph_db.py`** — all persistence; schema changes are high-impact
2. **`scripts/_pipeline_helpers.py`** — `process_page()` ties extractors to storage
3. **`src/extractor/entity_extractor.py`** — 565 LOC, core extraction logic
4. **`src/llm/entity_claim_extractor.py`** — Gemini structured-output schema

## Navigation

→ `architecture/system-overview.md` for the full system context
→ `components/index.md` for per-component detail
→ `workflows/index.md` for end-to-end path tracing
→ `change-impact/relationships.yaml` before editing any component
→ `testing/test-map.yaml` for the correct test command per area
