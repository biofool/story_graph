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
    "electronically hughes": ["Electronically Hughes"],
}

# Known groups
KNOWN_GROUPS: dict[str, list[str]] = {
    "the source family": ["The Source Family", "Source Family"],
    "the source restaurant": ["The Source Restaurant", "The Source"],
    "ya ho wa 13": ["Ya Ho Wa 13", "Yahowha 13"],
}

# Known places
KNOWN_PLACES: dict[str, list[str]] = {
    "sunset strip": ["Sunset Strip"],
    "kauai": ["Kauai", "Kauai compound"],
    "nichols canyon": ["Nichols Canyon"],
    "fairmont hotel san francisco": ["Fairmont Hotel San Francisco"],
    "los angeles": ["Los Angeles", "LA"],
}


def canonical_person(name: str) -> str:
    """Resolve a person name to its canonical form."""
    key = normalize(name)
    return ALIAS_MAP.get(key, key)


def person_id(name: str) -> str:
    """Generate a stable person node ID from a name."""
    canonical = canonical_person(name)
    return f"person:{slugify(canonical)}"


def group_id(name: str) -> str:
    """Generate a stable group node ID from a name."""
    return f"group:{slugify(normalize(name))}"


def place_id(name: str) -> str:
    """Generate a stable place node ID from a name."""
    return f"place:{slugify(normalize(name))}"


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
