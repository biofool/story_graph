# System Overview

## A. System Context

### Users
- **Researcher** (OBSERVED): Runs the CLI pipeline locally to build and
  explore the SQLite graph. No authentication, no multi-user access.
  Single-user, local-execution model.

### External Systems
| System | Interaction | Evidence |
|---|---|---|
| Web (blogs, Wikipedia, etc.) | HTTP GET crawling via `requests` | `src/crawler/web_crawler.py` |
| Google Gemini API | Structured JSON, text, grounded search | `src/llm/gemini_client.py` |
| Meta/Facebook Graph API | DECLARED in `docs/` + `.env.example:FB_ACCESS_TOKEN` | No implementation code found (UNKNOWN-001) |
| spaCy NLP models | Local model load (`en_core_web_sm`) | `src/extractor/entity_extractor.py` |
| datasette | Optional SQLite web explorer (manual) | `README.md` |

### Trust Boundaries
1. **Network → Local:** Crawler fetches untrusted HTML from allowed
   domains. HTML is parsed with BeautifulSoup (lxml parser). Text is
   cleaned via regex in `text_utils.clean_text()`.
2. **Gemini API → Local:** Gemini responses are parsed as JSON;
   `_normalize()` in `entity_claim_extractor.py` validates structure
   before use.
3. **No inbound trust boundary:** No server, no API endpoint, no
   authentication system. The application is a batch CLI tool.

### Data Flows
```
Web pages → WebCrawler.crawl() → CrawledPage[]
    → process_page() → EntityExtractor.extract() / GeminiExtractor.extract()
        → persons, groups, places, events, claims, relations
    → GraphDB.add_node() / add_edge() / add_source()
    → SQLite (data/graph.db)

SQLite → ContradictionDetector.detect_contradictions() → CONTRADICTS edges
SQLite → ContradictionDetector.build_timeline_edges() → PRECEDES edges
SQLite → GraphQA.answer() → Gemini → QAResponse
```

## B. Deployable Units

| Unit | Type | Entry Point | Evidence |
|---|---|---|---|
| Pipeline CLI | CLI script | `scripts/01_crawl_and_build_graph.py` | OBSERVED: Click command `main()` |
| Gemini CLI | CLI script | `scripts/02_gemini_search.py` | OBSERVED: Click group `cli()` with 3 subcommands |
| SQLite graph | Local file DB | `data/graph.db` | OBSERVED: `config/settings.py` default path |

**No web server, no worker, no job scheduler, no Dockerfile, no IaC.**
This is a single-process, local-execution research tool.

## C. Component Map

See [`components/index.md`](../components/index.md) for per-component detail.

## D. Runtime/Code Paths

See [`workflows/index.md`](../workflows/index.md) for end-to-end path tracing.

## E. Change Impact Summary

See [`change-impact/relationships.yaml`](../change-impact/relationships.yaml)
for the full dependency/dependents map.

Key high-impact components (OBSERVED):
1. **`src/storage/graph_db.py`** — all persistence; schema changes affect
   every other component that reads/writes the graph.
2. **`scripts/_pipeline_helpers.py`** — `process_page()` is the sole
   integration point between extractors and storage.
3. **`src/storage/models.py`** — enum changes (NodeType, RelationType)
   ripple through extractors, storage, and tests.
4. **`src/extractor/alias_resolver.py`** — ID generation functions
   (`person_id`, `group_id`, etc.) are used by extractors, pipeline
   helpers, and tests. Changing ID format invalidates existing graphs.
