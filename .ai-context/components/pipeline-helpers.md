# Component: Pipeline Helpers

**Path:** `scripts/_pipeline_helpers.py` (312 LOC)
**Type:** Integration layer — extraction → storage bridge

## Responsibility

Contains `process_page()`, the sole function that takes a crawled page,
runs entity/claim extraction, and stores all results (nodes, edges,
sources, claim-source links) in the graph database. Also contains
`classify_source()` for heuristic source classification.

## Interface

```python
def classify_source(url: str, title: str, text: str) -> tuple[SourceClass, BiasHint]

def process_page(
    page: CrawledPage,
    extractor: EntityExtractor,      # or GeminiExtractor (duck-typed)
    claim_extractor: ClaimExtractor,  # or GeminiClaimExtractor (duck-typed)
    db: GraphDB,
) -> None
```

`process_page()` is **duck-typed** — it accepts any extractor that
returns the `{persons, groups, places, events, claims, relations}` dict
shape, and any claim extractor with `extract_claims(text, source_url)`.
This is what makes `GeminiExtractor` a drop-in replacement.

## What process_page Does (OBSERVED, ordered)

1. Skip if `page.error` or no `page.text`
2. Classify source (domain heuristics + keyword matching)
3. Create **Work node** + **SourceRecord** (ID = `work_id(url)`)
4. Call `extractor.extract(page.text)` → entities dict
5. For each **person**: create Person node, add MENTIONS edge (work→person)
6. For each **group**: create Group node, add MENTIONS edge
7. For each **place**: create Place node, add MENTIONS edge
8. For each **event**: create Event node, add DESCRIBES edge (work→event)
9. Call `claim_extractor.extract_claims(page.text, source_url=url)`
10. For each **claim**: create Claim node, add CONTAINS edge (work→claim),
    add claim-source link, add ASSERTED_BY edge if speaker, add ABOUT
    edges to targets (creating target nodes if needed)
11. For each **relation**: add typed edge (FOUNDED, MEMBER_OF, WORKED_AT,
    LIVED_AT, LOCATED_IN) between resolved src/dst IDs

## Dependencies

| Dependency | Type | Evidence |
|---|---|---|
| `src.crawler.web_crawler.CrawledPage` | code | input type |
| `src.extractor.alias_resolver` | code | ID functions (person_id, group_id, etc.) |
| `src.extractor.claim_extractor.ClaimExtractor` | code | duck-typed input |
| `src.extractor.entity_extractor.EntityExtractor` | code | duck-typed input |
| `src.storage.graph_db.GraphDB` | code | output target |
| `src.storage.models` | code | GraphNode, GraphEdge, SourceRecord, enums |
| `src.utils.text_utils.get_domain` | code | source classification |

## Consumers

| Consumer | How |
|---|---|
| `scripts/01_crawl_and_build_graph.py` | Called per crawled page in Phase 2 loop |
| `scripts/02_gemini_search.py` | Called in `extract` subcommand with Gemini extractors |
| `tests/integration/test_pipeline.py` | `test_process_page_builds_graph()` — full integration test |

## Change Guidance

- **Adding new entity types to `process_page()`:** Must handle the new
  type in the storage loop. The `_REL_TYPE_MAP` may need updates if new
  relation types are introduced.
- **Changing source classification heuristics:** Low risk to code, but
  changes `SourceClass`/`BiasHint` assignments, affecting graph analysis.
  No dedicated unit test for `classify_source()` exists (DEBT-003).
- **Adding new edge types:** Update `_REL_TYPE_MAP` to map extractor
  relation strings to `RelationType` enum values.
- **This is the integration seam:** Any change to the extractor return
  shape or the storage API requires updating this function.
