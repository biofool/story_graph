# Error Handling & Logging Conventions

All patterns **OBSERVED** from source code.

## Logging

### Strongly recurring (every module):
```python
import logging
_log = logging.getLogger(__name__)
```
- Uses stdlib `logging` module throughout
- `structlog` is in `requirements.txt` but **not used anywhere** (UNKNOWN-003)
- Log levels used: `_log.info()`, `_log.warning()`, `_log.error()`, `_log.debug()`
- f-string interpolation in log messages (not lazy `%s` formatting)

### Log message patterns:
- Info: progress messages ("Crawling:", "Crawl complete:", "Found N contradictions")
- Warning: degradation notices ("spaCy model not available", "Gemini unavailable")
- Error: API failures ("Gemini extraction failed:", "Graph Q&A failed:")
- Debug: filtered entities ("Filtered spaCy PERSON false positive")

## Error Handling

### Pattern 1: Graceful degradation (strongly recurring)
- spaCy load failure → fall back to rule-based extraction, log warning
- Gemini unavailable → return empty results or error message, log warning
- No exceptions raised to caller for optional feature failures

### Pattern 2: Custom exceptions
- `GeminiError(RuntimeError)` — raised for Gemini API failures
  - Raised in `generate_content()` when SDK call fails
  - Raised when no API key configured
  - Raised when response has no text content
  - Raised when JSON parsing fails

### Pattern 3: Try/except with logging, return safe default
```python
try:
    data = self._client.generate_json(...)
except GeminiError as e:
    _log.error("Gemini extraction failed: %s", e)
    data = _empty_result()
```
Used in: `GeminiExtractor.extract()`, `GraphQA.answer()`, `SeedDiscoverer.discover()`

### Pattern 4: Explicit guard with clear error
- `GraphDB._get_conn()` raises `RuntimeError("GraphDB is closed")` instead
  of `AttributeError` from None. Added in fix/priority-items merge.
- Tested explicitly in `TestUseAfterClose` class.

### Pattern 5: Catch-all in crawler
- `WebCrawler.crawl()` catches `Exception` broadly for fetch failures,
  appends error page, continues. Does not re-raise.

### Pattern 6: No error handling (weak pattern, 2 instances)
- `WebCrawler._parse_page()` — no try/except; BeautifulSoup/lxml could
  raise on malformed HTML (DEBT-001)
- `process_page()` — no try/except; extraction or storage errors
  propagate to caller

## Retry Logic

### OBSERVED:
- `WebCrawler._fetch()`: `@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))`
- No retry on non-200 responses (only on exceptions)
- No retry in Gemini client (single attempt, raises GeminiError on failure)
- No retry in SQLite operations

## Input Validation

### Strongly recurring:
- Pydantic models validate types at construction
- `EntityExtractor.extract()` — no explicit validation (assumes string input)
- `GeminiExtractor.extract()` — checks for empty/whitespace text, returns empty result
- `GraphQA._retrieve()` — filters terms shorter than 3 chars
- `_is_valid_person_name()` — multi-layer heuristic filter for NER false positives
- `_normalize()` in entity_claim_extractor — validates dict structure, skips invalid entries
