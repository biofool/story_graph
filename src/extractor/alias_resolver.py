"""
Alias resolution: normalizes person names to canonical IDs using alias tables.
"""

from __future__ import annotations

import re

from src.utils.text_utils import get_domain, normalize, slugify

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
    # Not a Source Family member, but registered so the name resolves
    # cleanly during extraction — appears in the March 1971 meeting lead
    # (see scripts/03_targeted_entity_research.py).
    "yogi bhajan": ["Yogi Bhajan"],
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
    # Jim Baker's earlier, pre-Source restaurant (see
    # scripts/03_targeted_entity_research.py).
    "aware inn": ["Aware Inn", "The Aware Inn"],
    "wild mountain cafe": ["Wild Mountain Cafe", "Wild Mountain Café"],
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
    "aware inn": "aware inn",
    "the aware inn": "aware inn",
    "wild mountain cafe": "wild mountain cafe",
    "wild mountain café": "wild mountain cafe",
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


# ---------------------------------------------------------------------------
# Homonym disambiguation: same surface name, different real people.
#
# A plain name is not an identity. "Richard Moon" resolves to at least three
# unrelated people who all turn up in this project's crawl: the Aikido
# teacher and Quantum Aikido author kkron's leads are about, a Canadian
# constitutional-law professor, and an Australian chef. Before this table
# existed, all three collapsed onto one ``person:richard-moon`` node, so the
# graph asserted a single merged biography — a law professor who also cooked
# in the Blue Mountains and worked at Father Yod's Source restaurant.
#
# Disambiguation is by *publishing domain*, because that is the only signal
# available at extraction time: a bio on uwindsor.ca is about the law
# professor, one on burgewords.com is about the chef. Names listed here have
# NO unqualified canonical form — ``DEFAULT`` names the person a mention
# resolves to when the domain is unknown or unlisted, and every canonical
# form carries its disambiguator, so the graph never claims a bare
# "Richard Moon" that silently merges three men.
#
# Add an entry when (and only when) two distinct people genuinely share a
# surface name in the crawl. See docs/ for the research notes behind the
# current entries.
# ---------------------------------------------------------------------------
HOMONYM_DEFAULT = "DEFAULT"

HOMONYM_DISAMBIGUATION: dict[str, dict[str, str]] = {
    "richard moon": {
        # kkron's leads, the Quantum Aikido author, IMTD Cyprus/Bosnia work.
        HOMONYM_DEFAULT: "richard moon (aikido)",
        "quantumaikido.com": "richard moon (aikido)",
        "nautilus.org": "richard moon (aikido)",
        "openmindadventures.com": "richard moon (aikido)",
        "createabeautifulworld.org": "richard moon (aikido)",
        "innertraditions.com": "richard moon (aikido)",
        "simonandschuster.com": "richard moon (aikido)",
        # Canadian constitutional-law professor (Univ. of Windsor).
        "uwindsor.ca": "richard moon (law professor)",
        "uottawa.ca": "richard moon (law professor)",
        "ucl.ac.uk": "richard moon (law professor)",
        "cfe.torontomu.ca": "richard moon (law professor)",
        # Australian chef, subject of Michael Burge's "Moon on a Spoon".
        "burgewords.com": "richard moon (chef)",
    },
    "doug stone": {
        # Harvard Negotiation Project / Triad Consulting, co-author of
        # "Difficult Conversations"; the Cyprus-relevant Doug Stone.
        HOMONYM_DEFAULT: "douglas stone (negotiation)",
    },
    "douglas stone": {
        HOMONYM_DEFAULT: "douglas stone (negotiation)",
    },
}


def _disambiguate_person(key: str, source_url: str | None) -> str | None:
    """Resolve a homonymous person name using the publishing domain.

    Returns the disambiguated canonical name, or None if ``key`` is not a
    known homonym. An unknown/unlisted domain falls back to the entry's
    ``HOMONYM_DEFAULT``, which is still a disambiguated name — never a bare
    surface name.
    """
    variants = HOMONYM_DISAMBIGUATION.get(key)
    if variants is None:
        return None
    if source_url:
        domain = get_domain(source_url)
        for listed_domain, canonical in variants.items():
            if listed_domain == HOMONYM_DEFAULT:
                continue
            if domain == listed_domain or domain.endswith("." + listed_domain):
                return canonical
    return variants[HOMONYM_DEFAULT]


def canonical_person(name: str, source_url: str | None = None) -> str:
    """Resolve a person name to its canonical form.

    ``source_url`` is the page the mention came from. It only matters for
    names in :data:`HOMONYM_DISAMBIGUATION` — names shared by two or more
    unrelated real people — where the publishing domain is what tells them
    apart. Omitting it for such a name yields that entry's default person
    rather than a bare, merged surface name.
    """
    key = normalize(name)
    disambiguated = _disambiguate_person(key, source_url)
    if disambiguated is not None:
        return disambiguated
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


def person_id(name: str, source_url: str | None = None) -> str:
    """Generate a stable person node ID from a name.

    Pass ``source_url`` wherever the originating page is known so
    homonymous names resolve to the right person — see
    :func:`canonical_person` and :data:`HOMONYM_DISAMBIGUATION`.
    """
    canonical = canonical_person(name, source_url)
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


def resolve_target_id(target: dict, source_url: str | None = None) -> str:
    """Resolve a target dict (with 'type' and 'name'/'label') to a node ID.

    ``source_url`` is forwarded to :func:`person_id` so a homonymous person
    target resolves to the right person — see :data:`HOMONYM_DISAMBIGUATION`.
    """
    ttype = target.get("type", "").lower()
    name = target.get("name") or target.get("label") or ""
    if ttype == "person":
        return person_id(name, source_url)
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
