# Component: Entity Extractor

**Path:** `src/extractor/entity_extractor.py` (565 LOC)
**Type:** Core domain logic — extraction engine

## Responsibility

Hybrid entity extraction combining spaCy NER with rule-based regex
patterns specific to the Source Family corpus. Extracts persons, groups,
places, events, claims, and typed relations from text. Includes false-
positive filtering for spaCy PERSON entities.

## Interface

```python
class EntityExtractor:
    def __init__(self, spacy_model_name: str = "en_core_web_sm")
    def extract(self, text: str) -> dict
        # Returns: {persons, groups, places, events, claims, relations}
```

The `extract()` return shape is the **contract** that `process_page()`
and `GeminiExtractor` both conform to. Changing this shape breaks both
the pipeline and the Gemini extractor's drop-in compatibility.

## Extraction Pipeline (OBSERVED)

1. **Persons:** Rule patterns (`PERSON_PATTERNS`) → known persons list
   (`KNOWN_PERSONS`) → spaCy NER (PERSON label) with `_is_valid_person_name`
   filter. Dedup by canonical name.
2. **Groups:** Rule patterns (`GROUP_PATTERNS`) → known groups → spaCy
   NER (ORG label). Dedup by canonical group.
3. **Places:** Rule patterns (`PLACE_PATTERNS`) → known places → spaCy
   NER (GPE/LOC/FAC labels). Dedup by canonical place.
4. **Events:** Sentence-level detection — sentences with both an
   `EVENT_TRIGGER` verb and a date (or just a trigger verb).
5. **Claims:** Sentences with `CLAIM_TRIGGER` verbs. Stance classified
   by keyword matching. Claim type and evidence mode similarly.
   Speaker extracted via regex patterns. Targets identified by
   checking which already-extracted entities appear in the sentence.
6. **Relations:** Per-sentence scan for relational trigger phrases.
   Types: FOUNDED, MEMBER_OF, WORKED_AT, LIVED_AT, LOCATED_IN.
   (CREATED skipped — works not available at per-sentence level.)

## Dependencies

| Dependency | Type | Evidence |
|---|---|---|
| `src.extractor.alias_resolver` | code | canonical_person/group/place, KNOWN_* tables, is_aquarian_name |
| `src.utils.text_utils` | code | normalize, split_sentences, extract_date_from_text |
| `spacy` | external (optional) | lazy import in `_try_load_spacy` — falls back to rules only |

## Consumers

| Consumer | How |
|---|---|
| `src.extractor.claim_extractor.ClaimExtractor` | Wraps `_extract_claims()` with ID enrichment |
| `scripts/_pipeline_helpers.process_page()` | Calls `extract()`, iterates results for storage |
| `scripts/01_crawl_and_build_graph.py` | Instantiates `EntityExtractor`, passes to `ClaimExtractor` and `process_page` |
| `tests/unit/test_entity_extractor.py` | Direct extraction tests (rule-based only, spaCy model set to "nonexistent") |

## Key Design Decisions (OBSERVED)

- **spaCy is optional:** If model load fails, falls back to rule-based
  extraction only. This is tested explicitly (all unit tests use
  `spacy_model_name="nonexistent_model"`).
- **Text truncation:** spaCy processes `text[:100000]` for performance.
- **False-positive filter:** `_is_valid_person_name()` rejects common
  single-token NER false positives (adverbs, days, months, ambiguous
  tokens like "Robin"). Single-token names only accepted if known or
  Aquarian-pattern.
- **Surface-form reuse:** Claim target identification reuses already-
  extracted entities' surface forms rather than running NER per sentence.

## Change Guidance

- **Adding entity types:** Must update `extract()` return shape, which
  breaks `process_page()` and `GeminiExtractor` compatibility. Consider
  backward-compatible additions.
- **Changing keyword lists** (stance, claim_type, evidence_mode): Low
  risk to code, but changes extraction output. Update tests in
  `test_entity_extractor.py` accordingly.
- **Adding relation types:** Update `_REL_TYPE_MAP` in
  `_pipeline_helpers.py` and `EXTRACTION_SCHEMA` in
  `entity_claim_extractor.py` for Gemini parity.
- **spaCy model upgrade:** Test with real corpus — NER behavior may
  change, affecting false-positive filter adequacy.
