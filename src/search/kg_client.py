"""Google Knowledge Graph Search API client.

Resolves entity names to canonical URLs, Wikipedia links, types, and
descriptions via kgsearch.googleapis.com. Free tier: 100K requests/day.

Ported and adapted from WorldStudioFinder's
src/discovery/knowledge_graph_client.py.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)

_KG_ENDPOINT = "https://kgsearch.googleapis.com/v1/entities:search"


@dataclass
class KGEntity:
    """A Knowledge Graph entity result."""

    kg_id: str = ""
    name: str = ""
    types: list[str] = field(default_factory=list)
    description: str = ""
    url: str = ""
    wikipedia_url: str = ""
    article_body: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class KnowledgeGraphClient:
    """Queries the Google Knowledge Graph Search API for entity resolution."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GOOGLE_KNOWLEDGE_GRAPH_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not self.api_key:
            _log.warning("No GOOGLE_API_KEY set; Knowledge Graph client disabled")
        self._cache: dict[str, list[KGEntity]] = {}

    def is_available(self) -> bool:
        return bool(self.api_key)

    def search(
        self,
        query: str,
        limit: int = 5,
        types: str | None = None,
    ) -> list[KGEntity]:
        """Search the Knowledge Graph for entities matching the query.

        Args:
            query: Entity name to search for.
            limit: Max results (1-100).
            types: Optional type filter (e.g. "Person", "Organization").

        Returns:
            List of KGEntity objects, highest relevance first.
        """
        if not self.is_available():
            _log.warning("Knowledge Graph unavailable (no API key)")
            return []

        cache_key = f"{query.lower()}|{limit}|{types or ''}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {"query": query, "key": self.api_key, "limit": str(limit)}
        if types:
            params["types"] = types

        url = f"{_KG_ENDPOINT}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:200]
            _log.error("Knowledge Graph HTTP %d for '%s': %s", e.code, query, body)
            return []
        except Exception as e:
            _log.error("Knowledge Graph search failed for '%s': %s", query, e)
            return []

        entities: list[KGEntity] = []
        for item in data.get("itemListElement", []):
            result = item.get("result", {})
            if not result.get("name"):
                continue

            detailed = result.get("detailedDescription", {})
            raw_types = result.get("@type", [])
            if isinstance(raw_types, str):
                raw_types = [raw_types]

            entity = KGEntity(
                kg_id=result.get("@id", ""),
                name=result.get("name", ""),
                types=raw_types,
                description=result.get("description", ""),
                url=result.get("url", ""),
                wikipedia_url=detailed.get("url", ""),
                article_body=detailed.get("articleBody", ""),
                raw=result,
            )
            entities.append(entity)

        self._cache[cache_key] = entities
        _log.info("KG search '%s' → %d entities", query, len(entities))
        return entities

    def resolve_person(self, name: str, context: str = "") -> KGEntity | None:
        """Resolve a person name to the best-matching KG entity.

        Args:
            name: Person name (e.g. "Dan Millman").
            context: Optional context string (e.g. "aikido") to improve
                     disambiguation.

        Returns:
            Best-matching KGEntity or None if no Person-type result found.
        """
        query = f"{name} {context}".strip()
        entities = self.search(query, limit=5, types="Person")
        if entities:
            return entities[0]

        # Fall back to untyped search
        entities = self.search(query, limit=5)
        for e in entities:
            if "Person" in e.types:
                return e
        return entities[0] if entities else None
