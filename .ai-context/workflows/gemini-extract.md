# Workflow: Gemini Extract / Discover / Ask

**Entry Point:** `python scripts/02_gemini_search.py {discover|extract|ask}`
**CLI Framework:** Click (`@click.group()` with 3 subcommands)
**Requires:** `GEMINI_API_KEY` in `.env`

## Subcommand: discover

### Execution Path
1. `GeminiClient()` — lazy construction, checks `is_available()`
2. If unavailable: print error, return
3. `SeedDiscoverer(client).discover(query, exclude_urls=existing_seeds)`
4. `discoverer.discover()`:
   - Build prompt from query (or default Source Family topic)
   - `client.generate_grounded(prompt)` → `GroundingResult`
   - Filter: skip non-http URIs, excluded URLs, duplicates
   - Return `list[DiscoveredSeed]`
5. Output: Rich Table (URL, Title, Domain) or JSON if `--json-out`

### Evidence
| Step | Path | Symbol |
|---|---|---|
| Entry | `scripts/02_gemini_search.py` | `discover()` |
| Logic | `src/llm/seed_discoverer.py` | `SeedDiscoverer.discover()` |
| API | `src/llm/gemini_client.py` | `GeminiClient.generate_grounded()` |

## Subcommand: extract

### Execution Path
1. `GeminiClient()` — check availability
2. If `--url`: create single-page `WebCrawler`, `crawl()`, get page
   If `--text`: create synthetic `CrawledPage` with `url="gemini://inline-text"`
3. `GeminiExtractor(client)` — drop-in for `EntityExtractor`
4. `GeminiClaimExtractor(gemini_ext)` — wraps extractor, reuses cache
5. If `--store` (default): `GraphDB(db_file)`, `process_page(page, gemini_ext, gemini_claim_ext, db)`, close DB
6. If `--no-store`: `gemini_ext.extract(page.text)`, print JSON

### Key Detail
`GeminiExtractor.extract()` sends text to Gemini with `EXTRACTION_SCHEMA`
(JSON Schema constraining output to persons/groups/places/events/claims/
relations). Response is normalized via `_normalize()` to match
`EntityExtractor`'s dict shape. Results cached by text hash —
`GeminiClaimExtractor` reuses the cache to avoid a second API call.

### Evidence
| Step | Path | Symbol |
|---|---|---|
| Entry | `scripts/02_gemini_search.py` | `extract()` |
| Extract | `src/llm/entity_claim_extractor.py` | `GeminiExtractor.extract()` |
| Claims | `src/llm/entity_claim_extractor.py` | `GeminiClaimExtractor.extract_claims()` |
| Store | `scripts/_pipeline_helpers.py` | `process_page()` |
| API | `src/llm/gemini_client.py` | `GeminiClient.generate_json()` |

## Subcommand: ask

### Execution Path
1. `GeminiClient()` — check availability
2. `GraphDB(db_file)` — open existing graph
3. `GraphQA(db, client).answer(question)`
4. `qa.answer()`:
   a. `_retrieve(question)` — keyword-match question against node
      labels/canonical names + claim text. Collects matched nodes,
      claims (including those ABOUT matched nodes), and sources.
   b. If Gemini unavailable: return message + context
   c. Build prompt: question + retrieved context JSON
   d. `client.generate_text(prompt, system_instruction=...)` — system
      instruction enforces "answer using ONLY the provided context"
   e. Return `QAResponse(answer=text, context=context)`
5. Print answer; if `--show-context`, print retrieved context JSON
6. `db.close()` (in `finally` block)

### Evidence
| Step | Path | Symbol |
|---|---|---|
| Entry | `scripts/02_gemini_search.py` | `ask()` |
| Retrieval | `src/llm/graph_qa.py` | `GraphQA._retrieve()` |
| Synthesis | `src/llm/graph_qa.py` | `GraphQA.answer()` |
| API | `src/llm/gemini_client.py` | `GeminiClient.generate_text()` |

## Failure Paths

| Failure | Behavior |
|---|---|
| No `GEMINI_API_KEY` | `_require_gemini()` prints error, returns False, command exits |
| Gemini API error | `GeminiError` raised, caught in extractor/QA, logged, returns empty/error result |
| URL fetch fails (extract) | "Failed to fetch URL" printed, command returns |
| DB error | `db.close()` in `finally` block ensures cleanup |

## Change Guidance

- Adding subcommands: Follow the Click `@cli.command()` pattern. Use
  `_require_gemini()` guard. Add fake client tests in
  `tests/unit/test_gemini_extractors.py`.
- Changing retrieval logic: Modify `GraphQA._retrieve()`. Currently
  keyword-based — could be enhanced with embedding similarity.
- Changing extraction schema: Update `EXTRACTION_SCHEMA` in
  `entity_claim_extractor.py` and `_normalize()` to match.
