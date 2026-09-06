#!/usr/bin/env python3
"""
Ingest the "Your Guru Was Probably An Abuser" yoga abuse research spreadsheet
into the story_graph.

The spreadsheet was compiled and shared by Reddit user u/RonSwanSong87 in a
post on r/yoga titled "Your Guru Was Probably An Abuser - resource to educate
about abuse in Yoga" (https://reddit.com/r/yoga/comments/1mxe4ua, posted
2025-08-22). The post links to a Google Sheets research compilation tracking
yoga/spiritual gurus, teachers, and organizations with confirmed and/or
alleged abuse profiles, along with sources (documentaries, articles, books,
legal cases) and general background resources.

The script:
1. Fetches the CSV export of the Google Sheet (or reads a local copy)
2. Parses multi-row entries into structured per-entity data
3. For each entity creates:
   - Person nodes (for named individuals) / Group nodes (for organizations)
   - Group nodes for associated organizations
   - Claim nodes for abuse profiles (stance=critical, claim_type=abuse_allegation)
   - SourceRecords for listed sources (documentaries, articles, books, etc.)
   - Edges: MEMBER_OF, ABOUT, ASSERTED_BY, CONTAINS, SUPPORTED_BY
4. Creates a SourceRecord + Work node for the Reddit post + Google Sheet
5. Exports to graph_snapshot/

Usage:
    python scripts/13_ingest_yoga_abuse_sheet.py
    python scripts/13_ingest_yoga_abuse_sheet.py --dry-run
    python scripts/13_ingest_yoga_abuse_sheet.py --db data/graph.db
    python scripts/13_ingest_yoga_abuse_sheet.py --local data/yoga_abuse_research_sheet.csv
"""

import argparse
import csv
import hashlib
import io
import re
import sys
import urllib.request
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    ClaimStance,
    ClaimType,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Source identifiers -----------------------------------------------------
#
# The spreadsheet was posted to r/yoga by u/RonSwanSong87 on 2025-08-22.
# The Reddit post links to the Google Sheet. Both are recorded as sources:
# the Reddit post as the primary source (where the compilation was shared
# and contextualized), and the Google Sheet as the data source.

REDDIT_POST_URL = "https://www.reddit.com/r/yoga/comments/1mxe4ua/your_guru_was_probably_an_abuser_resource_to/"
REDDIT_POST_ID = "1mxe4ua"
REDDIT_AUTHOR = "RonSwanSong87"
REDDIT_POST_DATE = "2025-08-22"
REDDIT_POST_TITLE = (
    "Your Guru Was Probably An Abuser - resource to educate about abuse in Yoga"
)

# The Reddit author is the asserter of the claims in the spreadsheet.
AUTHOR_PERSON_ID = "person:reddit-ronswansong87"
AUTHOR_LABEL = "u/RonSwanSong87 (Reddit)"

# Work + Source for the Reddit post
REDDIT_WORK_ID = "work:reddit:yoga-1mxe4ua"
REDDIT_SOURCE_ID = "source:reddit:yoga-1mxe4ua"

# Work + Source for the Google Sheet (the data behind the post)
SHEET_WORK_ID = "work:googlesheets:yoga-abuse-research"
SHEET_SOURCE_ID = "source:googlesheets:yoga-abuse-research"
SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1-pAxlL2_3QvUYtHCb_19t6aHqwH_ZawRH_7h4GDMf3A/edit"
)
SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1-pAxlL2_3QvUYtHCb_19t6aHqwH_ZawRH_7h4GDMf3A/export?format=csv&gid=0"
)

# --- Date detection for continuation rows -----------------------------------
#
# Column 1 on continuation rows often contains just life dates, e.g.:
#   "8/26/1929 - 10/6/2004 (75)"
#   "b: 1944. (81)"
#   "7/26/1915 - 5/18/2009"
#   "d. 9/11/1973"
#   "1975"
# These are NOT new entity entries — they're continuation data for the
# previous entity's life span.
DATE_PATTERN = re.compile(
    r"^[\s]*"  # optional leading whitespace
    r"(?:b\.?\s*:?\s*|d\.?\s*:?\s*|born\s*|died\s*)?"  # optional prefix (b/d/b./d./b:/d:)
    r"(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4})"  # date or year
    r"(?:\s*[-–—to]+\s*"  # range separator
    r"(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}))?"  # optional end date
    r"[.\s]*"  # optional period/whitespace before age
    r"(?:\(\d+\))?"  # optional age in parens
    r"[\s.]*$"  # optional trailing whitespace/period
    r"|^[\s]*\d{4}[\s]*$",  # just a year
    re.IGNORECASE,
)

# Organization-only entries (no person name, just an org name)
ORG_ONLY_KEYWORDS = (
    "iskcon", "hare krishna", "dahn yoga", "body & brain",
)


def is_date_only(value: str) -> bool:
    """Check if a column-1 value is just a date/life-span, not a new name."""
    v = value.strip()
    if not v:
        return False
    return bool(DATE_PATTERN.match(v))


def is_org_only_entry(name: str) -> bool:
    """Check if an entry name is an organization, not a person."""
    n = name.lower().strip()
    return any(kw in n for kw in ORG_ONLY_KEYWORDS)


def _split_outside_parens(text: str, sep_pattern: str) -> list[str]:
    """Split text on the separator pattern, but not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif depth == 0 and re.match(sep_pattern, text[i:]):
            parts.append("".join(current))
            current = []
            # Skip the separator character(s)
            m = re.match(sep_pattern, text[i:])
            i += len(m.group(0)) - 1  # -1 because we'll i++ at end
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def slugify(text: str) -> str:
    """Create a URL-safe slug from text."""
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_-]+", "-", s).strip("-")
    return s[:60] if s else "unknown"


def short_hash(text: str, length: int = 8) -> str:
    """Create a short deterministic hash from text."""
    return hashlib.md5(text.encode()).hexdigest()[:length]


# --- CSV parsing ------------------------------------------------------------


def fetch_csv(url: str = SHEET_CSV_URL) -> str:
    """Fetch the CSV export from Google Sheets."""
    print(f"  Fetching CSV from Google Sheets...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_sheet(csv_text: str) -> list[dict]:
    """Parse the CSV text into a list of entity entries.

    Each entry is a dict with keys:
        names: list[str] — person names (aliases)
        org_names: list[str] — organization/brand names
        life_dates: str — birth/death info if available
        abuses: str — concatenated abuse profile
        sources: list[str] — source titles from column 4
        general_resources: list[str] — background resources from column 5
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return []

    # Skip header row
    rows = rows[1:]

    entries: list[dict] = []
    current: dict | None = None

    for row in rows:
        # Pad row to expected width
        while len(row) < 6:
            row.append("")

        col_name = row[0].strip()
        col_org = row[1].strip()
        col_abuses = row[2].strip()
        col_sources = row[3].strip()
        col_general = row[4].strip()

        # Determine if this is a new entry or a continuation row
        is_new = False
        if col_name:
            if is_date_only(col_name):
                # Continuation row with life dates
                if current:
                    current["life_dates"] = col_name
            elif is_org_only_entry(col_name):
                # Organization-only entry (no person)
                is_new = True
            else:
                # New person/entity entry
                is_new = True

        if is_new:
            if current:
                entries.append(current)
            # Parse names — split on commas, "+", and "/"
            # But don't split inside parentheses
            name_parts = _split_outside_parens(col_name, r"[,+/]")
            names = [n.strip() for n in name_parts if n.strip()]
            current = {
                "names": names,
                "org_names": [],
                "life_dates": "",
                "abuses": "",
                "sources": [],
                "general_resources": [],
                "is_org_only": is_org_only_entry(col_name),
            }
            if col_org:
                current["org_names"].extend(
                    o.strip() for o in _split_outside_parens(col_org, r",") if o.strip()
                )
            if col_abuses:
                current["abuses"] = col_abuses
            if col_sources:
                current["sources"].append(col_sources)
            if col_general:
                current["general_resources"].append(col_general)
        else:
            if current is None:
                continue
            if col_org:
                current["org_names"].extend(
                    o.strip() for o in _split_outside_parens(col_org, r",") if o.strip()
                )
            if col_abuses:
                if current["abuses"]:
                    current["abuses"] += " " + col_abuses
                else:
                    current["abuses"] = col_abuses
            if col_sources:
                current["sources"].append(col_sources)
            if col_general:
                current["general_resources"].append(col_general)

    if current:
        entries.append(current)

    # Deduplicate org names and sources within each entry
    for e in entries:
        e["org_names"] = list(dict.fromkeys(e["org_names"]))
        e["sources"] = list(dict.fromkeys(e["sources"]))
        e["general_resources"] = list(dict.fromkeys(e["general_resources"]))

    return entries


# --- Node lookup helpers ----------------------------------------------------


def build_existing_lookup(db: GraphDB) -> tuple[dict[str, str], dict[str, str]]:
    """Build lookup tables for existing Person and Group nodes.

    Returns (person_lookup, group_lookup) where each maps a normalized
    canonical_name or label to the existing node id.
    """
    person_lookup: dict[str, str] = {}
    group_lookup: dict[str, str] = {}

    for node in db.get_nodes_by_type(NodeType.PERSON):
        key = _norm(node.canonical_name or node.label)
        if key:
            person_lookup[key] = node.id
    for node in db.get_nodes_by_type(NodeType.GROUP):
        key = _norm(node.canonical_name or node.label)
        if key:
            group_lookup[key] = node.id

    return person_lookup, group_lookup


def _norm(text: str | None) -> str:
    """Normalize text for fuzzy matching."""
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_existing_person(person_lookup: dict[str, str], name: str) -> str | None:
    """Find an existing Person node by name, trying several normalizations."""
    key = _norm(name)
    if key in person_lookup:
        return person_lookup[key]
    # Try without common prefixes (Swami, Guru, etc.)
    stripped = re.sub(r"^(swami|guru|sri|sri sri|baba|dr)\s+", "", name, flags=re.IGNORECASE)
    key2 = _norm(stripped)
    if key2 and key2 in person_lookup:
        return person_lookup[key2]
    return None


def find_existing_group(group_lookup: dict[str, str], name: str) -> str | None:
    """Find an existing Group node by name."""
    key = _norm(name)
    if key in group_lookup:
        return group_lookup[key]
    # Try shorter substrings for long org names
    for existing_key, existing_id in group_lookup.items():
        if len(key) > 6 and key in existing_key:
            return existing_id
        if len(existing_key) > 6 and existing_key in key:
            return existing_id
    return None


# --- Source URL extraction --------------------------------------------------


def extract_url(text: str) -> str | None:
    """Extract a URL from a source string, if present."""
    url_match = re.search(r"https?://[^\s,]+", text)
    if url_match:
        return url_match.group(0).rstrip(".,)")
    return None


def clean_source_title(text: str) -> str:
    """Clean up a source string to use as a title."""
    # If it's just a URL, return a placeholder
    url = extract_url(text)
    if url and text.strip() == url:
        return f"Web resource ({url[:60]}...)"
    # Remove trailing URLs for the title
    title = re.sub(r"\s*https?://\S+\s*", "", text).strip().rstrip(",.")
    return title if title else text[:80]


# --- Source setup ------------------------------------------------------------


def ensure_sources(db: GraphDB, dry_run: bool = False) -> None:
    """Create/update the source nodes: Reddit author, Reddit post, Google Sheet."""
    if dry_run:
        print("  [dry-run] would ensure source nodes")
        return

    # Person node for the Reddit author (asserter of the claims)
    db.add_node(GraphNode(
        id=AUTHOR_PERSON_ID,
        type=NodeType.PERSON,
        label=AUTHOR_LABEL,
        canonical_name=AUTHOR_LABEL,
        metadata={
            "role": "reddit_researcher",
            "username": REDDIT_AUTHOR,
            "subreddit": "yoga",
            "note": (
                "Reddit user who compiled and shared the 'Your Guru Was "
                "Probably An Abuser' yoga abuse research spreadsheet. "
                "Claims ASSERTED_BY this node are their research "
                "compilation, pending independent corroboration."
            ),
        },
        source_urls=[REDDIT_POST_URL],
    ))

    # Work node for the Reddit post
    db.add_node(GraphNode(
        id=REDDIT_WORK_ID,
        type=NodeType.WORK,
        label=REDDIT_POST_TITLE,
        canonical_name=None,
        metadata={
            "url": REDDIT_POST_URL,
            "platform": "reddit",
            "subreddit": "yoga",
            "work_type": "reddit_post",
            "post_id": REDDIT_POST_ID,
            "post_date": REDDIT_POST_DATE,
            "note": (
                "Reddit post sharing a yoga/spiritual abuse research "
                "compilation. Links to a Google Sheet with per-guru abuse "
                "profiles, sources, and background resources."
            ),
        },
        source_urls=[REDDIT_POST_URL],
    ))

    # SourceRecord for the Reddit post
    db.add_source(SourceRecord(
        id=REDDIT_SOURCE_ID,
        url=REDDIT_POST_URL,
        title=REDDIT_POST_TITLE,
        author=REDDIT_AUTHOR,
        publish_date=REDDIT_POST_DATE,
        platform="reddit/r/yoga",
        source_class=SourceClass.COMMENT_THREAD,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))

    # Work node for the Google Sheet (the data behind the post)
    db.add_node(GraphNode(
        id=SHEET_WORK_ID,
        type=NodeType.WORK,
        label="Yoga/Spiritual Abuse Research Compilation (Google Sheets)",
        canonical_name=None,
        metadata={
            "url": SHEET_URL,
            "platform": "Google Sheets",
            "work_type": "research_compilation",
            "shared_via": REDDIT_POST_URL,
            "note": (
                "Google Sheets research compilation by u/RonSwanSong87 "
                "tracking yoga/spiritual gurus and organizations with abuse "
                "allegations, their sources, and background resources. "
                "Shared via Reddit post r/yoga/1mxe4ua."
            ),
        },
        source_urls=[SHEET_URL, REDDIT_POST_URL],
    ))

    # SourceRecord for the Google Sheet
    db.add_source(SourceRecord(
        id=SHEET_SOURCE_ID,
        url=SHEET_URL,
        title="Yoga/Spiritual Abuse Research Compilation",
        author=REDDIT_AUTHOR,
        platform="Google Sheets (shared via Reddit)",
        source_class=SourceClass.COMMENT_THREAD,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))

    # Link the Reddit post to the Google Sheet (the post DESCRIBES the sheet)
    db.add_edge(GraphEdge(
        src_id=REDDIT_WORK_ID,
        rel_type=RelationType.DESCRIBES,
        dst_id=SHEET_WORK_ID,
        metadata={"evidence": "Reddit post links to the Google Sheet"},
    ))


# --- Main ingestion ---------------------------------------------------------


def ingest(db: GraphDB, entries: list[dict], dry_run: bool = False) -> int:
    """Ingest all parsed entries into the graph DB."""
    added = 0
    person_lookup, group_lookup = build_existing_lookup(db)

    # Ensure source nodes exist
    ensure_sources(db, dry_run=dry_run)

    for entry in entries:
        names = entry["names"]
        org_names = entry["org_names"]
        abuses = entry["abuses"].strip()
        life_dates = entry["life_dates"]
        sources = entry["sources"]
        is_org = entry.get("is_org_only", False)

        if not names and not org_names:
            continue

        # --- Create Person nodes (or Group if org-only) -------------------
        person_ids: list[str] = []
        group_ids_for_entry: list[str] = []

        if is_org:
            # Organization-only entry (e.g., ISKCON, Dahn Yoga) — treat
            # all names as org names, not person names.
            all_org_names = list(org_names)
            for n in names:
                if n not in all_org_names:
                    all_org_names.append(n)
            for org_name in all_org_names:
                gid = _ensure_group(db, group_lookup, org_name, dry_run=dry_run)
                if gid:
                    group_ids_for_entry.append(gid)
                    if not dry_run:
                        added += 1
        else:
            for name in names:
                pid = find_existing_person(person_lookup, name)
                if pid:
                    print(f"  [exists] person: {name} -> {pid}")
                    person_ids.append(pid)
                    # Update with sheet metadata
                    if not dry_run:
                        _update_person_from_sheet(db, pid, name, life_dates, abuses, dry_run=False)
                else:
                    new_id = f"person:yoga-{slugify(name)}"
                    if dry_run:
                        print(f"  [dry-run] would add person: {name} ({new_id})")
                    else:
                        db.add_node(GraphNode(
                            id=new_id,
                            type=NodeType.PERSON,
                            label=name,
                            canonical_name=name,
                            metadata={
                                "description": f"Yoga/spiritual teacher researched in Reddit yoga abuse research compilation.",
                                "life_dates": life_dates,
                                "abuse_profile": abuses,
                                "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)",
                            },
                            source_urls=[REDDIT_POST_URL, SHEET_URL],
                        ))
                        person_lookup[_norm(name)] = new_id
                        print(f"  Added person: {new_id} — {name}")
                        added += 1
                    person_ids.append(new_id)

        # --- Create Group nodes for organizations -------------------------
        for org_name in org_names:
            gid = _ensure_group(db, group_lookup, org_name, dry_run=dry_run)
            if gid:
                group_ids_for_entry.append(gid)

        # --- Create MEMBER_OF / FOUNDED edges -----------------------------
        if not dry_run:
            for pid in person_ids:
                for gid in group_ids_for_entry:
                    db.add_edge(GraphEdge(
                        src_id=pid,
                        rel_type=RelationType.MEMBER_OF,
                        dst_id=gid,
                        metadata={
                            "evidence": f"Reddit yoga abuse research compilation (u/RonSwanSong87)",
                            "source": SHEET_URL,
                            "verified_independently": False,
                        },
                    ))

        # --- Create Claim node for the abuse profile ----------------------
        if abuses and (person_ids or group_ids_for_entry):
            claim_text = _build_claim_text(names, org_names, abuses)
            claim_slug = slugify(names[0] if names else org_names[0])
            claim_id = f"claim:yoga-abuse-{claim_slug}-{short_hash(claim_text)}"

            existing_claim = db.get_node(claim_id)
            if existing_claim:
                print(f"  [exists] claim: {claim_id}")
            elif dry_run:
                print(f"  [dry-run] would add claim: {claim_text[:80]}...")
            else:
                db.add_node(GraphNode(
                    id=claim_id,
                    type=NodeType.CLAIM,
                    label=claim_text[:200],
                    canonical_name=None,
                    metadata={
                        "claim_text": claim_text,
                        "claim_type": ClaimType.ABUSE_ALLEGATION.value,
                        "stance": ClaimStance.CRITICAL.value,
                        "confidence": 0.5,
                        "evidence_mode": "secondary_report",
                        "pending_independent_corroboration": True,
                        "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)",
                    },
                    source_urls=[REDDIT_POST_URL, SHEET_URL],
                ))
                print(f"  Added claim: {claim_id} — {claim_text[:60]}...")
                added += 1

                # Wire claim edges
                # ASSERTED_BY Reddit author
                db.add_edge(GraphEdge(
                    src_id=claim_id,
                    rel_type=RelationType.ASSERTED_BY,
                    dst_id=AUTHOR_PERSON_ID,
                    metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                ))
                # CONTAINS — the sheet contains this claim
                db.add_edge(GraphEdge(
                    src_id=SHEET_WORK_ID,
                    rel_type=RelationType.CONTAINS,
                    dst_id=claim_id,
                    metadata={"evidence": SHEET_URL},
                ))
                # ABOUT — claim is about each person and group
                for pid in person_ids:
                    db.add_edge(GraphEdge(
                        src_id=claim_id,
                        rel_type=RelationType.ABOUT,
                        dst_id=pid,
                        metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                    ))
                for gid in group_ids_for_entry:
                    db.add_edge(GraphEdge(
                        src_id=claim_id,
                        rel_type=RelationType.ABOUT,
                        dst_id=gid,
                        metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                    ))
                # Link claim to both the Reddit post and the sheet source
                db.add_claim_source_link(ClaimSourceLink(
                    claim_id=claim_id,
                    source_id=REDDIT_SOURCE_ID,
                ))
                db.add_claim_source_link(ClaimSourceLink(
                    claim_id=claim_id,
                    source_id=SHEET_SOURCE_ID,
                ))

        # --- Create SourceRecords for listed sources ----------------------
        if not dry_run:
            for src_text in sources:
                _add_listed_source(db, src_text, person_ids, group_ids_for_entry, claim_id if abuses else None)

        # --- MENTIONS edges from the sheet work + Reddit post to each entity
        if not dry_run:
            for pid in person_ids:
                db.add_edge(GraphEdge(
                    src_id=SHEET_WORK_ID,
                    rel_type=RelationType.MENTIONS,
                    dst_id=pid,
                    metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                ))
                db.add_edge(GraphEdge(
                    src_id=REDDIT_WORK_ID,
                    rel_type=RelationType.MENTIONS,
                    dst_id=pid,
                    metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                ))
            for gid in group_ids_for_entry:
                db.add_edge(GraphEdge(
                    src_id=SHEET_WORK_ID,
                    rel_type=RelationType.MENTIONS,
                    dst_id=gid,
                    metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                ))
                db.add_edge(GraphEdge(
                    src_id=REDDIT_WORK_ID,
                    rel_type=RelationType.MENTIONS,
                    dst_id=gid,
                    metadata={"evidence": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
                ))

        print()  # blank line between entries

    return added


def _ensure_group(db: GraphDB, group_lookup: dict[str, str], name: str, dry_run: bool = False) -> str | None:
    """Find or create a Group node for an organization name."""
    existing_id = find_existing_group(group_lookup, name)
    if existing_id:
        print(f"  [exists] group: {name} -> {existing_id}")
        return existing_id

    new_id = f"group:yoga-{slugify(name)}"
    if dry_run:
        print(f"  [dry-run] would add group: {name} ({new_id})")
        return new_id

    db.add_node(GraphNode(
        id=new_id,
        type=NodeType.GROUP,
        label=name,
        canonical_name=name,
        metadata={
            "description": f"Yoga/spiritual organization researched in Reddit yoga abuse research compilation.",
            "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)",
        },
        source_urls=[REDDIT_POST_URL, SHEET_URL],
    ))
    group_lookup[_norm(name)] = new_id
    print(f"  Added group: {new_id} — {name}")
    return new_id


def _update_person_from_sheet(db: GraphDB, pid: str, name: str, life_dates: str, abuses: str, dry_run: bool = False) -> None:
    """Update an existing Person node with sheet metadata (merge)."""
    if dry_run:
        return
    existing = db.get_node(pid)
    if not existing:
        return
    merged_meta = {**existing.metadata}
    if life_dates and not merged_meta.get("life_dates"):
        merged_meta["life_dates"] = life_dates
    if abuses and not merged_meta.get("abuse_profile"):
        merged_meta["abuse_profile"] = abuses
    merged_meta["yoga_abuse_sheet"] = True
    merged_urls = sorted(set(existing.source_urls + [REDDIT_POST_URL, SHEET_URL]))
    db.add_node(GraphNode(
        id=pid,
        type=NodeType.PERSON,
        label=existing.label,
        canonical_name=existing.canonical_name,
        metadata=merged_meta,
        source_urls=merged_urls,
    ))


def _build_claim_text(names: list[str], org_names: list[str], abuses: str) -> str:
    """Build a claim text string from the entry data."""
    subject = ", ".join(names) if names else ", ".join(org_names)
    orgs = f" ({', '.join(org_names)})" if org_names and names else ""
    return f"{subject}{orgs} — abuse profile: {abuses}"


def _add_listed_source(
    db: GraphDB,
    src_text: str,
    person_ids: list[str],
    group_ids: list[str],
    claim_id: str | None,
) -> None:
    """Create a SourceRecord + Work node for a listed source, with MENTIONS edges."""
    url = extract_url(src_text)
    title = clean_source_title(src_text)
    src_slug = slugify(title)[:40]
    src_hash = short_hash(src_text)
    source_id = f"source:yoga-{src_slug}-{src_hash}"
    work_id = f"work:yoga-{src_slug}-{src_hash}"

    # Skip if already exists
    if db.get_source(source_id):
        return

    # Determine source class from the text
    src_lower = src_text.lower()
    if "documentary" in src_lower or "docu" in src_lower:
        source_class = SourceClass.DOCUMENTARY_PROMOTIONAL
    elif "podcast" in src_lower:
        source_class = SourceClass.JOURNALISTIC
    elif "wiki" in src_lower:
        source_class = SourceClass.ARCHIVAL
    elif "lawsuit" in src_lower or "case" in src_lower or "court" in src_lower:
        source_class = SourceClass.ARCHIVAL
    elif "book" in src_lower:
        source_class = SourceClass.PRIMARY_FIRST_PERSON
    elif url:
        source_class = SourceClass.JOURNALISTIC
    else:
        source_class = SourceClass.COMMENT_THREAD

    pseudo_url = url or f"reddit://yoga-sheet-source/{src_hash}"

    db.add_source(SourceRecord(
        id=source_id,
        url=pseudo_url,
        title=title,
        author=None,
        platform="Reddit research compilation (listed source)",
        source_class=source_class,
        bias_hint=BiasHint.NEUTRAL_ISH,
    ))

    db.add_node(GraphNode(
        id=work_id,
        type=NodeType.WORK,
        label=title[:100],
        canonical_name=None,
        metadata={
            "work_type": "listed_source",
            "original_text": src_text[:500],
            "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)",
            "url": url,
        },
        source_urls=[pseudo_url] if pseudo_url != f"reddit://yoga-sheet-source/{src_hash}" else [],
    ))

    # MENTIONS edges from this source work to each person/group
    for pid in person_ids:
        db.add_edge(GraphEdge(
            src_id=work_id,
            rel_type=RelationType.MENTIONS,
            dst_id=pid,
            metadata={"evidence": src_text[:200], "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
        ))
    for gid in group_ids:
        db.add_edge(GraphEdge(
            src_id=work_id,
            rel_type=RelationType.MENTIONS,
            dst_id=gid,
            metadata={"evidence": src_text[:200], "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
        ))

    # If we have a claim, link it as SUPPORTED_BY this source
    if claim_id:
        db.add_edge(GraphEdge(
            src_id=claim_id,
            rel_type=RelationType.SUPPORTED_BY,
            dst_id=work_id,
            metadata={"evidence": src_text[:200], "source": "Reddit yoga abuse research compilation (u/RonSwanSong87)"},
        ))
        db.add_claim_source_link(ClaimSourceLink(
            claim_id=claim_id,
            source_id=source_id,
        ))


# --- Main -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ingest the Reddit-sourced Yoga/Spiritual Abuse Research spreadsheet into story_graph"
    )
    parser.add_argument("--db", default=None, help="Path to graph.db")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip graph_snapshot export")
    parser.add_argument("--local", default=None, help="Read CSV from a local file instead of fetching")
    args = parser.parse_args(argv)

    print("""
╔════════════════════════════════════════════════════════════════════╗
║   YOGA/SPIRITUAL ABUSE RESEARCH SHEET INGESTION — story_graph      ║
║   Reddit yoga abuse research compilation (u/RonSwanSong87)                       ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    # Get CSV text
    if args.local:
        csv_path = Path(args.local)
        if not csv_path.is_absolute():
            csv_path = PROJECT_ROOT / csv_path
        print(f"  Reading CSV from local file: {csv_path}")
        csv_text = csv_path.read_text(encoding="utf-8")
    else:
        try:
            csv_text = fetch_csv()
        except Exception as exc:
            print(f"  [WARNING] Failed to fetch from Google Sheets: {exc}")
            local_fallback = PROJECT_ROOT / "data" / "yoga_abuse_research_sheet.csv"
            if local_fallback.exists():
                print(f"  Falling back to local copy: {local_fallback}")
                csv_text = local_fallback.read_text(encoding="utf-8")
            else:
                print(f"  ERROR: No local fallback found at {local_fallback}")
                return 1

    # Parse
    entries = parse_sheet(csv_text)
    print(f"\n  Parsed {len(entries)} entity entries from the spreadsheet\n")

    if args.dry_run:
        print("[dry-run mode — no DB writes]\n")

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / "graph.db"
    db = GraphDB(db_path)
    try:
        added = ingest(db, entries, dry_run=args.dry_run)
        print(f"\n{'Would add' if args.dry_run else 'Added'} {added} new nodes/edges")

        if not args.dry_run and not args.no_export:
            snapshot_dir = PROJECT_ROOT / "graph_snapshot"
            counts = export_to_json(db, snapshot_dir)
            print(f"Exported snapshot: {counts}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
