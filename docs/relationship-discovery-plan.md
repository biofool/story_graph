# Relationship Discovery Plan — Adapting WorldStudioFinder Google API Searches for Story Graph (issue #21)

> **Status:** PLANNING document — no further implementation required for this
> issue. Phase 0 (the search infrastructure) is already implemented in the
> Story Graph (see "Current implementation state" below). This document is
> the canonical plan for Phases 1–4.
>
> **Reviewed against:**
> - WorldStudioFinder search infrastructure: `src/discovery/knowledge_graph_client.py`, `src/scrapers/` (QuotaBudget, places_api_cache, dedup_check), `src/utils/api_usage.py`
> - Story Graph search infrastructure: `src/search/` (relationship_searcher.py, brave_search_client.py, kg_client.py, quota.py, search_cache.py), `scripts/22_relationship_search.py`, `scripts/23_ingest_nadeau_relationships.py`

## Current implementation state (Phase 0 — DONE)

The following Phase 0 files already exist and are committed in the Story Graph:

| File | Status | Source |
|---|---|---|
| `src/search/relationship_searcher.py` | ✅ implemented | query builder + entity-pair generator + priority scoring; loads templates from `data/search_terms/relationship_templates.json` |
| `src/search/brave_search_client.py` | ✅ implemented | Brave Web Search API wrapper (X-Subscription-Token, 2K queries/month free tier) |
| `src/search/kg_client.py` | ✅ implemented | Google Knowledge Graph Search API client (ported from WorldStudioFinder `src/discovery/knowledge_graph_client.py`) |
| `src/search/quota.py` | ✅ implemented | QuotaBudget + API usage tracking (ported from WorldStudioFinder `src/scrapers/google_places_api.py:QuotaBudget` + `src/utils/api_usage.py`) |
| `src/search/search_cache.py` | ✅ implemented | SQLite query cache, SHA-256 key, 30-day TTL (ported from WorldStudioFinder `places_api_cache`) |
| `scripts/22_relationship_search.py` | ✅ implemented | CLI orchestrator with review gates |
| `scripts/23_ingest_nadeau_relationships.py` | ✅ implemented | ingests discovered Nadeau-lineage relationships into the graph |

Remaining Phase 0 items not yet done: `TRAINED_WITH`, `STUDENT_OF`, `TAUGHT`
edge types are not yet in the graph schema (the existing `MEMBER_OF` edge is
used for student-teacher relationships, e.g. `person:dan-millman --MEMBER_OF--> person:robert-nadeau`).

---

# Plan: Adapt WorldStudioFinder Google API searches for targeted Story Graph expansion

## Problem statement

The Story Graph currently holds **397 Person nodes**, **318 Group nodes**, **185 Place nodes**, and **5,257 sources** — but the graph is sparse on **relationships between people**. A spot check of four martial-arts figures known to be interconnected reveals the gap:

| Person | Node exists? | Edges FROM person | Direct edges to other 3? |
|---|---|---|---|
| `person:dan-millman` | Yes | 2 (MEMBER_OF aikido, WORKED_AT oberlin/stanford) | **0** |
| `person:robert-nadeau` | Yes | 2 (MEMBER_OF CAA, WORKED_AT Castro St dojo) | **0** |
| `person:richard-moon` | No (47 claims mention him, no Person node) | 0 | **0** |
| `person:bob-noha` | Yes | 0 | **0** |

The user has firsthand knowledge that Dan Millman trained with Robert Nadeau and/or Richard Moon and/or Bob Noha — but the graph contains **no edges documenting any of these relationships**, and Richard Moon lacks a Person node entirely. This pattern repeats across the martial-arts and cult/NRM coverage areas: we have nodes and claims, but the **inter-personal and inter-organizational connection fabric** is thin.

The `../WorldStudioFinder` repository contains a mature, production-tested Google API search infrastructure (Places API, Geocoding API, Knowledge Graph Search API, Gemini + Google Search grounding, Brave Search skills). This issue proposes a plan to adapt those capabilities — **not for location-based place discovery, but for relational entity search**: systematically finding documentation of connections between people, groups, places, and events that the graph already knows about.

## What WorldStudioFinder has that Story Graph can use

### Directly portable

| Component | WorldStudioFinder location | What it does | Story Graph adaptation |
|---|---|---|---|
| **Knowledge Graph Search API client** | `src/discovery/knowledge_graph_client.py` | Resolves entity names to canonical URLs, types, and metadata via `kgsearch.googleapis.com/v1/entities:search`. Free tier: 100K req/day. | Resolve Person/Group/Place nodes to canonical Knowledge Graph IDs, Wikipedia URLs, and official websites. Detect when two entities share a KG entry or are related. |
| **Gemini + Google Search grounding** | `src/ai/gemini_batch_client.py`, Story Graph's own `src/llm/seed_discoverer.py` | Natural-language queries grounded in live Google Search, returning source URLs. | Query for relationships: *"Find documentation of Dan Millman training with Robert Nadeau"* — returns grounded source URLs. |
| **Brave Search skills** | `.devin/skills/web-search/`, `news-search/`, `images-search/`, `videos-search/`, `bx/` | Token-budgeted web/news/image/video search with snippets, URLs, thumbnails. Pre-extracted content optimized for LLM ingestion. | Systematic web search for relationship documentation, interview transcripts, seminar records, lineage charts, old dojo photos. |
| **API usage tracking + quota budgets** | `src/utils/api_usage.py`, `src/scrapers/google_places_api.py:QuotaBudget` | Per-provider call logging, free-tier alerts, session/monthly budget caps with halt-on-exceed. | Track Gemini/Brave/KG call counts and costs. Halt when free tiers approach limits. |
| **Persistent query caching** | `src/scrapers/places_api_cache.py` | SQLite cache keyed by SHA-256(query+params), 30-day TTL, empty results not cached. | Cache all search queries to avoid re-spending quota on identical relationship queries. |
| **Deduplication** | `src/scrapers/dedup_check.py` | Filters by place_id, normalized phone, website domain, (name, city). | Adapt to dedup by URL, normalized title, and (entity_a, entity_b, relationship) tuple. |
| **Tiered web retrieval** | Story Graph's own `src/crawler/fetch_page.py` | Direct fetch with browser headers, Wayback fallback, Brotli, protocol-relative URL fix. | Already in place — use to fetch and ingest discovered sources. |

### Not portable / needs redesign

| Component | Why not directly portable |
|---|---|
| **Places API `searchText`** | Returns businesses/venues, not relationships between people. Useful only for finding dojo/organization locations — a secondary use case. |
| **Playwright Google Maps scraper** | Browser automation for place discovery. Story Graph needs document/article discovery, not map scraping. |
| **CityTargetProvider / grid search** | Location-based anchor generation. Story Graph's "anchors" are entity pairs, not geographic coordinates. |
| **Google Sheets sync** | WorldStudioFinder uses Sheets as both config and result sink. Story Graph uses GitHub issues and graph snapshots. |
| **Studio data model** | Business-centric (rating, review_count, place_id). Story Graph needs Source/Claim/Edge records. |

## Proposed search architecture

```
                    ┌─────────────────────────────────┐
                    │   Entity Pair Generator          │
                    │   (from existing graph nodes)    │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │   Query Builder                  │
                    │   (relationship-aware templates) │
                    └──────────────┬──────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
    ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────┐
    │ Brave Web Search│  │ Gemini Grounded  │  │ Knowledge Graph   │
    │ (snippets+URLs) │  │ Search (NL query)│  │ API (entity resolve)│
    └────────┬────────┘  └────────┬─────────┘  └─────────┬─────────┘
             │                    │                      │
             └────────────────────┼──────────────────────┘
                                  ▼
                    ┌─────────────────────────────────┐
                    │   Result Normalizer + Dedup      │
                    │   (URL, title, snippet,          │
                    │    entity_pair, query, provider) │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │   Source Quality Triage          │
                    │   (accessible? relevant?         │
                    │    primary? secondary? tertiary?)│
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │   HUMAN REVIEW GATE              │
                    │   (review queue → approve/reject)│
                    └──────────────┬──────────────────┘
                                   │ approved
                    ┌──────────────▼──────────────────┐
                    │   Fetch + Ingest Pipeline        │
                    │   (fetch_page.py → extraction    │
                    │    → Source/Claim/Edge records)  │
                    └──────────────┬──────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │   Graph Snapshot Export          │
                    │   + Data Ticket Generation       │
                    └─────────────────────────────────┘
```

### Key design principle: search is discovery, not verification

Google/Brave/Gemini search results are **leads**, not evidence. A search snippet saying "Millman trained with Nadeau" is a discovery lead. The source must be fetched, read, and ingested as a `SourceRecord` with claims before it becomes graph evidence. The human review gate ensures no search snippet is auto-ingested as a claim.

## Query-generation strategy

### Relationship query templates

The core innovation is generating **entity-pair queries** rather than single-entity queries. Templates:

| Template | Example query | Target edge type |
|---|---|---|
| `"{person_a}" "{person_b}" training` | `"Dan Millman" "Robert Nadeau" training` | TRAINED_WITH |
| `"{person_a}" "{person_b}" aikido` | `"Dan Millman" "Robert Nadeau" aikido` | MENTIONS |
| `"{person_a}" "{person_b}" seminar` | `"Dan Millman" "Bob Noha" seminar` | ATTENDED_WITH |
| `"{person_a}" "{person_b}" dojo` | `"Robert Nadeau" "Bob Noha" dojo` | TRAINED_AT |
| `"{person_a}" student of "{person_b}"` | `"Dan Millman" student of "Robert Nadeau"` | STUDENT_OF |
| `"{person_a}" taught "{person_b}"` | `"Robert Nadeau" taught "Dan Millman"` | TAUGHT |
| `"{person_a}" "{person_b}" interview` | `"Dan Millman" "Richard Moon" interview` | MENTIONS |
| `"{person_a}" "{person_b}" lineage` | `"Dan Millman" "Robert Nadeau" lineage` | LINEAGE |
| `"{person_a}" "{person_b}" {style}` | `"Sig Kufferath" "Robert Nadeau" danzan` | MENTIONS |
| `"{group_a}" "{person_b}"` | `"Aikido of San Francisco" "Robert Nadeau"` | MEMBER_OF |

### Entity-pair generation

Not all pairs are worth searching. Priority scoring:

1. **Same domain, no existing edge** — highest priority (e.g., two aikido persons with no edge between them)
2. **Same geographic area, no existing edge** — high (e.g., two persons who both WORKED_AT Bay Area locations)
3. **Same time period, no existing edge** — medium (requires birth/active dates)
4. **User-specified pairs** — always searched regardless of score (e.g., "find documentation of Dan Millman + Robert Nadeau + Richard Moon + Bob Noha")
5. **Existing edge, low source count** — medium (find additional sources for known relationships)

### Single-entity enrichment queries

For nodes with thin sourcing (e.g., `person:bob-noha` has 0 outgoing edges):

| Template | Example |
|---|---|
| `"{person}" aikido biography` | `"Bob Noha" aikido biography` |
| `"{person}" {style} instructor` | `"Bob Noha" aikido instructor` |
| `"{person}" {organization} member` | `"Bob Noha" California Aikido Association` |
| `"{person}" seminar {year}` | `"Bob Noha" seminar 1970` |
| `"{person}" interview martial arts` | `"Richard Moon" interview martial arts` |

## Target-entity prioritization

### Phase 1: Martial arts relational web (highest value)

Based on current graph coverage and the user's known knowledge gaps:

**Priority cluster A — Bay Area Aikido lineage:**
- Dan Millman ↔ Robert Nadeau ↔ Richard Moon ↔ Bob Noha
- Robert Nadeau ↔ Sig Kufferath (partially documented, needs more sources)
- Richard Bunch ↔ Robert Nadeau ↔ Sig Kufferath (the "operational link" claim needs independent sourcing)

**Priority cluster B — Danzan-ryu / Kodenkan lineage:**
- Sig Kufferath ↔ Henry Okazaki (documented but could be enriched)
- Sig Kufferath ↔ AJJF / Kilohana / KDRJA founders
- Sig Kufferath ↔ Pacific Judo Academy

**Priority cluster C — Aikido lineage broader:**
- Robert Nadeau ↔ Morihei Ueshiba (O-Sensei)
- Robert Nadeau ↔ California Aikido Association members
- Aikido Journal ↔ key figures it has documented

### Phase 2: Source-thin persons (enrichment)

Persons with 0–2 outgoing edges are candidates for single-entity enrichment search. Current count: **~280 of 397 persons** have fewer than 3 outgoing edges.

### Phase 3: Cult/NRM cross-references

- Source Family ↔ martial arts crossover (Father Yod/Baker was a Marine; any martial arts connections?)
- Yogi Bhajan / 3HO ↔ Sikh Dharma lineage
- Rajneesh ↔ documented members

### Phase 4: Wikipedia citation gap research

Following the pattern established in issue #20 (Dan Millman Wikipedia improvements):
- Find sources for `[citation needed]` claims in Wikipedia articles on graph entities
- Find sources for missing sections (e.g., Dan Millman's judo/karate background)

## Source quality and provenance rules

### Source tiering

| Tier | Definition | Handling |
|---|---|---|
| **Primary** | Firsthand account, interview, autobiography, official record | Highest confidence; can support claims alone |
| **Secondary** | News article, scholarly paper, documentary citing primary sources | High confidence; prefer with corroboration |
| **Tertiary** | Encyclopedia, directory, aggregator (Wikipedia, Alchetron) | Medium confidence; use for discovery, seek primary sources |
| **Snippet** | Search result snippet only (not fetched) | **Never ingested as evidence** — used only as discovery lead |
| **User assertion** | `kkron://` personal communication | First-class evidence per AGENTS.md; preserved alongside other sources |

### Provenance requirements

Every ingested source must record:
- `source_url` — canonical URL
- `discovered_via` — which search query + provider found it
- `discovered_at` — timestamp
- `fetch_status` — fetched / Wayback / 403 / 404 / JS-rendered
- `tier` — primary / secondary / tertiary
- `reviewer` — who approved it (GitHub username or `auto` with justification)

### Conflicting evidence handling

Per AGENTS.md: when sources conflict, **preserve both claims** with provenance. Do not silently drop either. Record a `CONTRADICTS` edge between the conflicting claims.

## Claim verification workflow

```
1. SEARCH     →  Query generated, executed via Brave/Gemini/KG
2. COLLECT    →  Results normalized, deduplicated, cached
3. TRIAGE     →  Auto-classify: accessible? relevant? likely tier?
4. FETCH      →  fetch_page.py retrieves full content (with Wayback fallback)
5. EXTRACT    →  Rule-based or Gemini extraction of entities/claims/relations
6. REVIEW     →  Human reviews extracted claims against source text
7. INGEST     →  Approved claims → SourceRecord + Claim + Edge records
8. EXPORT     →  Graph snapshot updated; data ticket generated if needed
```

### Human review gate

- **Auto-reject:** search snippets never fetched, JS-rendered pages with no extractable text, 403/404 sources
- **Auto-accept (with logging):** sources from already-trusted domains (Wikipedia, Aikido Journal, danzan.com, kodenkan.com) where extraction is clean
- **Human review required:** all other sources, all conflicting claims, all `kkron` assertions that lack independent corroboration

## Deduplication and canonicalization

### URL-level dedup
- Normalize URLs (strip tracking params, lowercase scheme/host)
- Dedup by canonical URL
- Cross-reference with Wayback Machine URLs (treat archive.org snapshot as same source)

### Entity-pair dedup
- Cache key: `SHA-256(sorted(entity_a, entity_b) + relationship_type + query)`
- Skip re-searching pairs already searched within cache TTL (30 days default)

### Source-level dedup
- If a discovered URL is already a `SourceRecord` in the graph, skip ingestion but log that it was re-discovered (useful for source-quality scoring)

## Respectful crawling and rate controls

| Control | Value | Rationale |
|---|---|---|
| Inter-query delay | 2–5 seconds (randomized) | Avoid hammering search APIs |
| Max queries per session | 100 | Bounded sessions for reviewability |
| Fetch delay | 1–3 seconds (randomized) | Respect target servers |
| Fetch timeout | 30 seconds | Don't hang on slow servers |
| Retry on transient failure | 3 retries with exponential backoff | Standard resilience |
| Retry on 403/WAF | 0 (skip and log) | Don't fight WAFs — record as inaccessible |
| Robots.txt | Check before fetching | Respect crawl directives |
| User-Agent | Browser-like (already in `fetch_page.py`) | Avoid blocks without deception |

## Cost and quota controls

### Free-tier-first strategy

| API | Free tier | Story Graph expected usage | Cost |
|---|---|---|---|
| Brave Search | 2,000 queries/month (free tier) | ~100–200 queries/session, 1–2 sessions/month | $0 if within free tier |
| Gemini (Google Search grounding) | Free tier via `GEMINI_API_KEY` | ~50–100 grounded queries/session | $0 if within free tier |
| Knowledge Graph Search API | 100,000 requests/day | ~50–200 entity resolutions/session | $0 |
| Google Places API | $200/month free credit (Maps platform) | Minimal (dojo location enrichment only) | $0 if within credit |

### Budget enforcement

Port `QuotaBudget` pattern from WorldStudioFinder:
- `SEARCH_SESSION_BUDGET_QUERIES` (default 100)
- `SEARCH_MONTHLY_BUDGET_QUERIES` (default 2,000 — Brave free tier)
- `GEMINI_MONTHLY_BUDGET_CALLS` (default 250 — conservative free-tier estimate)
- Halt on budget exceeded; log clearly; do not silently skip

### Caching to reduce calls

- All search queries cached in SQLite (SHA-256 key, 30-day TTL)
- Knowledge Graph results cached per entity (permanent — entity metadata rarely changes)
- Re-runs skip cached queries entirely

## Human review gates

### Gate 1: Query plan review (before searching)
- Generated query plan is written to `data/search_runs/{timestamp}_plan.json`
- User reviews the entity pairs and query templates
- User can add/remove pairs, modify templates, or approve as-is
- **No searches executed until plan is approved**

### Gate 2: Source triage review (after searching, before fetching)
- Search results written to `data/search_runs/{timestamp}_results.json`
- User reviews discovered URLs, snippets, and auto-tier classification
- User approves/rejects individual URLs for fetching
- **No pages fetched until URLs are approved**

### Gate 3: Claim review (after extraction, before ingestion)
- Extracted claims written to `data/search_runs/{timestamp}_claims.json`
- User reviews claims against source text
- User approves/rejects individual claims
- **No claims ingested into graph until approved**

### Gate 4: Post-ingestion audit
- Data ticket generated via `scripts/19_generate_data_ticket.py` for each entity pair
- Diff of graph edges before/after ingestion
- User reviews the diff

## Expected outputs and graph changes

### Per search session (estimated)
- 50–100 discovered source URLs (after dedup)
- 20–40 fetched and parsed sources
- 10–30 new `SourceRecord` entries
- 5–20 new `Claim` entries
- 3–15 new `Edge` entries (primarily `MENTIONS`, `MEMBER_OF`, `WORKED_AT`, `TRAINED_WITH`)
- 1–5 new `Person` or `Group` nodes (for entities discovered during search)
- 1 data ticket per priority cluster

### Graph quality improvements
- Increase average edges-per-person from current ~0.5 to target ~2.0
- Reduce persons with 0 outgoing edges from ~280 to <100
- Add `TRAINED_WITH`, `STUDENT_OF`, `TAUGHT` edge types (currently absent)
- Document the Millman–Nadeau–Moon–Noha relationship cluster

## Testing and validation plan

### Unit tests
- Query builder: verify template expansion, entity-pair generation, priority scoring
- Result normalizer: verify dedup, URL normalization, tier classification
- Cache: verify hit/miss, TTL expiry, empty-result handling

### Integration tests
- Mock search API responses → verify full pipeline (search → triage → fetch → extract → ingest)
- Verify budget enforcement halts at configured limits
- Verify human review gates block pipeline stages until approved

### Validation against known truth
- Run the Millman–Nadeau–Moon–Noha cluster search
- Verify that at least one source documenting the relationship is discovered
- Verify the ingested claims match the user's firsthand knowledge
- Verify `kkron` assertions are preserved alongside discovered sources

## Rollout phases

### Phase 0: Foundation (this issue)
- [ ] Create `src/search/relationship_searcher.py` — query builder + entity-pair generator
- [ ] Create `src/search/brave_search_client.py` — Brave Search API wrapper (or use WorldStudioFinder skills)
- [ ] Port `KnowledgeGraphClient` from WorldStudioFinder as `src/search/kg_client.py`
- [ ] Port `QuotaBudget` + `api_usage` tracking as `src/search/quota.py`
- [ ] Port `places_api_cache` pattern as `src/search/search_cache.py`
- [ ] Create `scripts/22_relationship_search.py` — CLI orchestrator with review gates
- [ ] Add `data/search_terms/relationship_templates.json` — query template data file
- [ ] Add `TRAINED_WITH`, `STUDENT_OF`, `TAUGHT` edge types to graph schema

### Phase 1: Martial arts relational web
- [ ] Run Millman–Nadeau–Moon–Noha cluster search
- [ ] Run Nadeau–Kufferath–Bunch cluster search
- [ ] Run Danzan-ryu lineage cluster search
- [ ] Generate data tickets for each cluster
- [ ] Verify graph edges match known relationships

### Phase 2: Source-thin person enrichment
- [ ] Identify all persons with 0–2 outgoing edges
- [ ] Generate single-entity enrichment queries
- [ ] Run in bounded sessions (100 queries max)
- [ ] Review and ingest approved sources

### Phase 3: Cult/NRM cross-references
- [ ] Source Family ↔ martial arts crossover search
- [ ] Yogi Bhajan / 3HO lineage search
- [ ] Cross-reference with existing cult/NRM coverage

### Phase 4: Wikipedia citation gap research
- [ ] Identify Wikipedia articles on graph entities with `[citation needed]`
- [ ] Generate citation-gap queries
- [ ] Find and ingest sources that fill citation gaps
- [ ] Generate Wikipedia improvement tickets (following issue #20 pattern)

## Acceptance criteria

1. **Millman–Nadeau–Moon–Noha cluster documented**: At least 2 independent sources discovered and ingested documenting relationships between these four persons. Graph contains edges connecting them. Richard Moon has a `Person` node.
2. **Search infrastructure reusable**: Running `scripts/22_relationship_search.py --entities "person:a" "person:b" --dry-run` produces a reviewable query plan without executing searches.
3. **Human review gates functional**: Each gate (plan, triage, claim, audit) produces a JSON artifact in `data/search_runs/` and blocks the next stage until approved.
4. **Quota enforcement works**: Session halts when `SEARCH_SESSION_BUDGET_QUERIES` is reached. Monthly counter persists across sessions.
5. **Caching works**: Re-running the same query within TTL returns cached results without API calls.
6. **Provenance preserved**: Every ingested source records `discovered_via`, `discovered_at`, `fetch_status`, `tier`, and `reviewer`.
7. **`kkron` assertions preserved**: Personal communication assertions are never dropped or deprioritized. Conflicting sources are recorded with `CONTRADICTS` edges.
8. **No secrets exposed**: API keys are read from environment variables only. No key values are logged or committed.

## Risks, limitations, and non-goals

### Risks
- **Search API quota exhaustion**: Brave free tier is 2K/month. Aggressive sessions could exhaust it. Mitigation: caching + monthly budget caps.
- **Low-quality sources**: Web search returns SEO spam, AI-generated content, and aggregators. Mitigation: tier classification + human review gate.
- **False relationship inference**: A search for "Dan Millman" "Robert Nadeau" might return pages that mention both but don't document a relationship. Mitigation: extraction must verify the relationship is stated, not just co-mentioned.
- **WAF blocks**: AJJF, Jujitsu America, and other sites return 403. Mitigation: Wayback fallback + record as inaccessible (don't fight WAFs).
- **Knowledge Graph coverage gaps**: KG may not have entries for obscure martial arts figures. Mitigation: KG is one of three search providers; not a single point of failure.

### Limitations
- Search results are in English only (Brave/Gemini default). Non-English sources (Japanese aikido archives, Hawaiian danzan-ryu records) will be missed.
- Image/video search can find photos of people together but cannot auto-verify the relationship type.
- Knowledge Graph API returns entity metadata, not relationship metadata — it resolves entities, not connections between them.

### Non-goals
- **Not building a general-purpose web crawler** — this is targeted relational search, not open-ended crawling.
- **Not auto-ingesting search snippets as claims** — snippets are leads only.
- **Not replacing the existing BFS crawler** (`scripts/01_crawl_and_build_graph.py`) — this is a complementary discovery layer.
- **Not modifying WorldStudioFinder** — this repo borrows patterns and code, not the other repo.
- **Not deploying external services** — runs locally or on Oracle Always Free infrastructure.
- **Not location-based place discovery** — the primary use case is relational entity search. Places API is secondary.

## Suggested implementation files / sub-issues

| File | Purpose | Sub-issue? |
|---|---|---|
| `src/search/relationship_searcher.py` | Query builder + entity-pair generator + priority scoring | #21 |
| `src/search/brave_search_client.py` | Brave Search API wrapper (web + news + images) | #22 |
| `src/search/kg_client.py` | Knowledge Graph Search API client (ported from WorldStudioFinder) | #23 |
| `src/search/quota.py` | QuotaBudget + API usage tracking (ported from WorldStudioFinder) | #24 |
| `src/search/search_cache.py` | SQLite query cache (ported from WorldStudioFinder places_api_cache) | #25 |
| `src/search/result_normalizer.py` | URL normalization, dedup, tier classification | #26 |
| `scripts/22_relationship_search.py` | CLI orchestrator with human review gates | #27 |
| `data/search_terms/relationship_templates.json` | Query template data file | (part of #21) |
| `data/search_runs/` | Output directory for plan/results/claims/audit JSON | (part of #27) |

## References

- WorldStudioFinder Knowledge Graph client: `../WorldStudioFinder/src/discovery/knowledge_graph_client.py`
- WorldStudioFinder quota/budget: `../WorldStudioFinder/src/scrapers/google_places_api.py` (QuotaBudget, line 86)
- WorldStudioFinder API usage tracking: `../WorldStudioFinder/src/utils/api_usage.py`
- WorldStudioFinder Places API cache: `../WorldStudioFinder/src/scrapers/places_api_cache.py`
- Story Graph existing seed discovery: `src/llm/seed_discoverer.py`
- Story Graph Gemini client with grounding: `src/llm/gemini_client.py` (generate_grounded, line 207)
- Story Graph tiered web retrieval: `src/crawler/fetch_page.py`
- Story Graph reference discovery: `scripts/15_discover_references.py`
- Story Graph data ticket generator: `scripts/19_generate_data_ticket.py`
- Story Graph project rules: `AGENTS.md` (kkron assertions are first-class evidence)
- Existing issues: #19 (Kufferath data ticket), #20 (Dan Millman Wikipedia improvements)

