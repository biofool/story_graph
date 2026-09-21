#!/usr/bin/env python3
"""Ingest residual findings from the issue #50 sweep.

- Ikeda's annual Kyoto International Aikido Friendship Seminar at the
  historic Butokuden (Oct 31-Nov 2, 2025; Oct 30-Nov 1, 2026), co-taught
  with Ryoichi Kinoshita — source: aikijuku.com. Earlier editions already
  in graph via AikiWeb ingest; this adds the current ones.
- Richard Moon birth year 1946 — per US copyright records on his music
  releases ("Richard Moon, 1946-", San Anselmo CA) plus LinkedIn "Jul
  1946" profile entry.

Usage:
    python scripts/51_ingest_issue50_findings.py --dry-run
    python scripts/51_ingest_issue50_findings.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

GRAPH_DB = "data/graph.db"
IKEDA = "person:hiroshi-ikeda"
MOON = "person:richard-moon-aikido"
KINO = "person:ryoichi-kinoshita"
AJK = "https://aikijuku.com/kyoto-seminar-2026/"
AJK25 = "https://aikijuku.com/kyoto-seminar-2025/"
COPYR = ("https://www.copyrightencyclopedia.com/"
         "radical-militant-vegetarians-in-naziland-against-the-odds/")

EVENTS = [
    ("event:kyoto-friendship-seminar-2025",
     "International Aikido Friendship Seminar, Kyoto Butokuden (Oct 31-Nov 2, 2025)",
     "2025-10-31",
     "Ikeda Shihan (Boulder Aikikai) + Kinoshita Shihan (Suisenkan, "
     "Osaka) + intl guests at the historic Kyoto Butokuden.",
     [AJK25]),
    ("event:kyoto-friendship-seminar-2026",
     "International Aikido Friendship Seminar, Kyoto Butokuden (Oct 30-Nov 1, 2026)",
     "2026-10-30",
     "Ikeda Shihan + Kinoshita Shihan + intl guests at the Kyoto "
     "Butokuden.",
     [AJK]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    nodes, edges = [], []

    nodes.append(GraphNode(
        id=KINO, type=NodeType.PERSON, label="Ryoichi Kinoshita",
        canonical_name="Ryoichi Kinoshita",
        metadata={"rank": "7th dan", "dojo": "Suisenkan, Osaka",
                  "notes": "trained 30 yrs under Seiseki Abe; "
                           "co-teaches Kyoto friendship seminars "
                           "with Ikeda",
                  "source": "aikijuku.com"},
        source_urls=[AJK]))
    nodes.append(GraphNode(
        id="place:kyoto-butokuden", type=NodeType.PLACE,
        label="Kyoto Butokuden", canonical_name="Kyoto Butokuden",
        metadata={"city": "Kyoto", "country": "Japan",
                  "notes": "historic Hall of Martial Virtues near "
                           "Heian Shrine"},
        source_urls=[AJK]))
    nodes.append(GraphNode(
        id="work:web-aikijuku-kyoto-issue50", type=NodeType.WORK,
        label="Aikijuku Dojo — Kyoto International Friendship Seminar pages",
        metadata={"work_type": "web_page",
                  "ingested_for": "issue 50 Ikeda Japan coverage"},
        source_urls=[AJK, AJK25]))

    for eid, label, date, desc, urls in EVENTS:
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=label, canonical_name=label,
            metadata={"start_date": date, "description": desc,
                      "event_type": "seminar",
                      "source": "web_research_issue50"},
            source_urls=urls))
        for pid in (IKEDA, KINO):
            edges.append(GraphEdge(
                src_id=pid, rel_type=RelationType.CO_APPEARANCE,
                dst_id=eid, metadata={"role": "instructor",
                                      "date": date,
                                      "source": "web_research_issue50"}))
        edges.append(GraphEdge(
            src_id=eid, rel_type=RelationType.LOCATED_IN,
            dst_id="place:kyoto-butokuden",
            metadata={"source_url": AJK}))
        edges.append(GraphEdge(
            src_id="work:web-aikijuku-kyoto-issue50",
            rel_type=RelationType.DESCRIBES, dst_id=eid,
            metadata={"source": "web_research_issue50"}))

    # Moon birth year
    nodes.append(GraphNode(
        id="work:web-copyright-moon-1946", type=NodeType.WORK,
        label="US copyright records — Richard Moon 1946- (San Anselmo music releases)",
        metadata={"work_type": "web_page",
                  "ingested_for": "issue 50 Moon birth year"},
        source_urls=[COPYR]))
    nodes.append(GraphNode(
        id="claim:moon-born-1946", type=NodeType.CLAIM,
        label="Richard Moon born 1946",
        metadata={"claim_text": "Richard Moon (aikido instructor) was "
                                "born in 1946.",
                  "claim_type": "biographical", "stance": "supporting",
                  "confidence": "medium",
                  "notes": "US copyright registrations list 'Richard "
                           "Moon, 1946-' on his San Anselmo CA music "
                           "releases (matches aikido Moon's Marin "
                           "County residence); LinkedIn profile shows "
                           "'Jul 1946'. Exact date unknown."},
        source_urls=[COPYR]))
    edges.append(GraphEdge(
        src_id="claim:moon-born-1946", rel_type=RelationType.ABOUT,
        dst_id=MOON, metadata={"source": "web_research_issue50"}))
    edges.append(GraphEdge(
        src_id="work:web-copyright-moon-1946",
        rel_type=RelationType.DESCRIBES, dst_id="claim:moon-born-1946",
        metadata={"source": "web_research_issue50"}))

    print(f"{len(nodes)} nodes, {len(edges)} edges")
    if args.dry_run:
        for n in nodes:
            print("  N", n.id)
        for e in edges:
            print("  E", e.src_id, f"-[{e.rel_type.value}]->", e.dst_id)
        return
    db = GraphDB(GRAPH_DB)
    for n in nodes:
        db.add_node(n)
    for e in edges:
        db.add_edge(e)
    db.close()
    print("done")


if __name__ == "__main__":
    main()
