"""Gemini (Google Gen AI SDK) integration layer.

Provides three capabilities, all optional (gated on GEMINI_API_KEY):

- :mod:`src.llm.seed_discoverer` — discover new seed URLs via Google Search
  grounding.
- :mod:`src.llm.entity_claim_extractor` — structured entity/claim/relation
  extraction with the same output shape as
  :class:`src.extractor.entity_extractor.EntityExtractor`.
- :mod:`src.llm.graph_qa` — natural-language Q&A over the SQLite graph
  (retrieval-augmented).
"""
