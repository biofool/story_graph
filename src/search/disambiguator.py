"""
Person and dojo name disambiguation for the lineage graph.

Provides:
- normalize_person_name: strip titles, normalize whitespace
- normalize_domain: extract canonical domain from URL
- build_alias_index: {alias_lower: [person_node_ids]} from lineage_persons
- map_head_to_person: resolution chain (exact → alias → fuzzy → candidate)
- is_likely_aikidoka: contextual signal detection
- disambiguate_person: filter candidates by context
- slugify: URL-safe slug from text
- clean_dojo_name: normalize dojo names
- deduplicate_dojos: dedup by domain+city
"""

from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlparse

from src.storage.lineage_db import LineageDB

_log = logging.getLogger(__name__)

# Contextual signals for aikido disambiguation
AIKIDO_CONTEXT_SIGNALS = [
    "aikido", "sensei", "shihan", "hanshi", "dojo", "dan", "aikikai",
    "ueshiba", "hombu", "seminar", "training", "uke", "iaido",
    "jo", "bokken", "tatami", "keikogi", "hakama", "nadeau",
    "millman", "moon", "kufferath", "strozzi", "leonard", "ralston",
    "cheng hsin", "caa", "california aikido",
]

AIKIDO_DOMAIN_SIGNALS = [
    "aikido", "aikikai", "dojo", "caa", "chenghsin",
    "cityaikido", "aikido-health", "usadojo", "budovideos",
]

COMMON_TITLES = r'^(Sensei|Shihan|Hanshi|Professor|Prof\.|Dr\.|Mr\.|Ms\.|Mrs\.)\s+'

# Words that should never be used as fuzzy match keys (last names)
# These are common martial arts terms, not person name components
FUZZY_STOPWORDS = {
    "aikido", "dojo", "sensei", "shihan", "hanshi", "professor", "prof",
    "dr", "mr", "ms", "mrs", "aikikai", "ki", "society", "club",
    "international", "inc", "llc", "the", "and", "of", "for", "school",
    "center", "centre", "institute", "academy", "foundation", "association",
    "federation", "organization", "organisation", "university", "college",
    "memorial", "community", "martial", "arts", "art", "way", "budo",
    "bujutsu", "kai", "kan", "ryu", "jutsu", "do", "juku", "shudokan",
    "aikidoka", "teacher", "instructor", "master", "student", "black",
    "belt", "dan", "kyu", "class", "training", "practice", "what",
}


def normalize_person_name(name: str) -> str:
    """Normalize a person name for matching.

    - Strips common martial arts titles
    - Normalizes whitespace
    - Preserves case (for display) but matching is case-insensitive
    """
    if not name:
        return ""
    name = name.strip()
    name = re.sub(COMMON_TITLES, '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name)
    return name


def normalize_domain(website: str) -> str:
    """Extract and normalize the domain from a URL."""
    if not website:
        return ""
    url = website.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().removeprefix("www.")
        return domain
    except Exception:
        return ""


def slugify(text: str) -> str:
    """Create a URL-safe slug from text."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return text


def clean_dojo_name(name: str) -> str:
    """Normalize dojo name: trim, remove redundant suffixes."""
    if not name:
        return ""
    name = name.strip()
    name = re.sub(r'\s+Aikido$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s+', ' ', name)
    return name


def build_alias_index(db: LineageDB) -> dict[str, list[str]]:
    """Build a {alias_lower: [person_node_ids]} index from all Person nodes.

    Includes both canonical_name and all entries in aliases_json.
    """
    persons = db.query_all("SELECT node_id, canonical_name, aliases_json FROM lineage_persons")
    index: dict[str, list[str]] = {}
    for p in persons:
        names = [p["canonical_name"]]
        try:
            aliases = json.loads(p["aliases_json"] or "[]")
            names.extend(aliases)
        except (json.JSONDecodeError, TypeError):
            pass
        for name in names:
            if name:
                key = name.strip().lower()
                if key:
                    index.setdefault(key, []).append(p["node_id"])
    _log.info("Alias index: %d names → %d persons", len(index), len(persons))
    return index


def is_likely_aikidoka(name: str, context_text: str, domain: str = "") -> bool:
    """Determine if a name reference is likely an aikido practitioner.

    Uses contextual signals from surrounding text and website domain
    to disambiguate aikidoka from non-aikidoka with the same name.
    """
    text_lower = (context_text or "").lower()
    domain_lower = (domain or "").lower()

    if any(d in domain_lower for d in AIKIDO_DOMAIN_SIGNALS):
        return True

    signal_count = sum(1 for s in AIKIDO_CONTEXT_SIGNALS if s in text_lower)
    return signal_count >= 2


def map_head_to_person(
    head_name: str,
    db: LineageDB,
    alias_index: dict[str, list[str]],
    context: str = "",
    domain: str = "",
) -> str | None:
    """Map a head_name string from a CSV row to a person node_id.

    Resolution order:
    1. Exact match on canonical_name (case-insensitive)
    2. Match against alias index (pre-built from all Person nodes)
    3. Fuzzy match (last name substring match)
    4. Return None → caller should queue as person_candidate

    If multiple candidates are found and context is available,
    disambiguate_person() is called to pick the best match.

    Args:
        head_name: Raw name string from source data
        db: LineageDB instance
        alias_index: Pre-built alias index from build_alias_index()
        context: Surrounding text for contextual disambiguation
        domain: Website domain for domain-based disambiguation

    Returns:
        person node_id, or None if unresolved (should be queued as candidate)
    """
    normalized = normalize_person_name(head_name)
    if not normalized:
        return None

    name_lower = normalized.lower()

    # 1. Exact canonical_name match
    matches = db.find_persons_by_name(normalized)
    if len(matches) == 1:
        return matches[0]["node_id"]
    elif len(matches) > 1:
        result = disambiguate_person(normalized, context, domain, matches, db)
        if result:
            return result
        # Ambiguous — queue for reconciliation
        db.queue_for_reconciliation(normalized, "person", {
            "reason": "multiple_canonical_name_matches",
            "candidates": [m["node_id"] for m in matches],
            "context": context,
            "domain": domain,
        }, confidence=0.3)
        return None

    # 2. Alias match
    if name_lower in alias_index:
        candidates = alias_index[name_lower]
        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            # Try disambiguation
            person_rows = [db.get_person(c) for c in candidates]
            person_rows = [p for p in person_rows if p]
            result = disambiguate_person(normalized, context, domain, person_rows, db)
            if result:
                return result
            db.queue_for_reconciliation(normalized, "person", {
                "reason": "multiple_alias_matches",
                "candidates": candidates,
                "context": context,
                "domain": domain,
            }, confidence=0.3)
            return None

    # 3. Fuzzy last-name match
    parts = name_lower.split()
    if len(parts) >= 2:
        last_name = parts[-1]
        # Skip stopwords, very short names, and numeric strings
        if len(last_name) >= 4 and last_name not in FUZZY_STOPWORDS:
            fuzzy = db.query_all(
                "SELECT node_id, canonical_name FROM lineage_persons WHERE lower(canonical_name) LIKE ?",
                (f"%{last_name}%",),
            )
            if len(fuzzy) == 1:
                _log.debug("Fuzzy match: '%s' → '%s' (last name)", normalized, fuzzy[0]["canonical_name"])
                return fuzzy[0]["node_id"]
            elif len(fuzzy) > 1 and len(fuzzy) <= 5:
                # Try full name match among fuzzy results
                for f in fuzzy:
                    if name_lower == f["canonical_name"].lower():
                        return f["node_id"]

    return None


def disambiguate_person(
    name: str,
    context: str,
    domain: str,
    candidates: list[dict],
    db: LineageDB,
) -> str | None:
    """Disambiguate among multiple person candidates using context.

    Args:
        candidates: list of person dicts from lineage_persons (must have node_id)

    Returns:
        The best-matching node_id, or None if still ambiguous.
    """
    if len(candidates) == 1:
        return candidates[0]["node_id"]

    # Check name_collisions table for disambiguator
    collisions = db.get_name_collisions(name)
    if collisions:
        if is_likely_aikidoka(name, context, domain):
            aikido_matches = [c for c in collisions if c["disambiguator"] == "aikido"]
            if len(aikido_matches) == 1:
                return aikido_matches[0]["node_id"]

    # Filter by aikido context
    if is_likely_aikidoka(name, context, domain):
        aikido_candidates = []
        for c in candidates:
            # Check if person's metadata or primary_art suggests aikido
            if c.get("primary_art") and "aikido" in c["primary_art"].lower():
                aikido_candidates.append(c)
            elif c.get("metadata_json"):
                try:
                    meta = json.loads(c["metadata_json"])
                    if any(kw in str(meta).lower() for kw in ["aikido", "dojo", "sensei", "dan"]):
                        aikido_candidates.append(c)
                except (json.JSONDecodeError, TypeError):
                    pass
        if len(aikido_candidates) == 1:
            return aikido_candidates[0]["node_id"]

    # Filter by domain match (person's primary_url domain matches source domain)
    if domain:
        norm_domain = normalize_domain(domain)
        for c in candidates:
            primary_url = c.get("primary_url") or c.get("official_url") or ""
            if primary_url and normalize_domain(primary_url) == norm_domain:
                return c["node_id"]

    # Still ambiguous
    _log.debug("Could not disambiguate '%s' among %d candidates", name, len(candidates))
    return None


def deduplicate_dojos(rows: list[dict]) -> list[dict]:
    """Deduplicate dojo rows by (normalized_domain, city).

    Primary dedup key: website domain (if present)
    Fallback key: name + city

    When duplicates are found, merges data (keeps the most complete row).

    Args:
        rows: list of dicts from dojo_raw (or similar) with keys:
              dojo_name, website, city, email, phone_number, etc.

    Returns:
        Deduplicated list of dojo dicts
    """
    seen: dict[str, dict] = {}
    deduped: list[dict] = []

    for row in rows:
        domain = normalize_domain(row.get("website", ""))
        city_lower = (row.get("city") or "").strip().lower()

        if domain:
            key = f"domain:{domain}"
        else:
            name_lower = clean_dojo_name(row.get("dojo_name", "")).lower()
            key = f"name_city:{name_lower}|{city_lower}"

        if key not in seen:
            seen[key] = dict(row)
            deduped.append(seen[key])
        else:
            existing = seen[key]
            for field in ["email", "phone_number", "dojo_cho_name", "lat", "lng",
                          "heuristic_dojo_cho", "lineage", "division"]:
                if not existing.get(field) and row.get(field):
                    existing[field] = row[field]

    _log.info("Dojo dedup: %d raw → %d unique", len(rows), len(deduped))
    return deduped
