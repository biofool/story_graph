# Component: LLM Layer

**Path:** `src/llm/` (4 files, ~643 LOC total)
**Type:** Optional enhancement — Gemini-powered features

## Responsibility

Provides LLM-backed alternatives to the rule-based pipeline:
- **GeminiClient** (`gemini_client.py`, 219 LOC): Thin wrapper over
  `google-genai` SDK. Lazy construction — SDK only imported on first use.
  Three call shapes: `generate_text`, `generate_json` (structured output),
  `generate_grounded` (Google Search grounding).
- **GeminiExtractor** (`entity_claim_extractor.py`, 365 LOC): Drop-in
  replacement for `EntityExtractor`. Sends text to Gemini with a JSON
  Schema constraining output to the same 6-key shape. Caches by text hash.
- **GeminiClaimExtractor**: Wraps GeminiExtractor, mirrors
  `ClaimExtractor` interface. Reuses cached extraction to avoid second
  API call.
- **GraphQA** (`graph_qa.py`, 163 LOC): Keyword retrieval from SQLite
  graph + Gemini synthesis. System instruction enforces "answer using
  ONLY the provided context."
- **SeedDiscoverer** (`seed_discoverer.py`, 96 LOC): Uses Gemini's
  Google Search grounding to find new seed URLs about the Source Family.

## Interface

```python
class GeminiClient:
    def is_available(self) -> bool  # True if API key set + SDK imports
    def generate_text(self, prompt, *, system_instruction=None) -> str
    def generate_json(self, prompt, response_schema, *, system_instruction=None) -> Any
    def generate_grounded(self, prompt) -> GroundingResult

class GeminiExtractor:
    def is_available(self) -> bool
    def extract(self, text: str) -> dict  # same shape as EntityExtractor

class GeminiClaimExtractor:
    def extract_claims(self, text: str, source_url: str = "") -> list[dict]

class GraphQA:
    def answer(self, question: str, *, max_nodes=25, max_claims=15) -> QAResponse

class SeedDiscoverer:
    def discover(self, query=None, *, exclude_urls=None) -> list[DiscoveredSeed]
```

## Dependencies

| Dependency | Type | Evidence |
|---|---|---|
| `google-genai` SDK | external (optional) | lazy import in `_ensure_client()` |
| `config.settings` | code | `settings.gemini_api_key`, `settings.gemini_model` |
| `src.extractor.alias_resolver` | code | canonical_* functions for normalization |
| `src.storage.graph_db` | code | GraphQA reads from DB |
| `src.storage.models` | code | NodeType, RelationType for retrieval |
| `src.utils.text_utils` | code | `stable_hash`, `get_domain` |

## Consumers

| Consumer | How |
|---|---|
| `scripts/02_gemini_search.py` | `discover`, `extract`, `ask` subcommands |
| `scripts/_pipeline_helpers.process_page()` | Accepts GeminiExtractor/GeminiClaimExtractor (duck-typed) |

## Graceful Degradation (OBSERVED)

- `GeminiClient.is_available()` returns False if no API key or SDK
  import fails. All LLM modules check this before making calls.
- `GeminiExtractor.extract()` returns empty result if unavailable.
- `GraphQA.answer()` returns a message saying Gemini is not configured,
  with retrieved context still attached.
- `SeedDiscoverer.discover()` returns empty list if unavailable.
- The default pipeline (`01_crawl_and_build_graph.py`) never uses Gemini.

## Testing (OBSERVED)

All LLM tests use fake clients (`FakeGeminiClient`, `_FakeGeminiClient`)
that override `generate_text`/`generate_json`/`generate_grounded` to
return canned data. No test hits the real Gemini API.

## Change Guidance

- **Gemini SDK version changes:** `gemini_client.py` uses
  `response_json_schema` (not `response_schema`) in `GenerateContentConfig`
  — this is a newer SDK API. SDK upgrades may change response shapes;
  `_response_text()` has fallback parsing but may need updates.
- **Schema changes in `EXTRACTION_SCHEMA`:** Must stay compatible with
  `process_page()`'s expectations. The `_normalize()` function reshapes
  Gemini output to match `EntityExtractor`'s dict shape.
- **Adding new LLM features:** Follow the pattern — thin method on
  `GeminiClient`, higher-level logic in a dedicated module, fake client
  in tests.
