# Workflow: Full Pipeline (Default)

**Entry Point:** `python scripts/01_crawl_and_build_graph.py`
**CLI Framework:** Click (`@click.command()` with options)
**Console Output:** Rich (`Console`, `Table`)

## Execution Path (OBSERVED, ordered)

### 1. Initialization
- `config.settings.settings` loaded from `.env` (Pydantic BaseModel)
- CLI options override: `--max-depth`, `--max-pages`, `--skip-crawl`, `--db-path`
- `GraphDB(db_file)` created — schema initialized via `CREATE TABLE IF NOT EXISTS`
- `EntityExtractor(settings.spacy_model)` — spaCy model loaded (or falls back to rules)
- `ClaimExtractor(extractor)` — wraps entity extractor

### 2. Phase 1: Crawl (skipped if `--skip-crawl`)
- `WebCrawler(seed_urls, allowed_domains, max_depth, max_pages, ...)`
- `crawler.crawl()` → `list[CrawledPage]` (BFS with domain filtering)
- Pages with errors are kept in the list (filtered in Phase 2)

### 3. Phase 2: Extract + Store
- For each page in `pages`:
  - Skip if `page.error` is truthy
  - `process_page(page, extractor, claim_extractor, db)`:
    - Classify source (domain + keyword heuristics)
    - Create Work node + SourceRecord
    - `extractor.extract(page.text)` → entities dict
    - Store persons, groups, places, events (nodes + MENTIONS/DESCRIBES edges)
    - `claim_extractor.extract_claims(page.text, source_url=url)`
    - Store claims (nodes + CONTAINS edges + claim-source links + ASSERTED_BY + ABOUT)
    - Store typed relations (FOUNDED, MEMBER_OF, WORKED_AT, LIVED_AT, LOCATED_IN)

### 4. Phase 3: Detect Contradictions + Timeline
- `ContradictionDetector(db)` instantiated
- `detector.infer_implicit_targets()` — adds ABOUT edges to claims with
  none, inheriting person/group targets from source work's MENTIONS edges
- `detector.detect_contradictions()` — finds claims with opposite stances
  targeting the same node, adds CONTRADICTS edges
- `detector.build_timeline_edges()` — adds PRECEDES edges between dated events

### 5. Summary Output
- Rich Table with counts: Nodes, Edges, Sources, Contradictions, Timeline edges
- Per-node-type breakdown
- `db.close()`
- Hint: `datasette {db_file}` for exploration

## Evidence

| Step | Path | Symbol |
|---|---|---|
| Entry | `scripts/01_crawl_and_build_graph.py` | `main()` |
| Crawl | `src/crawler/web_crawler.py` | `WebCrawler.crawl()` |
| Process | `scripts/_pipeline_helpers.py` | `process_page()` |
| Extract | `src/extractor/entity_extractor.py` | `EntityExtractor.extract()` |
| Claims | `src/extractor/claim_extractor.py` | `ClaimExtractor.extract_claims()` |
| Store | `src/storage/graph_db.py` | `GraphDB.add_node/add_edge/add_source` |
| Detect | `src/extractor/contradiction_detector.py` | `ContradictionDetector.*` |
| Config | `config/settings.py` | `settings` singleton |

## Failure Paths

| Failure | Behavior | Evidence |
|---|---|---|
| spaCy model unavailable | Falls back to rule-based extraction | `_try_load_spacy()` logs warning |
| Network fetch error | Tenacity retries 3x, then error page appended | `web_crawler.py:_fetch()` |
| Non-200 HTTP | Error page appended, no retry | `web_crawler.py:crawl()` |
| Page has error/no text | Skipped in Phase 2 loop | `_pipeline_helpers.py:process_page()` |
| DB closed during use | `RuntimeError("GraphDB is closed")` | `graph_db.py:_get_conn()` |

## Change Guidance

- To add a new extraction phase: add after Phase 3, before summary.
  Update the summary table.
- To change crawl behavior: modify `WebCrawler` or `config/settings.py`
  defaults. CLI overrides already supported.
- To use Gemini instead of spaCy: run `02_gemini_search.py extract`
  instead, or modify the pipeline script to use `GeminiExtractor`.
