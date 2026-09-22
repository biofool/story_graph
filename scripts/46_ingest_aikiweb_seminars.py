#!/usr/bin/env python3
"""Ingest AikiWeb seminar listings as Event nodes in the story graph.

Source: data/reference/aikiweb_ikeda_bridge_listings.json — produced by
scripts/45_aikiweb_seminars_crawl.py from aikiweb.com/seminars.

Creates:
  - person:hiroshi-ikeda (aikido shihan, Boulder Aikikai)
  - group:aikido-bridge (the Aikido Bridge friendship seminar series,
    started 2005 at Jiai Aikido, San Diego)
  - dojo:jiai-aikido, dojo:boulder-aikikai
  - event:aikiweb-* nodes for each Ikeda/bridge seminar listing
  - person:hiroshi-ikeda -[CO_APPEARANCE]-> each event (Nadeau/Lenkai
    convention: date, region, venue, source_url on the edge)
  - bridge-series events -[MEMBER_OF]-> group:aikido-bridge
  - Jiai-hosted events -[LOCATED_IN]-> dojo:jiai-aikido

Usage:
    python scripts/46_ingest_aikiweb_seminars.py --dry-run
    python scripts/46_ingest_aikiweb_seminars.py
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

LISTINGS = "data/reference/aikiweb_ikeda_bridge_listings.json"
GRAPH_DB = "data/graph.db"

BRIDGE_URL = re.compile(
    r"aikidobridge|midwestbridge|jiaiaikido|sandiegoaikido|"
    r"phillyaikidobridge|ioaikido\.com\.au", re.I)
IKEDA_ID = "person:hiroshi-ikeda"
BRIDGE_ID = "group:aikido-bridge"
JIAI_ID = "dojo:jiai-aikido"
BOULDER_ID = "dojo:boulder-aikikai"

Aikiweb = "https://www.aikiweb.com/seminars/"


def slugify(text, maxlen=80):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen].strip("-")


def event_id(e):
    h = hashlib.sha1(
        f"{e['title']}|{e['dates']}|{e['region']}".encode()).hexdigest()[:10]
    return f"event:aikiweb-{slugify(e['title'], 60)}-{h}"


def is_bridge(e):
    return bool(BRIDGE_URL.search(e.get("url") or ""))


def is_jiai(e):
    return bool(re.search(r"jiai|sandiegoaikido|aikido of san diego",
                          (e.get("venue") or "") + " " + (e.get("url") or ""), re.I))


def scaffold_nodes():
    return [
        GraphNode(id=IKEDA_ID, type=NodeType.PERSON, label="Hiroshi Ikeda",
                  canonical_name="Hiroshi Ikeda",
                  metadata={
                      "role": "aikido shihan", "rank": "8th dan",
                      "dojo": "Boulder Aikikai",
                      "notes": "Boulder Aikikai founder (1980); Saotome student; "
                               "Aikido Shimbokukai VP; founded Aikido Bridge "
                               "seminar series (2005)"},
                  source_urls=["https://www.hiroshi-ikeda.com/",
                               "https://www.aikidoshimbokukai.org/events-master/2026-midwest-bridge"]),
        GraphNode(id=BRIDGE_ID, type=NodeType.GROUP, label="Aikido Bridge",
                  canonical_name="Aikido Bridge",
                  metadata={
                      "kind": "seminar_series",
                      "founded": "2005",
                      "founded_by": "Hiroshi Ikeda",
                      "purpose": "bring together teachers and students from "
                                 "different Aikido organizations and "
                                 "backgrounds to share skills and build "
                                 "friendships",
                      "first_event": "Aikido Bridge 'Un Pont' International "
                                     "Friendship Seminar, Jiai Aikido, "
                                     "San Diego CA, 2005"},
                  source_urls=["http://aikidobridge.com/about/",
                               "https://www.hiroshi-ikeda.com/aikido-bridge"]),
        GraphNode(id=JIAI_ID, type=NodeType.DOJO, label="Jiai Aikido",
                  canonical_name="Jiai Aikido",
                  metadata={"city": "San Diego", "state": "CA",
                            "country": "USA",
                            "notes": "host dojo of the first Aikido Bridge "
                                     "seminar (2005) and the annual "
                                     "International Aikido Bridge Seminar"},
                  source_urls=["https://www.sandiegoaikido.com/2026-san-diego-bridge"]),
        GraphNode(id=BOULDER_ID, type=NodeType.DOJO, label="Boulder Aikikai",
                  canonical_name="Boulder Aikikai",
                  metadata={"city": "Boulder", "state": "CO", "country": "USA",
                            "founded": "1980",
                            "head_instructor": "Hiroshi Ikeda"},
                  source_urls=["https://www.aikidoshimbokukai.org/events-master/2026-midwest-bridge"]),
    ]


def scaffold_edges():
    return [
        GraphEdge(src_id=IKEDA_ID, rel_type=RelationType.FOUNDED,
                  dst_id=BOULDER_ID,
                  metadata={"date": "1980",
                            "source_url": "https://www.aikidoshimbokukai.org/events-master/2026-midwest-bridge"}),
        GraphEdge(src_id=IKEDA_ID, rel_type=RelationType.HEAD_INSTRUCTOR,
                  dst_id=BOULDER_ID,
                  metadata={"source_url": "https://www.aikidoshimbokukai.org/events-master/2026-midwest-bridge"}),
        GraphEdge(src_id=IKEDA_ID, rel_type=RelationType.FOUNDED,
                  dst_id=BRIDGE_ID,
                  metadata={"date": "2005",
                            "context": "started the Aikido Bridge seminar "
                                       "series with the 'Un Pont' "
                                       "International Friendship Seminar",
                            "source_url": "http://aikidobridge.com/about/"}),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    listings = json.load(open(LISTINGS))
    # keep Ikeda-titled seminars + anything on a real Bridge-series domain;
    # drop substring false-positives (e.g. cambridge-aikido.com)
    keep = [e for e in listings
            if "ikeda" in e["title"].lower() or is_bridge(e)]

    db = None if args.dry_run else GraphDB(GRAPH_DB)
    stats = {"events": 0, "co_appearance": 0, "member_of": 0, "located_in": 0}

    nodes = scaffold_nodes()
    edges = scaffold_edges()
    for e in keep:
        eid = event_id(e)
        meta = {
            "dates": e["dates"], "region": e["region"],
            "venue": e["venue"], "listing_url": e["url"],
            "source": "aikiweb_seminars_db",
        }
        if is_bridge(e):
            meta["seminar_series"] = "aikido_bridge"
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=e["title"],
            canonical_name=e["title"], metadata=meta,
            source_urls=[e["url"]] if e["url"] else []))
        stats["events"] += 1

        if "ikeda" in e["title"].lower():
            edges.append(GraphEdge(
                src_id=IKEDA_ID, rel_type=RelationType.CO_APPEARANCE,
                dst_id=eid,
                metadata={"role": "instructor", "dates": e["dates"],
                          "region": e["region"], "source_url": e["url"],
                          "source": "aikiweb_seminars_db"}))
            stats["co_appearance"] += 1
        if is_bridge(e):
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.MEMBER_OF,
                dst_id=BRIDGE_ID,
                metadata={"source_url": e["url"]}))
            stats["member_of"] += 1
        if is_jiai(e):
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.LOCATED_IN,
                dst_id=JIAI_ID,
                metadata={"source_url": e["url"]}))
            stats["located_in"] += 1

    print(f"listings in scope: {len(keep)}")
    for n in nodes[:4]:
        print(f"  scaffold node {n.id}")
    if args.dry_run:
        print(f"[dry-run] would upsert {len(nodes)} nodes, {len(edges)} edges; stats {stats}")
        return
    for n in nodes:
        db.add_node(n)
    for ed in edges:
        db.add_edge(ed)
    db.close()
    print(f"upserted {len(nodes)} nodes, {len(edges)} edges; stats {stats}")


if __name__ == "__main__":
    main()
