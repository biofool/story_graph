# Story Graph — PRD: Search Engine Strategy

## Purpose

This PRD defines which search engines the enrichment pipeline uses,
when to use each one, what API keys they require, and how they fail over.

## JEV bounded-decision availability

JEV (`jev-latest` / `typesafe/jev-1.13`) is available to annotate extracted
claims as `supported`, `contradicted`, or `unresolved` against their source
evidence. Extraction remains Gemini/open-ended LLM work; JEV is only the
bounded verification layer. It is off by default (`JEV_CLAIM_VERIFY=1` enables
it), and its verdict/confidence are annotations: claims are never dropped. API
failure produces `unverified` and preserves the claim.

**Credentials (verified live 2026-09-21):** this repo's key is a **direct
TypeSafe API key** (not an OpenRouter key). It is stored in `.env` as
`JEV_API_KEY` and in GCP Secret Manager `quantum-aikido-coaching/JEV_API_KEY`.
The client defaults to the OpenRouter Decisions endpoint, so `.env` also pins
`JEV_BASE_URL=https://api.typesafe.ai/v1/systemone` and `JEV_MODEL=jev-latest`
— without those overrides the direct key gets a 401 from OpenRouter. Verified:
`verify_claim` returns `supported`/`unresolved` verdicts correctly over the
TypeSafe endpoint.

Report intent/actual to CloudManagement as provider `typesafe`, API
`systemone`, decision kind `claim_verification` (the OpenRouter
`openrouter`/`decisions` pair applies only when an OpenRouter-format key is
used). Promotion beyond annotation requires a labeled benchmark,
confidence/disagreement policy, current pricing, and a project budget.

### Candidate JEV decision kinds (assessed 2026-09-21)

Bounded decisions where JEV's typed answers fit story_graph's pain points.
All remain **unimplemented / shadow-only** until each has a labeled eval set,
confidence/disagreement policy, and is registered as a decision kind in
CloudManagement's `docs/per-repo-api-specs.md` §6A. Priority order:

| Decision kind | Bounded question | Where it applies | Pain point it addresses |
|---|---|---|---|
| `identity_match` | Choice `{same_person, different_person, insufficient_evidence}` — does this text refer to the same person as a known identity card? | Corpus triage (`scripts/42-44`), `--taught-by` ingest screening (`scripts/48`), newspaper hit filtering | The dominant manual cost in this project: 700+ newspaper pages hand-triaged for "which Hiroshi Ikeda / Richard Moon" (bonsai Ikeda, Tadanori Ikeda, rugby Moon, Sir Richard Moon). JEV gets the candidate text + an identity card (affiliations, dates, places) as state. |
| `entity_resolution` | Choice `{same_entity, alias_only, different_entities, uncertain}` for a node pair | Dedup pipeline (`scripts/50` pattern), ingest-time alias detection | Duplicate person/dojo nodes (`person-richard-moon` vs `person:richard-moon-aikido`, 8 Kufferath nodes). Human stays final authority; JEV ranks/groups candidate pairs. |
| `event_dedup` | Choice `{same_event, different_event, uncertain}` for event pairs sharing venue/date overlap | Post-ingest maintenance | The AikiWeb ingest produced literal duplicate edges; deterministic IDs don't catch near-dupes across sources. |
| `source_relevance` | Score 1-5 — how likely is this search-result snippet to document the research target? | `scripts/42` before download/OCR | Would have flagged the 201 Japan-query pages as collision-noise *before* extraction cost; prioritizes quota spend. |
| `disposition_classify` | Choice `{collision, unrelated, same_context, keep}` + named collision target | `scripts/44`-style terminal-node cleanup | Formalizes today's hand-written `disposition`/`not_connected` metadata. |
| `review_priority` | Score 1-5 — does this claim need human review? | Claim pipeline after `claim_verification` | Routes kkron's attention: contradicted/low-confidence/high-stakes claims first. Pure annotation; never drops claims. |

Shared constraints (from CloudManagement PRD §6.5): start off or shadow-only;
existing rule/regex path stays the fallback; JEV failure must preserve current
behavior; nothing JEV decides is destructive without a human gate. Identity and
dedup decisions are the highest-value targets but also the most
calibration-sensitive — they stay annotation-only longest.

## Search engine inventory

| Engine | API key required | Plan | Cost | Strengths | Weaknesses |
|--------|-----------------|------|------|-----------|------------|
| **Brave Search** | `BRAVE_SEARCH_API_KEY` (or `BRAVE_ANSWERS_API_KEY` alias) | Data for Search | $5/1K queries; $5/month free credits (~1K queries) | Best `site:` queries for niche domains; indexes small sites well; structured JSON API | Requires paid plan; free tier limited to ~1K queries/month |
| **Bing** | None (HTML scraping) | N/A | Free | No key needed; lenient on automated requests; broad index | HTML scraping is fragile; doesn't index niche domains well (wikitia.com, doczz.net, Russian .ru domains); 3s delay between queries |
| **DuckDuckGo** | None (HTML scraping) | N/A | Free | No key needed; privacy-focused | **Currently broken** — HTTP 403 Forbidden on all queries (bot detection); unreliable for automated use |
| **Gemini Grounded** | `GEMINI_API_KEY` | Google AI Studio (free) or Vertex AI (paid) | Free tier: 1,500 RPD; Vertex AI: pay-per-use | Returns grounded URLs from Google Search; best for broad discovery | Not a traditional search engine — returns AI-curated results, not raw SERPs; limited result count |
| **Google KG** | `GOOGLE_API_KEY` | Google Knowledge Graph API | Free (1K/day) | Resolves entities to Wikipedia URLs; adds KG metadata | Only returns KG entities, not web pages; limited to well-known entities |

## When to use each engine

### Priority order (enrichment pipeline)

The enrichment script (`scripts/34_enrich_person.py`) tries engines in this order:

1. **Google KG** — resolve the person to a canonical entity + Wikipedia URL
2. **Gemini Grounded** — broad discovery with Google Search grounding
3. **Brave Search** — structured web search for biography/interview/seminar pages
4. **Bing** — fallback web search when Brave is unavailable
5. **DuckDuckGo** — last-resort fallback (currently broken)
6. **Magazine Archive** — specialized search for martial-arts magazine sources
7. **Reference Discovery** — follow outbound links from existing sources
8. **Arctic Shift** — Reddit archive search

### When to use Brave vs Bing

| Use case | Preferred engine | Reason |
|---------|-------------------|--------|
| `site:` queries on niche domains | Brave | Brave indexes smaller sites (wikitia.com, doczz.net, aikiclub.ru) better than Bing |
| Magazine archive discovery | Brave | Brave finds Google Books URLs and document archive pages that Bing misses |
| Broad biography search | Either | Both return similar results for well-known people |
| High-volume batch queries | Brave | Structured JSON API is faster and more reliable than HTML scraping |
| No API key available | Bing | Bing requires no key and is always available as a fallback |
| Russian/organizational domains | Brave | Bing doesn't index .ru martial arts domains well |

### When to use Gemini Grounded vs web search

| Use case | Preferred engine | Reason |
|---------|-------------------|--------|
| Initial person discovery | Gemini Grounded | Returns curated, relevant URLs with grounding metadata |
| Magazine article discovery | Brave/Bing | Web search finds specific magazine issues and archive pages |
| Verifying claims | Brave/Bing | Need raw SERPs to see all sources, not AI-curated results |
| Cost-sensitive runs | Gemini Grounded | Free tier (1,500 RPD) is more generous than Brave ($5/month) |

## API key requirements

### Required keys

| Key | Env var | Secret Manager | Purpose | Status |
|-----|---------|---------------|---------|--------|
| Gemini | `GEMINI_API_KEY` | `GEMINI_API_KEY` | LLM extraction + grounded search | ✅ Working |
| Google | `GOOGLE_API_KEY` | (via `GOOGLE_API_KEY`) | Knowledge Graph API | ✅ Working |
| Brave Search | `BRAVE_SEARCH_API_KEY` | `BRAVE_SEARCH_API_KEY` | Web search (Data for Search plan) | ❌ Current key is on Answers plan — needs Search plan |

### Optional keys

| Key | Env var | Purpose | Status |
|-----|---------|---------|--------|
| Movement Arts Google | `MOVEMENT_ARTS_GOOGLE_API_KEY` | Additional free-tier Gemini quota | Optional |
| Brave Answers (legacy) | `BRAVE_ANSWERS_API_KEY` | Legacy alias for Brave key | ⚠️ Answers plan, not Search plan |

### Key resolution order

The `config/settings.py` resolves keys with fallback aliases:

```python
# Brave: check BRAVE_SEARCH_API_KEY first, then BRAVE_ANSWERS_API_KEY
brave_search_api_key = os.getenv("BRAVE_SEARCH_API_KEY", "") \
    or os.getenv("BRAVE_ANSWERS_API_KEY", "")
```

## Known issues

### Brave key on wrong plan (issue #37)

The `BRAVE_ANSWERS_API_KEY` in Secret Manager is on the **Answers** plan
(AI-generated grounded answers), not the **Data for Search** plan (web search
results). The API returns 200 OK but with zero `web.results` because the
monthly quota for web search is 0.

**Fix:** Create a new key on the **Data for Search** plan at
https://api-dashboard.search.brave.com/ and store it as
`BRAVE_SEARCH_API_KEY` in Secret Manager.

### DuckDuckGo broken (issue #39)

DuckDuckGo HTML scraping returns HTTP 403 Forbidden on all queries,
followed by connection resets and timeouts. This is IP-based bot detection.

**Fix:** DuckDuckGo HTML scraping is inherently fragile. The client should
be treated as a best-effort fallback and not relied upon. Consider replacing
with the `bx` CLI tool or removing it entirely.

### Bing doesn't index niche domains (issue #39)

Bing's `site:` operator doesn't find pages on low-traffic, niche domains
like `wikitia.com`, `doczz.net`, `aikiclub.ru`, `lenkai.spb.ru`. This limits
the magazine archive discovery method's effectiveness when Brave is unavailable.

**Fix:** Once a working Brave Search key is obtained, Brave should be the
primary engine for magazine archive queries. Bing should only be used as a
fallback for broad biography searches.

## Recommendations

1. **Get a Brave Search key on the Data for Search plan** — this is the
   highest-impact fix. Brave is the only engine that reliably finds niche
   magazine/archive domains.

2. **Demote DuckDuckGo to last-resort** — it's currently broken and should
   not be tried before Bing. The enrichment pipeline already has it last
   in the order, but the magazine_archive method's fallback chain
   (brave → bing → ddg) should skip DDG when it's returning errors.
   **Implemented** — all search clients now have a `health_check()` method
   that makes a test query and caches the result. Engines that fail the
   health check are skipped before wasting queries.

3. **Add health checks to search clients** — each client should have a
   `health_check()` method that verifies the API key works and the endpoint
   is reachable, so the enrichment script can skip broken engines before
   wasting queries.
   **Implemented** — `BraveSearchClient.health_check()`,
   `BingSearchClient.health_check()`, and
   `DuckDuckGoSearchClient.health_check()` all make a single test query
   and cache the result. The enrichment script (`_run_search_method`,
   `_search_web_for_magazine_hits`, `_find_wiki_mirror_pages_via_search`,
   and `_verify_magazine_citation_via_search`) all check `health_check()`
   before using an engine.

4. **Add Google Books API direct search** — the Google Books API
   (`https://www.googleapis.com/books/v1/volumes?q=...`) doesn't require
   web search and can find magazine issues directly. This bypasses the
   Bing/Brave limitation for Google Books URLs. **Implemented** as Phase 1b
   in the `magazine_archive` method. Requires a standard Google API key
   (`AIza...` prefix) for reliable access — the Gemini AI Studio key
   (`AQ.Ab8...` prefix) does NOT work with the Books API (returns 401).
   Without a key, anonymous access is limited to ~100 requests/day (429
   after that). A proper Google API key should be added to Secret Manager
   as `GOOGLE_API_KEY` to enable full Google Books API access.

5. **Cache search results aggressively** — the SearchCache already caches
   results, but the magazine_archive method should also cache the wiki
   mirror citation tracing results so re-runs don't re-fetch the same pages.
