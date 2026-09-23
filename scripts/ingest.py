#!/usr/bin/env python3
"""
Generic JSON-driven ingest — the default way to add data to the story graph.

One-off ingests are declared as JSON files in data/ingest/ instead of
bespoke scripts. All keys are optional:

    {
      "name": "my-ingest",
      "description": "what/why, for future readers",
      "pages": ["https://...", {"url": "...", "retry_archive": true}],
      "nodes":    [{"id", "type", "label", "canonical_name", "metadata", "source_urls"}],
      "edges":    [{"src_id", "rel_type", "dst_id", "metadata"}],
      "sources":  [{"id", "url", "title", "author", "publish_date",
                    "platform", "raw_text", "source_class", "bias_hint"}],
      "claim_sources": [{"claim_id", "source_id",
                         "quote_span_start", "quote_span_end"}],
      "delete_edges": [{"src_id", "rel_type", "dst_id"}],
      "csv_events": {                      # published seminar-calendar CSV
        "file": "data/reference/ikeda_seminar_calendar.csv",
        "url": "<optional live CSV URL — overrides file when set>",
        "person_id": "person:hiroshi-ikeda",
        "person_match": "ikeda",
        "bridge_group_id": "group:aikido-bridge",
        "dojo_aliases": {"nashville aikikai": "dojo:nashville-aikikai"},
        "id_prefix": "ikeda-cal",
        "source_label": "hiroshi-ikeda.com seminar calendar",
        "source_record": {"id": "...", "title": "...", "author": "...",
                          "platform": "...", "source_class": "primary_first_person"}
      }
    }

csv_events expects columns: Start Date, End Date, Seminar, Instructor,
Location, Link, Status, Notes, Source. Each row becomes an Event node;
rows whose Instructor/Seminar matches person_match get a CO_APPEARANCE
edge from person_id; titles containing "bridge" (when bridge_group_id is
set) get MEMBER_OF; a named host dojo gets event -[LOCATED_IN]-> dojo
(mapped via dojo_aliases, else a new dojo:<slug> node).

Usage:
    python scripts/ingest.py data/ingest/<name>.json --dry-run
    python scripts/ingest.py data/ingest/<name>.json
    python scripts/ingest.py data/ingest/<name>.json --no-rebuild --no-export
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
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    ClaimSourceLink,
    GraphEdge,
    GraphNode,
    SourceRecord,
)

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


def ingest_csv_events(spec: dict, db: GraphDB | None) -> dict:
    """Structured ingest of a published seminar-calendar CSV."""
    stats = {"events": 0, "person_edges": 0, "group_edges": 0, "dojo_links": 0}
    url = spec.get("url")
    if url:
        resp = requests.get(url, timeout=settings.crawl_timeout,
                            headers={"User-Agent": "Mozilla/5.0 (story_graph ingest)"})
        resp.raise_for_status()
        resp.encoding = "utf-8"  # sheets omit charset; requests guesses latin-1
        text = resp.text
        if spec.get("file"):
            Path(spec["file"]).parent.mkdir(parents=True, exist_ok=True)
            Path(spec["file"]).write_text(text, encoding="utf-8")
    else:
        text = Path(spec["file"]).read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))

    person_id = spec.get("person_id")
    person_re = re.compile(
        spec.get("person_match", "a^"), re.I) if person_id else None
    bridge_id = spec.get("bridge_group_id")
    aliases = {k.lower(): v for k, v in spec.get("dojo_aliases", {}).items()}
    prefix = spec.get("id_prefix", "cal")
    source_label = spec.get("source_label", "csv calendar")
    fallback_src = spec.get("fallback_source_url") or url or spec.get("file")

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for row in rows:
        title = row["Seminar"]
        h = hashlib.sha1(
            f"{title}|{row['Start Date']}|{row['Location']}".encode()
        ).hexdigest()[:10]
        eid = f"event:{prefix}-{slugify(title, 50)}-{h}"
        loc = parse_location(row.get("Location", ""))
        event_url = (row.get("Link") or "").strip() or fallback_src
        src = (row.get("Source") or "").strip() or fallback_src
        nodes.append(GraphNode(
            id=eid, type="Event", label=title, canonical_name=title,
            metadata={
                "start_date": row.get("Start Date"),
                "end_date": row.get("End Date"),
                "location": row.get("Location"),
                "city": loc.get("city"), "state": loc.get("state"),
                "country": loc.get("country"),
                "instructor": row.get("Instructor") or None,
                "status": row.get("Status"),
                "event_url": event_url,
                "notes": (row.get("Notes") or "").strip() or None,
                "event_type": "seminar",
                "calendar": source_label,
            },
            source_urls=[u for u in {event_url, src} if u],
        ))
        stats["events"] += 1

        if person_re and person_re.search(
            (row.get("Instructor") or "") + " " + title
        ):
            edges.append(GraphEdge(
                src_id=person_id, rel_type="CO_APPEARANCE", dst_id=eid,
                metadata={
                    "role": "instructor",
                    "start_date": row.get("Start Date"),
                    "end_date": row.get("End Date"),
                    "location": row.get("Location"),
                    "status": row.get("Status"),
                    "source_url": src,
                    "source": source_label,
                }))
            stats["person_edges"] += 1

        if bridge_id and "bridge" in title.lower():
            edges.append(GraphEdge(
                src_id=eid, rel_type="MEMBER_OF", dst_id=bridge_id,
                metadata={"source_url": src}))
            stats["group_edges"] += 1

        # host dojo: alias match, else " at <X>" suffix on the title
        low = title.lower()
        dojo_id = next((v for k, v in aliases.items() if k in low), None)
        label = None
        if not dojo_id:
            m = re.search(r"\bat\s+(.+)$", title)
            if m:
                host = re.split(r"\s+[—–-]\s+", m.group(1))[0].strip().rstrip(",")
                if DOJOISH.search(host) and not NON_DOJO_HOSTS.search(host):
                    dojo_id, label = f"dojo:{slugify(host)}", host
        if dojo_id:
            if label:
                nodes.append(GraphNode(
                    id=dojo_id, type="Dojo", label=label,
                    canonical_name=label,
                    metadata={
                        "city": loc.get("city"), "state": loc.get("state"),
                        "country": loc.get("country"), "art": "aikido",
                        "notes": f"Named as seminar host on {source_label}.",
                    },
                    source_urls=[event_url] if event_url else []))
            edges.append(GraphEdge(
                src_id=eid, rel_type="LOCATED_IN", dst_id=dojo_id,
                metadata={"role": "host_dojo", "source_url": src}))
            stats["dojo_links"] += 1

    if db is not None:
        for n in nodes:
            db.add_node(n)
        for e in edges:
            db.add_edge(e)
        if spec.get("source_record"):
            rec = {"url": url or spec.get("file"), **spec["source_record"]}
            if rec.get("raw_text_file"):
                rec["raw_text"] = Path(
                    PROJECT_ROOT / rec.pop("raw_text_file")
                ).read_text(encoding="utf-8")[:50000]
            db.add_source(SourceRecord(**rec))
    return stats


def apply_spec(spec: dict, db: GraphDB | None) -> dict:
    stats = {}
    for rec in spec.get("delete_edges", []):
        stats["edges_deleted"] = stats.get("edges_deleted", 0) + (
            db.delete_edge(rec["src_id"], rec["rel_type"], rec["dst_id"])
            if db else 1
        )
    for rec in spec.get("sources", []):
        if db:
            src = SourceRecord(**rec)
            # sources.url is UNIQUE: if the URL already exists under a
            # different id, update that row instead of inserting a dupe.
            existing = db.get_source_by_url(src.url) if src.url else None
            if existing and existing.id != src.id:
                src.id = existing.id
            db.add_source(src)
        stats["sources"] = stats.get("sources", 0) + 1
    for rec in spec.get("nodes", []):
        if db:
            db.add_node(GraphNode(**rec))
        stats["nodes"] = stats.get("nodes", 0) + 1
    for rec in spec.get("edges", []):
        if db:
            db.add_edge(GraphEdge(**rec))
        stats["edges"] = stats.get("edges", 0) + 1
    for rec in spec.get("claim_sources", []):
        if db:
            db.add_claim_source_link(ClaimSourceLink(**rec))
        stats["claim_sources"] = stats.get("claim_sources", 0) + 1
    if spec.get("csv_events"):
        stats["csv_events"] = ingest_csv_events(spec["csv_events"], db)
    stats["pages"] = len(spec.get("pages", []))
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("spec", help="Path to a data/ingest/*.json file")
    ap.add_argument("--db", default=None)
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    name = spec.get("name", Path(args.spec).stem)
    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print(f"═══ INGEST {name} — story_graph ═══\n")
    if spec.get("description"):
        print(f"  {spec['description']}\n")

    if args.dry_run:
        stats = apply_spec(spec, None)
        print(f"[dry-run] {stats}")
        for p in spec.get("pages", []):
            print(f"  page: {p if isinstance(p, str) else p['url']}")
        return

    db = GraphDB(db_path) if args.no_rebuild else import_from_json(snapshot_dir, db_path)

    # Fetch + extract any declared pages through the standard pipeline.
    # Pages run first so that "sources" entries (or per-page overrides)
    # can re-classify the auto-created source records afterwards.
    pages = spec.get("pages", [])
    if pages:
        from scripts._pipeline_helpers import process_page
        from src.crawler.fetch_page import fetch_page
        from src.extractor.claim_extractor import ClaimExtractor
        from src.extractor.entity_extractor import EntityExtractor

        extractor = EntityExtractor(settings.spacy_model)
        claim_extractor = ClaimExtractor(extractor)
        for p in pages:
            p = {"url": p} if isinstance(p, str) else p
            try:
                page = fetch_page(
                    p["url"], timeout=settings.crawl_timeout,
                    use_browser_ua=p.get("browser_ua", True),
                    retry_archive=p.get("retry_archive", False),
                )
                process_page(page, extractor, claim_extractor, db)
                if p.get("source_class") or p.get("bias_hint"):
                    src = db.get_source_by_url(p["url"])
                    if src:
                        db.add_source(SourceRecord(
                            id=src.id, url=src.url,
                            source_class=p.get("source_class"),
                            bias_hint=p.get("bias_hint"),
                        ))
                print(f"  page OK  {p['url']} — {len(page.text)} chars")
            except requests.RequestException as e:
                print(f"  page FAIL {p['url']}: {e}")

    stats = apply_spec(spec, db)
    print(f"  applied: {stats}")

    print(f"  graph now has {db.get_node_count()} nodes")
    if not args.no_export:
        counts = export_to_json(db, snapshot_dir)
        print(f"  exported: {counts}")
    print("\nDone.")


if __name__ == "__main__":
    main()
