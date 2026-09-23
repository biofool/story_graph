#!/usr/bin/env python3
"""
Ingest hiroshi-ikeda.com — Ikeda Shihan's own website — into the story graph.

Two parts:

1. Static pages (Home, About, Aikido Bridge, Kanji Art, Contact) go through
   the standard fetch_page -> process_page extraction pipeline. The /about
   page is a first-person bio: 8th dan (Jan 2025), Boulder Aikikai founder
   1980, Saotome's Reimeijuku Dojo 1969, Sarasota Aikikai 1976, ASU VP,
   Aikido Shimbokukai VP 2016, Bu Jin Design, Aikido Bridge founder.

2. The /seminars page is JS-rendered from a published Google Sheet CSV
   (found in the page's footer code injection). The CSV is ingested as
   structured data — the authoritative first-party seminar calendar:
   one Event node per row, a CO_APPEARANCE edge from person:hiroshi-ikeda
   for rows where he teaches, MEMBER_OF -> group:aikido-bridge for Bridge
   series events, and event -[LOCATED_IN]-> dojo edges where the seminar
   title names a host dojo. Host names are mapped to existing dojo nodes
   via DOJO_ALIASES; unrecognized dojo-like hosts get a new Dojo node.
   A copy of the fetched CSV is kept at data/reference/ikeda_seminar_calendar.csv
   for provenance.

This is the *verified* counterpart to the speculative leads in
data/ikeda_visited_dojos.json (issue #65): e.g. the real Kansas City host
is Aikijuku Dojo (not the variant-guessed KC dojos), the Big Island visit
is the Kona Winter Camp (not Kohala Aikikai — refuted by Kristina Varjan),
and Istanbul Aikikai is the real Istanbul host.

Usage:
    python scripts/57_ingest_ikeda_website.py --dry-run
    python scripts/57_ingest_ikeda_website.py
    python scripts/57_ingest_ikeda_website.py --no-export --no-rebuild
"""

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from config.settings import settings
from scripts._pipeline_helpers import process_page
from src.crawler.fetch_page import fetch_page
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.entity_extractor import EntityExtractor
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

SITE = "https://www.hiroshi-ikeda.com"
PAGES = ["/", "/about", "/aikido-bridge", "/kanji-art", "/contact"]

# Published Google Sheet behind the JS-rendered /seminars calendar
# (Squarespace footer code injection: "Global Seminars + Video Catalogue").
SEMINAR_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vSVKDcmv_f3fA4nkwSVkt4GDDzWZMKGyohp9mW7LXWPm9m76AxuJ3nGW8iQAs"
    "BcyPPYfwHp0tvnUnLt/pub?gid=501055104&single=true&output=csv"
)
CSV_COPY = PROJECT_ROOT / "data" / "reference" / "ikeda_seminar_calendar.csv"

IKEDA_ID = "person:hiroshi-ikeda"
BRIDGE_ID = "group:aikido-bridge"
SEMINARS_PAGE = f"{SITE}/seminars"

# Seminar-title host -> existing dojo node id (avoids duplicate dojo nodes
# for hosts already in the graph under a different label).
DOJO_ALIASES = {
    "aikido tamalpais": "dojo:aikido-of-tamalpais",
    "aikido of tamalpais": "dojo:aikido-of-tamalpais",
    "san diego aikido bridge": "dojo:jiai-aikido",  # sandiegoaikido.com = Jiai
    "aikido shobukan": "dojo:aikido-shobukan-dojo",
    "tampa aikido": "dojo:aikido-chuseikan-of-tampa-bay",  # tampaaikido.com
    "nashville aikikai": "dojo:nashville-aikikai",
    "aikido kenkyukai": "dojo:aikido-kenkyukai-los-angeles",
    "allegheny aikido": "dojo:allegheny-aikido",
    "boulder aikikai": "dojo:boulder-aikikai",
    "two cranes aikido": "dojo:two-cranes-aikido",
    "bond street dojo": "dojo:bond-street-dojo",
    "aiki-kai zurich": "dojo:aiki-kai-zurich",
    "aiki-kai zürich": "dojo:aiki-kai-zurich",
    "shindai aikido": "dojo:shindai-aikikai",
    "arizona aikido": "dojo:arizona-aikido",
}

# "at X" hosts that are event series, not dojos — never create Dojo nodes.
NON_DOJO_HOSTS = re.compile(
    r"winter intensive|winter camp|summer camp|world seminar|"
    r"friendship seminar|bridge seminar|reunion seminar",
    re.I,
)

DOJOISH = re.compile(
    r"aikido|aikikai|aiki|dojo|juku|kan\b|shumeikai|butokukan|budo", re.I
)


def slugify(text: str, maxlen: int = 80) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen].strip("-")


def cal_event_id(row: dict) -> str:
    h = hashlib.sha1(
        f"{row['Seminar']}|{row['Start Date']}|{row['Location']}".encode()
    ).hexdigest()[:10]
    return f"event:ikeda-cal-{slugify(row['Seminar'], 50)}-{h}"


def ikeda_teaches(row: dict) -> bool:
    return bool(
        re.search(r"ikeda", (row.get("Instructor") or "") + " " + row["Seminar"], re.I)
    )


def is_bridge(row: dict) -> bool:
    return "bridge" in row["Seminar"].lower()


def host_dojo(row: dict) -> str | None:
    """Return the host-dojo label named in the seminar title, or None."""
    title = row["Seminar"]
    low = title.lower()
    for alias, dojo_id in DOJO_ALIASES.items():
        if alias in low:
            return dojo_id  # existing node id, returned via alias path
    m = re.search(r"\bat\s+(.+)$", title)
    if not m:
        return None
    host = re.split(r"\s+[—–-]\s+", m.group(1))[0].strip().rstrip(",")
    if NON_DOJO_HOSTS.search(host) or not DOJOISH.search(host):
        return None
    return host


def parse_location(loc: str) -> dict:
    """'St. Pete Beach, FL, USA' -> {city, state, country} (best effort)."""
    out = {"raw": loc}
    if not loc or "virtual" in loc.lower():
        return out
    parts = [p.strip() for p in loc.split(",") if p.strip()]
    if not parts:
        return out
    if re.fullmatch(r"[A-Z]{2}|USA|United States", parts[-1]):
        if parts[-1].upper() in ("USA", "UNITED STATES"):
            out["country"] = "United States"
            parts = parts[:-1]
        else:
            out["country"] = parts.pop()
    elif parts[-1].isupper() or parts[-1].lower() in (
        "france", "italy", "japan", "switzerland", "poland", "india",
        "costa rica", "canada", "uk", "turkey", "morocco", "germany",
        "brazil", "finland",
    ):
        out["country"] = parts.pop().title()
    if len(parts) >= 2:
        out["city"], out["state"] = parts[0], parts[1]
    elif parts:
        out["city"] = parts[0]
    return out


def fetch_seminar_rows(timeout: int) -> list[dict]:
    resp = requests.get(
        SEMINAR_CSV_URL, timeout=timeout,
        headers={"User-Agent": "Mozilla/5.0 (story_graph ingest)"},
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"  # sheet is UTF-8; response omits charset
    CSV_COPY.parent.mkdir(parents=True, exist_ok=True)
    CSV_COPY.write_text(resp.text, encoding="utf-8")
    return list(csv.DictReader(io.StringIO(resp.text)))


def ingest_calendar(rows: list[dict], db: GraphDB | None) -> dict:
    stats = {"events": 0, "ikeda_edges": 0, "bridge": 0, "dojo_links": 0}
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for row in rows:
        eid = cal_event_id(row)
        loc = parse_location(row.get("Location", ""))
        event_url = (row.get("Link") or "").strip() or SEMINARS_PAGE
        src = (row.get("Source") or "").strip() or SEMINARS_PAGE
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=row["Seminar"],
            canonical_name=row["Seminar"],
            metadata={
                "start_date": row.get("Start Date"),
                "end_date": row.get("End Date"),
                "location": row.get("Location"),
                "city": loc.get("city"),
                "state": loc.get("state"),
                "country": loc.get("country"),
                "instructor": row.get("Instructor") or None,
                "status": row.get("Status"),
                "event_url": event_url,
                "notes": (row.get("Notes") or "").strip() or None,
                "event_type": "seminar",
                "calendar": "hiroshi-ikeda.com/seminars (published Google Sheet)",
            },
            source_urls=[event_url, src],
        ))
        stats["events"] += 1

        if ikeda_teaches(row):
            edges.append(GraphEdge(
                src_id=IKEDA_ID, rel_type=RelationType.CO_APPEARANCE,
                dst_id=eid,
                metadata={
                    "role": "instructor",
                    "start_date": row.get("Start Date"),
                    "end_date": row.get("End Date"),
                    "location": row.get("Location"),
                    "status": row.get("Status"),
                    "source_url": src,
                    "source": "hiroshi-ikeda.com seminar calendar",
                }))
            stats["ikeda_edges"] += 1

        if is_bridge(row):
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.MEMBER_OF, dst_id=BRIDGE_ID,
                metadata={"source_url": src}))
            stats["bridge"] += 1

        host = host_dojo(row)
        if host:
            if host.startswith("dojo:"):
                dojo_id, label = host, None
            else:
                dojo_id, label = f"dojo:{slugify(host)}", host
            if label:
                nodes.append(GraphNode(
                    id=dojo_id, type=NodeType.DOJO, label=label,
                    canonical_name=label,
                    metadata={
                        "city": loc.get("city"), "state": loc.get("state"),
                        "country": loc.get("country"), "art": "aikido",
                        "notes": "Named as seminar host on Ikeda's official calendar.",
                    },
                    source_urls=[event_url]))
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.LOCATED_IN, dst_id=dojo_id,
                metadata={"role": "host_dojo", "source_url": src}))
            stats["dojo_links"] += 1

    if db is not None:
        for n in nodes:
            db.add_node(n)
        for e in edges:
            db.add_edge(e)
        db.add_source(SourceRecord(
            id="source:ikeda-seminar-calendar",
            url=SEMINAR_CSV_URL,
            title="Hiroshi Ikeda seminar calendar (published Google Sheet)",
            author="Hiroshi Ikeda",
            platform="hiroshi-ikeda.com",
            raw_text=CSV_COPY.read_text(encoding="utf-8")[:50000],
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        ))
    return stats


def main():
    ap = argparse.ArgumentParser(description="Ingest hiroshi-ikeda.com into the story graph")
    ap.add_argument("--db", default=None)
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    ap.add_argument("--skip-pages", action="store_true", help="CSV ingest only")
    args = ap.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print("═══ INGEST hiroshi-ikeda.com — story_graph ═══\n")

    print("[1/3] Fetching seminar calendar CSV...")
    rows = fetch_seminar_rows(settings.crawl_timeout)
    ikeda_rows = [r for r in rows if ikeda_teaches(r)]
    print(f"  {len(rows)} rows, {len(ikeda_rows)} with Ikeda teaching "
          f"(copy saved to {CSV_COPY.relative_to(PROJECT_ROOT)})")

    pages = []
    if not args.skip_pages:
        print("\n[2/3] Fetching site pages...")
        for path in PAGES:
            url = f"{SITE}{path}"
            try:
                page = fetch_page(url, timeout=settings.crawl_timeout,
                                  use_browser_ua=True)
                pages.append(page)
                print(f"  OK  {url} — {len(page.text)} chars")
            except requests.RequestException as e:
                print(f"  FAIL {url}: {e}")

    if args.dry_run:
        print("\n[dry-run]")
        st = ingest_calendar(rows, None)
        print(f"  would add {st}")
        for r in ikeda_rows:
            print(f"    {r['Start Date']}  {r['Seminar'][:80]}  ({r['Location']})")
        return

    print("\n[3/3] Rebuilding DB from snapshot, ingesting, exporting...")
    db = GraphDB(db_path) if args.no_rebuild else import_from_json(snapshot_dir, db_path)

    if pages:
        extractor = EntityExtractor(settings.spacy_model)
        claim_extractor = ClaimExtractor(extractor)
        for page in pages:
            print(f"  process_page: {page.url}")
            process_page(page, extractor, claim_extractor, db)

    st = ingest_calendar(rows, db)
    print(f"  calendar ingest: {st}")
    print(f"  graph now has {db.get_node_count()} nodes")

    if not args.no_export:
        counts = export_to_json(db, snapshot_dir)
        print(f"  exported: {counts}")
    print("\nDone.")


if __name__ == "__main__":
    main()
