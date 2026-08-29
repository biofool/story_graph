"""
Scope filtering: detect pages that are primarily about out-of-scope entities
(namesakes of story-relevant persons/events) and prevent the pipeline from
extracting from them or following their links.

Out-of-scope entities are listed in ``config/out_of_scope.json``. Each entry
has a canonical name (matching the disambiguated form from
:data:`~src.extractor.alias_resolver.HOMONYM_DISAMBIGUATION`) and a list of
surface forms (how the name appears in page text/titles).

A page is considered "primarily about" an out-of-scope entity when:
  1. The entity's surface form appears in the page title, OR
  2. The entity's surface form appears 3+ times in the first 2000 chars of
     text AND no in-scope entity (from the story's known persons/groups) is
     mentioned in the same window.

This is conservative: a page that mentions both an out-of-scope namesake and
an in-scope entity is NOT filtered out, since it may be drawing a contrast
or providing context relevant to the story.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.extractor.alias_resolver import (
    KNOWN_GROUPS,
    KNOWN_PERSONS,
    event_id,
    person_id,
)
from src.utils.text_utils import normalize

_log = logging.getLogger(__name__)

# Default path to the out-of-scope config, relative to project root.
DEFAULT_CONFIG_PATH = "config/out_of_scope.json"

# How many mentions of the out-of-scope entity in the text window before we
# consider the page "primarily about" it (when the title doesn't match).
_MENTION_THRESHOLD = 3

# How much of the page text to scan for entity mentions.
_TEXT_WINDOW = 2000


@dataclass(frozen=True)
class OutOfScopeEntity:
    """One out-of-scope person or event."""
    canonical_name: str
    entity_type: str  # "person" | "event"
    surface_forms: list[str]
    note: str = ""
    # Pre-computed: normalized surface forms for fast matching.
    normalized_forms: frozenset[str] = field(default_factory=frozenset)

    @property
    def node_id(self) -> str:
        """The graph node ID for this entity (person or event)."""
        if self.entity_type == "event":
            return event_id(self.canonical_name)
        return person_id(self.canonical_name)


@dataclass
class ScopeFilter:
    """Loads out-of-scope config and tests whether pages are in or out of scope.

    Call :meth:`is_page_out_of_scope` per crawled page. Returns ``True`` when
    the page should be skipped (not extracted, links not followed).
    """
    entities: list[OutOfScopeEntity]
    # Normalized surface forms of all in-scope known persons/groups, used to
    # detect whether a page also mentions a story-relevant entity (in which
    # case it is NOT filtered, even if an out-of-scope entity is mentioned).
    _in_scope_forms: frozenset[str]

    @classmethod
    def from_config(cls, config_path: str | Path | None = None) -> ScopeFilter:
        """Load the out-of-scope config from JSON.

        If the config file doesn't exist or is empty, returns an empty filter
        that passes everything through (no behavior change).
        """
        path = Path(config_path) if config_path else _default_config_path()
        entities: list[OutOfScopeEntity] = []

        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                _log.warning("Failed to load out-of-scope config %s: %s", path, e)
                data = {}
        else:
            _log.debug("Out-of-scope config not found at %s; filter is empty", path)
            data = {}

        for entry in data.get("persons", []):
            canonical = entry.get("canonical_name", "")
            if not canonical:
                continue
            forms = entry.get("surface_forms", [])
            entities.append(OutOfScopeEntity(
                canonical_name=canonical,
                entity_type="person",
                surface_forms=forms,
                note=entry.get("note", ""),
                normalized_forms=frozenset(normalize(f) for f in forms if f),
            ))

        for entry in data.get("events", []):
            canonical = entry.get("canonical_name", "")
            if not canonical:
                continue
            forms = entry.get("surface_forms", [])
            entities.append(OutOfScopeEntity(
                canonical_name=canonical,
                entity_type="event",
                surface_forms=forms,
                note=entry.get("note", ""),
                normalized_forms=frozenset(normalize(f) for f in forms if f),
            ))

        # Build in-scope surface forms from the alias resolver's known
        # persons and groups. These are the story-relevant entities — if a
        # page mentions one of them, it's in scope even if it also mentions
        # an out-of-scope namesake.
        in_scope_forms: set[str] = set()
        for aliases in KNOWN_PERSONS.values():
            for alias in aliases:
                in_scope_forms.add(normalize(alias))
        for aliases in KNOWN_GROUPS.values():
            for alias in aliases:
                in_scope_forms.add(normalize(alias))

        return cls(
            entities=entities,
            _in_scope_forms=frozenset(in_scope_forms),
        )

    @property
    def is_empty(self) -> bool:
        """True if no out-of-scope entities are configured (filter is a no-op)."""
        return len(self.entities) == 0

    def out_of_scope_node_ids(self) -> set[str]:
        """Return the set of graph node IDs for all out-of-scope entities."""
        return {e.node_id for e in self.entities}

    def is_page_out_of_scope(self, title: str, text: str, url: str | None = None) -> bool:
        """Check whether a page is primarily about an out-of-scope entity.

        Returns ``True`` if the page should be skipped (not extracted, links
        not followed). Returns ``False`` if the page is in scope or if no
        out-of-scope entities are configured.
        """
        if self.is_empty:
            return False

        title_norm = normalize(title) if title else ""
        text_window = text[:_TEXT_WINDOW] if text else ""
        text_norm = normalize(text_window)

        for entity in self.entities:
            if not entity.normalized_forms:
                continue

            # Check if any surface form appears in the title — strong signal.
            title_match = any(
                form in title_norm for form in entity.normalized_forms
            )

            # Count mentions in the text window. We count the total
            # occurrences of all surface forms, not just distinct forms —
            # "Richard Moon" appearing 3 times is a strong signal even if
            # only one surface form is used.
            mention_count = sum(
                text_norm.count(form) for form in entity.normalized_forms
            )

            if not title_match and mention_count < _MENTION_THRESHOLD:
                continue

            # The page prominently features this out-of-scope entity. But
            # if it ALSO mentions an in-scope entity, keep it — it may be
            # providing relevant context or contrast.
            if self._mentions_in_scope_entity(text_norm):
                _log.debug(
                    "Page %s mentions out-of-scope '%s' but also in-scope "
                    "entities; keeping",
                    url or "(no url)",
                    entity.canonical_name,
                )
                continue

            _log.info(
                "Page %s filtered as out-of-scope (primarily about '%s')",
                url or "(no url)",
                entity.canonical_name,
            )
            return True

        return False

    def _mentions_in_scope_entity(self, text_norm: str) -> bool:
        """Check whether normalized text mentions any in-scope entity."""
        return any(form in text_norm for form in self._in_scope_forms)


def _default_config_path() -> Path:
    """Return the default config path relative to the project root."""
    # config/settings.py defines PROJECT_ROOT as the parent of config/
    from config.settings import PROJECT_ROOT
    return PROJECT_ROOT / DEFAULT_CONFIG_PATH
