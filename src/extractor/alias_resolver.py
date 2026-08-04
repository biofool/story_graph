"""
Alias resolution: normalizes person names to canonical IDs using alias tables.
"""

from __future__ import annotations

import re
from typing import Optional

from src.utils.text_utils import normalize, slugify

# Canonical person: "James Edward Baker"
ALIAS_MAP: dict[str, str] = {
    "jim baker": "james edward baker",
    "james baker": "james edward baker",
    "father yod": "james edward baker",
    "ya ho wa": "james edward baker",
    "yahowha": "james edward baker",
    "ya ho wa 13": "james edward baker",
}

# Reverse map: canonical -> list of known aliases
CANONICAL_ALIASES: dict[str, list[str]] = {
    "james edward baker": ["Jim Baker", "Father Yod", "Ya Ho Wa", "Yahowha"],
}

# Known Source Family member names (partial — will grow via extraction)
KNOWN_PERSONS: dict[str, list[str]] = {
    "laura garon": ["Laura Garon"],
    "isis aquarian": ["Isis Aquarian"],
    "octavius": ["Octavius"],
    "djin aquarian": ["Djin Aquarian"],
    "rhythm aquarian": ["Rhythm Aquarian"],
    "hom aquarian": ["Hom Aquarian"],
    "electricity aquarian": ["Electricity Aquarian"],
}

# Set of all known person aliases (lowercased) for quick membership checks.
KNOWN_PERSON_ALIASES: set[str] = {
    alias.lower()
    for aliases in KNOWN_PERSONS.values()
    for alias in aliases
} | set(ALIAS_MAP.keys()) | set(ALIAS_MAP.values())

# Known groups
KNOWN_GROUPS: dict[str, list[str]] = {
    "the source family": ["The Source Family", "Source Family"],
    "the source restaurant": ["The Source Restaurant", "The Source"],
    "ya ho wa 13": ["Ya Ho Wa 13", "Yahowha 13"],
}

# Group alias map: any alias (normalized) -> canonical group name (normalized).
# Collapses surface variants like "The Source" / "The Source Restaurant" and
# "Source Family" / "The Source Family" into a single canonical node.
GROUP_ALIAS_MAP: dict[str, str] = {
    "the source family": "the source family",
    "source family": "the source family",
    "the source restaurant": "the source restaurant",
    "the source": "the source restaurant",
    "source restaurant": "the source restaurant",
    "ya ho wa 13": "ya ho wa 13",
    "yahowha 13": "ya ho wa 13",
    "yahowha": "ya ho wa 13",
}

# Known places
KNOWN_PLACES: dict[str, list[str]] = {
    "sunset strip": ["Sunset Strip"],
    "kauai": ["Kauai", "Kauai compound"],
    "nichols canyon": ["Nichols Canyon"],
    "fairmont hotel san francisco": ["Fairmont Hotel San Francisco"],
    "los angeles": ["Los Angeles", "LA"],
}

# Place alias map: any alias (normalized) -> canonical place name (normalized).
PLACE_ALIAS_MAP: dict[str, str] = {
    "los angeles": "los angeles",
    "la": "los angeles",
    "kauai": "kauai",
    "kauai compound": "kauai",
    "fairmont hotel san francisco": "fairmont hotel san francisco",
    "fairmont hotel": "fairmont hotel san francisco",
    "the fairmont hotel": "fairmont hotel san francisco",
    "sunset strip": "sunset strip",
    "nichols canyon": "nichols canyon",
    "san francisco": "san francisco",
}


def canonical_person(name: str) -> str:
    """Resolve a person name to its canonical form."""
    key = normalize(name)
    return ALIAS_MAP.get(key, key)


def canonical_group(name: str) -> str:
    """Resolve a group name to its canonical form (collapses 'The Source' /
    'The Source Restaurant' and 'Source Family' / 'The Source Family')."""
    key = normalize(name)
    return GROUP_ALIAS_MAP.get(key, key)


def canonical_place(name: str) -> str:
    """Resolve a place name to its canonical form (collapses 'LA' /
    'Los Angeles', 'Kauai compound' / 'Kauai', etc.)."""
    key = normalize(name)
    return PLACE_ALIAS_MAP.get(key, key)


def person_id(name: str) -> str:
    """Generate a stable person node ID from a name."""
    canonical = canonical_person(name)
    return f"person:{slugify(canonical)}"


def group_id(name: str) -> str:
    """Generate a stable group node ID from a name (canonicalized)."""
    return f"group:{slugify(canonical_group(name))}"


def place_id(name: str) -> str:
    """Generate a stable place node ID from a name (canonicalized)."""
    return f"place:{slugify(canonical_place(name))}"


def event_id(label: str) -> str:
    """Generate a stable event node ID from a label."""
    return f"event:{slugify(normalize(label))}"


def work_id(url: str) -> str:
    """Generate a stable work node ID from a URL."""
    from src.utils.text_utils import hash_url
    return f"work:{hash_url(url)}"


def claim_id(claim_text: str, source_url: str) -> str:
    """Generate a stable claim node ID from claim text + source URL."""
    from src.utils.text_utils import stable_hash
    return f"claim:{stable_hash(claim_text, source_url)}"


def get_aliases_for_canonical(canonical_name: str) -> list[str]:
    """Get known aliases for a canonical person name."""
    return CANONICAL_ALIASES.get(canonical_name, [])


def is_aquarian_name(name: str) -> bool:
    """Check if a name follows the Source Family 'X Aquarian' pattern."""
    return bool(re.search(r"\bAquarian\b", name, re.IGNORECASE))


def resolve_target_id(target: dict) -> str:
    """Resolve a target dict (with 'type' and 'name'/'label') to a node ID."""
    ttype = target.get("type", "").lower()
    name = target.get("name") or target.get("label") or ""
    if ttype == "person":
        return person_id(name)
    elif ttype == "group":
        return group_id(name)
    elif ttype == "place":
        return place_id(name)
    elif ttype == "event":
        return event_id(name)
    elif ttype == "work":
        url = target.get("url", "")
        return work_id(url)
    else:
        return f"unknown:{slugify(normalize(name))}"
