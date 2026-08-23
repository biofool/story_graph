# Configuration Conventions

All patterns **OBSERVED** from source code.

## Configuration Architecture

### Single source: `config/settings.py`
- `Settings(BaseModel)` — Pydantic v2 model
- `load_dotenv(PROJECT_ROOT / ".env")` at module import time
- `settings = Settings()` — module-level singleton
- Each field uses `Field(default_factory=lambda: ...os.getenv(...))`

### Environment Variables (from `.env.example`)

| Variable | Default | Used By |
|---|---|---|
| `CRAWL_DELAY_SECONDS` | `3` | WebCrawler |
| `CRAWL_MAX_DEPTH` | `2` | WebCrawler |
| `CRAWL_MAX_PAGES` | `200` | WebCrawler |
| `CRAWL_USER_AGENT` | `story-graph-bot/0.1 (+research)` | WebCrawler |
| `CRAWL_TIMEOUT` | `30` | WebCrawler |
| `SPACY_MODEL` | `en_core_web_sm` | EntityExtractor |
| `GEMINI_API_KEY` | `` (empty) | GeminiClient |
| `GEMINI_MODEL` | `gemini-2.5-flash` | GeminiClient |
| `GRAPH_DB_PATH` | `data/graph.db` | GraphDB |
| `RAW_PAGES_DIR` | `data/raw` | (declared, not actively used in code) |
| `FB_ACCESS_TOKEN` | `` (empty) | No implementation found (UNKNOWN-001) |

## Settings Access Patterns

### Direct import (strongly recurring):
```python
from config.settings import settings
```
- `settings.seed_urls`, `settings.allowed_domains` — hardcoded defaults
- `settings.crawl_*` — crawl parameters
- `settings.gemini_api_key`, `settings.gemini_model` — Gemini config
- `settings.graph_db_abs_path` — property resolving relative to PROJECT_ROOT

### CLI override pattern:
- `--max-depth`, `--max-pages`, `--db-path` override settings values
- Pattern: `crawl_depth = max_depth if max_depth is not None else settings.crawl_max_depth`

## Path Resolution

### OBSERVED:
- `PROJECT_ROOT = Path(__file__).resolve().parent.parent` (in settings.py)
- `graph_db_abs_path` property: resolves relative paths against PROJECT_ROOT
- `raw_pages_abs_dir` property: same pattern
- Scripts use their own `PROJECT_ROOT = Path(__file__).resolve().parent.parent`
  + `sys.path.insert(0, str(PROJECT_ROOT))` for imports

## Hardcoded Data

### In `config/settings.py`:
- `seed_urls` — 5 hardcoded URLs (also documented in README)
- `allowed_domains` — 10 hardcoded domains (also documented in README)

### In `src/extractor/alias_resolver.py`:
- `ALIAS_MAP`, `CANONICAL_ALIASES`, `KNOWN_PERSONS`, `KNOWN_GROUPS`,
  `KNOWN_PLACES`, `GROUP_ALIAS_MAP`, `PLACE_ALIAS_MAP` — all hardcoded

### In `src/extractor/entity_extractor.py`:
- `PERSON_STOPWORDS`, `PERSON_PATTERNS`, `GROUP_PATTERNS`, `PLACE_PATTERNS`,
  `EVENT_TRIGGERS`, `CLAIM_TRIGGERS` — all hardcoded

## Secrets Handling

### OBSERVED:
- `.env` is gitignored (`.gitignore`: `.env*` with `!.env.example`)
- `GEMINI_API_KEY` and `FB_ACCESS_TOKEN` stored in `.env`
- `GeminiClient` stores key in `self._api_key`, never logged
- `.env.example` shows empty values for secrets
- No secrets in any source file or test
