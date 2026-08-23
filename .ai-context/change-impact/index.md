# Change Impact Index

See [relationships.yaml](relationships.yaml) for the full dependency/dependents map.

## High-Impact Components (change these → many downstream effects)

1. **`src/storage/models.py`** — enum changes ripple to all extractors,
   storage, pipeline helpers, contradiction detector, tests.
2. **`src/storage/graph_db.py`** — schema changes affect all DB consumers.
3. **`scripts/_pipeline_helpers.py`** — `process_page()` is the sole
   extraction→storage bridge.
4. **`src/extractor/alias_resolver.py`** — ID generation functions used
   everywhere; changing ID format invalidates existing graphs.
5. **`src/extractor/entity_extractor.py`** — `extract()` return shape
   is the contract for both rule-based and Gemini extractors.
