# Components Index

| Component | File | Responsibility |
|---|---|---|
| [Graph DB](graph-db.md) | `src/storage/graph_db.py` | SQLite property graph storage |
| [Entity Extractor](entity-extractor.md) | `src/extractor/entity_extractor.py` | spaCy NER + rule-based extraction |
| [Pipeline Helpers](pipeline-helpers.md) | `scripts/_pipeline_helpers.py` | Per-page entity/claim/relation storage |
| [LLM Layer](llm-layer.md) | `src/llm/` | Gemini-powered extraction, Q&A, seed discovery |
| [Web Crawler](web-crawler.md) | `src/crawler/web_crawler.py` | BFS domain-filtered crawler |

## Supporting Components (not separate files)

| Component | File | Responsibility |
|---|---|---|
| Alias Resolver | `src/extractor/alias_resolver.py` | Canonical name normalization + ID generation |
| Claim Extractor | `src/extractor/claim_extractor.py` | Wraps entity extractor's claim detection with IDs |
| Contradiction Detector | `src/extractor/contradiction_detector.py` | Opposite-stance detection + timeline edges |
| Data Models | `src/storage/models.py` | Pydantic models + enums |
| Text Utils | `src/utils/text_utils.py` | Normalization, hashing, HTML cleaning, dates |
| Config | `config/settings.py` | Pydantic settings from `.env` |
| Pipeline CLI | `scripts/01_crawl_and_build_graph.py` | Click CLI orchestrator |
| Gemini CLI | `scripts/02_gemini_search.py` | Click CLI for Gemini features |
