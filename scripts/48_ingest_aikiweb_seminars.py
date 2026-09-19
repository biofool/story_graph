#!/usr/bin/env python3
"""Ingest AikiWeb seminar listings for an instructor into the story graph.

Reads the locally archived AikiWeb seminar listing pages
(data/reference/aikiweb/seminar_pages/*.txt, produced by
scripts/45_aikiweb_seminars_crawl.py), extracts entries whose TITLE
matches --taught-by, and ingests them as event:aikiweb-* Event nodes.

For each event:
  person:<slug> -[CO_APPEARANCE]-> event   (the --taught-by instructor)
  person:<other> -[CO_APPEARANCE]-> event  (any other existing graph
    Person node whose canonical_name/label appears in the title)
  event -[LOCATED_IN]-> dojo:*             (when the venue matches an
    existing Dojo node's canonical_name/label)

Creates the taught-by Person node if missing. Extracted listings are
also written to data/reference/aikiweb_<slug>_listings.json.

Examples:
    python scripts/48_ingest_aikiweb_seminars.py --taught-by "Richard Moon" \
        --person-id person:richard-moon-aikido --dry-run
    python scripts/48_ingest_aikiweb_seminars.py --taught-by "Hiroshi Ikeda"
"""
import argparse
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

GRAPH_DB = "data/graph.db"
PAGES_DIR = "data/reference/aikiweb/seminar_pages"

ENTRY_RE = re.compile(
    r"([^\n]{10,200})\s*\n\s*Share\s*\n\(Permalink\)(.*?)"
    r"(?=\n[^\n]{10,200}\s*\n\s*Share\s*\n\(Permalink\)|$)", re.S)


def slugify(text, maxlen=60):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:maxlen].strip("-")


def field(rest, key):
    m = re.search(key + r":\s*([^\n]+)", rest)
    return m.group(1).strip() if m else ""


def extract_listings(pages_dir, title_pat):
    out = []
    for fn in sorted(os.listdir(pages_dir)):
        if not fn.endswith(".txt"):
            continue
        body = open(os.path.join(pages_dir, fn), errors="replace").read()
        region = fn[:-4].replace("_", " ")
        for m in ENTRY_RE.finditer(body):
            title, rest = m.group(1).strip(), m.group(2)
            if not title_pat.search(title):
                continue
            u = re.search(r"(?:^|\n)(?:Facebook URL|URL)\s*(https?://\S+)", rest)
            out.append({
                "region": region, "title": title,
                "dates": field(rest, "Dates?"), "venue": field(rest, "Venue"),
                "address": field(rest, "Address"),
                "url": u.group(1) if u else "",
                "notes": field(rest, "Notes"),
                "archive_file": fn})
    return out


def name_in_title(title, name):
    """Whole-phrase match tolerant of OCR/case noise."""
    return bool(re.search(r"\b" + re.escape(name.strip()) + r"\b",
                          title, re.I))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--taught-by", required=True,
                    help="instructor name/regex matched against listing titles")
    ap.add_argument("--person-id",
                    help="graph id for the instructor (default person:<slug>)")
    ap.add_argument("--pages-dir", default=PAGES_DIR)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    title_pat = re.compile(args.taught_by, re.I)
    person_id = args.person_id or f"person:{slugify(args.taught_by)}"

    listings = extract_listings(args.pages_dir, title_pat)
    slug = slugify(args.taught_by)
    lj = f"data/reference/aikiweb_{slug}_listings.json"
    json.dump(listings, open(lj, "w"), indent=1)
    print(f"{len(listings)} '{args.taught_by}' listings -> {lj}")

    db = GraphDB(GRAPH_DB)
    # existing people for co-instructor edge detection
    people = db._get_conn().execute(
        "SELECT id, label, canonical_name FROM nodes WHERE type='Person'"
    ).fetchall()
    dojos = db._get_conn().execute(
        "SELECT id, label, canonical_name FROM nodes WHERE type='Dojo'"
    ).fetchall()

    nodes, edges = [], []
    if not db.get_node(person_id):
        nodes.append(GraphNode(
            id=person_id, type=NodeType.PERSON, label=args.taught_by,
            canonical_name=args.taught_by,
            metadata={"notes": "created by 48_ingest_aikiweb_seminars.py"},
            source_urls=[]))
        print(f"  will create {person_id}")

    for e in listings:
        h = hashlib.sha1(
            f"{e['title']}|{e['dates']}|{e['region']}".encode()).hexdigest()[:10]
        eid = f"event:aikiweb-{slugify(e['title'])}-{h}"
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=e["title"],
            canonical_name=e["title"],
            metadata={"dates": e["dates"], "region": e["region"],
                      "venue": e["venue"], "notes": e["notes"],
                      "listing_url": e["url"],
                      "source": "aikiweb_seminars_db",
                      "event_type": "seminar"},
            source_urls=[e["url"]] if e["url"] else []))
        edges.append(GraphEdge(
            src_id=person_id, rel_type=RelationType.CO_APPEARANCE,
            dst_id=eid,
            metadata={"role": "instructor", "dates": e["dates"],
                      "region": e["region"], "source_url": e["url"],
                      "source": "aikiweb_seminars_db"}))
        # co-instructors already in the graph
        for pid, label, canon in people:
            for nm in {label, canon} - {None}:
                if name_in_title(e["title"], nm) and pid != person_id:
                    edges.append(GraphEdge(
                        src_id=pid, rel_type=RelationType.CO_APPEARANCE,
                        dst_id=eid,
                        metadata={"role": "instructor",
                                  "dates": e["dates"],
                                  "source_url": e["url"],
                                  "source": "aikiweb_seminars_db"}))
                    break
        # venue -> existing dojo node
        for did, label, canon in dojos:
            for nm in {label, canon} - {None}:
                if name_in_title(e["venue"], nm):
                    edges.append(GraphEdge(
                        src_id=eid, rel_type=RelationType.LOCATED_IN,
                        dst_id=did, metadata={"source_url": e["url"]}))
                    break

    uniq = {n.id: n for n in nodes}
    nodes = list(uniq.values())
    print(f"{len(nodes)} nodes, {len(edges)} edges")
    if args.dry_run:
        for e in edges:
            print("  ", e.src_id, f"-[{e.rel_type.value}]->", e.dst_id)
        db.close()
        return
    for n in nodes:
        db.add_node(n)
    for e in edges:
        db.add_edge(e)
    db.close()
    print("done")


if __name__ == "__main__":
    main()
