#!/usr/bin/env python3
"""Ingest verified Richard Moon newspaper events into the story graph.

Source: extracted Newspapers.com articles under
data/reference/newspapers-com/articles/ (kept pages from the
Moon sweep — see scripts/44_npc_terminal_nodes_cleanup.py KEEP set).

Creates:
  - event:* nodes for each verified Moon class/demo/workshop/presentation
  - dojo:aikido-of-marin (FBN filed Feb 1985, renewed Apr 1996)
  - place:dance-palace (Point Reyes Station community venue)
  - person:richard-moon-aikido -[CO_APPEARANCE]-> event edges
  - event -[LOCATED_IN]-> place:dance-palace
  - work:npc-<page> source nodes -[DESCRIBES]-> event/dojo nodes

Usage:
    python scripts/47_ingest_moon_newspaper_events.py --dry-run
    python scripts/47_ingest_moon_newspaper_events.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

GRAPH_DB = "data/graph.db"
MOON = "person:richard-moon-aikido"
DOJO = "dojo:aikido-of-marin"
PALACE = "place:dance-palace"

def npc_url(pid):
    return f"https://www.newspapers.com/image/{pid}/"

# (event_id, label, date, description, [source page ids])
EVENTS = [
    ("event:aikido-class-dance-palace-1980",
     "Aikido adult class at Dance Palace (Nov 24 & Dec 1, 1980)",
     "1980-11-24",
     "Adult aikido class at the Dance Palace, Point Reyes Station, "
     "10:30 a.m.-1:30 p.m., instructor Richard Moon. Point Reyes Light "
     "listing, Nov 20, 1980.",
     ["1125183831"]),
    ("event:aikido-demo-dance-palace-1983",
     "Aikido demonstration by Richard Moon, David Gamble & Sandy Jacobs (Sep 1983)",
     "1983-09-13",
     "Aikido demonstration at a Dance Palace classes showcase, "
     "Point Reyes Station. Point Reyes Light, Sep 8, 1983.",
     ["1101135895"]),
    ("event:aikido-classes-west-marin-1984",
     "Weekly aikido classes taught by Richard Moon (1984)",
     "1984-09-06",
     "Ongoing West Marin aikido classes taught by Richard Moon. "
     "Point Reyes Light class listing, Sep 6, 1984.",
     ["1100933658"]),
    ("event:aikido-dance-dance-palace-1992",
     "Aikido Dance with Richard Moon, Bun Burton, Alan Kemp & Ira Kamin (Sep 12, 1992)",
     "1992-09-12",
     "'Aikido Dance' event at the Dance Palace, Saturday Sept 12, 8 pm, "
     "with Trane Richard Moon, Bun Burton, Alan Kemp and Ira Kamin. "
     "Point Reyes Light, Sep 10, 1992.",
     ["1101035804", "1101035712"]),
    ("event:aiki-dance-workshop-1997",
     "Aiki-Dance Workshop led by Richard Moon (Apr 26, 1997)",
     "1997-04-26",
     "'Aiki-Dance Workshop — Led by Richard Moon — the funnest part of "
     "aikido and dance', Sunday April 26, 7-9 pm, Dance Palace Community "
     "Center, 503 B St., Pt. Reyes Station. Point Reyes Light notices "
     "Apr 17 & 24, 1997.",
     ["1100842220", "1100842319"]),
    ("event:aiki-dance-intro-1998",
     "Introduction to Aikido and Dance with Richard Moon (Apr 1998)",
     "1998-04-16",
     "'Aiki-Dance — Introduction to Aikido and Dance with Richard Moon'. "
     "Point Reyes Light notices, Apr 16 & 23, 1998.",
     ["1100916418", "1100916601"]),
    ("event:aikido-and-dialogue-durham-1997",
     "Aikido and Dialogue — Thorsen & Moon at 'Designing Organizations for the 21st Century' (Oct 1997)",
     "1997-10-07",
     "Chris Thorsen and Richard Moon (Performance Edge) presented "
     "'Aikido and Dialogue', an interactive session applying aikido "
     "principles to organizational learning, at the 1997 Designing "
     "Organizations for the 21st Century conference, Durham NC. "
     "The Herald-Sun program, Oct 7, 1997.",
     ["793520210", "793548759"]),
    ("event:aikido-and-dialogue-2001",
     "Aikido and Dialogue — Thorsen & Moon conference presentation (2001)",
     "2001-09-23",
     "Chris Thorsen & Richard Moon listed as presenters ('Aikido') in "
     "the conference series program. The Herald-Sun, Sep 23, 2001.",
     ["795545627"]),
]

# FBN filings -> dojo node sources (not events)
DOJO_PAGES = {
    "1100894830": "FBN 'Aikido of Marin' filed by Richard Moon, Pt Reyes Light Feb 1985",
    "1100894910": "FBN 'Aikido of Marin' filed by Richard Moon, Pt Reyes Light Feb 28 1985",
    "1100894996": "FBN 'Aikido of Marin' filing run, Pt Reyes Light Mar 1985",
    "1100894742": "Pt Reyes Light page, Feb 14 1985 (FBN cluster; article polygon unextracted)",
    "1100898652": "'Richard Moon - Aikido of Marin' donor listing, Pt Reyes Light Dec 12 1985",
    "1100943036": "FBN renewal 'Aikido of Marin', Novato Advance May 1 1996",
    "1100943153": "FBN renewal 'Aikido of Marin', Novato Advance Apr 1996",
    "1100943276": "FBN renewal 'Aikido of Marin', Novato Advance Apr 1996",
    "1100943401": "FBN renewal 'Aikido of Marin', Novato Advance Apr 1996",
}

# pages on Dance Palace events -> LOCATED_IN edge targets
PALACE_EVENTS = {
    "event:aikido-class-dance-palace-1980",
    "event:aikido-demo-dance-palace-1983",
    "event:aikido-classes-west-marin-1984",
    "event:aikido-dance-dance-palace-1992",
    "event:aiki-dance-workshop-1997",
    "event:aiki-dance-intro-1998",
}

PAGE_LABELS = {
    "1125183831": "Point Reyes Light — Page 13 — Nov 20, 1980",
    "1101135895": "Point Reyes Light — Page 9 — Sep 8, 1983",
    "1100933658": "Point Reyes Light — Page 14 — Sep 6, 1984",
    "1100894830": "Point Reyes Light — Feb/Mar 1985 (FBN)",
    "1100894910": "Point Reyes Light — Page 16 — Feb 28, 1985 (FBN)",
    "1100894996": "Point Reyes Light — Mar 1985 (FBN)",
    "1100894742": "Point Reyes Light — Page 16 — Feb 14, 1985",
    "1100898652": "Point Reyes Light — Page 9 — Dec 12, 1985",
    "1101035804": "Point Reyes Light — Page 14 — Sep 10, 1992",
    "1101035712": "Point Reyes Light — Page 22 — Sep 3, 1992",
    "1100842220": "Point Reyes Light — Page 13 — Apr 17, 1997",
    "1100842319": "Point Reyes Light — Page 17 — Apr 24, 1997",
    "1100916418": "Point Reyes Light — Page 13 — Apr 16, 1998",
    "1100916601": "Point Reyes Light — Page 13 — Apr 23, 1998",
    "1100943036": "Novato Advance — Page 23 — May 1, 1996 (FBN)",
    "1100943153": "Novato Advance — Apr 1996 (FBN)",
    "1100943276": "Novato Advance — Apr 1996 (FBN)",
    "1100943401": "Novato Advance — Apr 1996 (FBN)",
    "793520210": "The Herald-Sun (Durham NC) — Page 18 — Oct 7, 1997",
    "793548759": "The Herald-Sun (Durham NC) — Page 78 — Oct 19, 1997",
    "795545627": "The Herald-Sun (Durham NC) — Page 80 — Sep 23, 2001",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    nodes, edges = [], []

    nodes.append(GraphNode(
        id=DOJO, type=NodeType.DOJO, label="Aikido of Marin",
        canonical_name="Aikido of Marin",
        metadata={"city": "Novato", "state": "CA", "country": "USA",
                  "founded": "1985",
                  "head_instructor": "Richard Moon",
                  "notes": "Fictitious business name filed by Richard Moon "
                           "Feb 1985 (Pt Reyes), renewed Apr 1996 (Novato)"},
        source_urls=[npc_url(p) for p in sorted(DOJO_PAGES)]))
    nodes.append(GraphNode(
        id=PALACE, type=NodeType.PLACE, label="Dance Palace",
        canonical_name="Dance Palace",
        metadata={"city": "Point Reyes Station", "state": "CA",
                  "country": "USA",
                  "notes": "community center, 503 B St.; recurring venue "
                           "for Richard Moon's aikido classes and "
                           "Aiki-Dance events 1980-1998"},
        source_urls=[npc_url("1100842319")]))

    for eid, label, date, desc, pages in EVENTS:
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=label,
            canonical_name=label,
            metadata={"start_date": date, "description": desc,
                      "event_type": "seminar",
                      "source": "newspapers_com"},
            source_urls=[npc_url(p) for p in pages]))
        edges.append(GraphEdge(
            src_id=MOON, rel_type=RelationType.CO_APPEARANCE, dst_id=eid,
            metadata={"role": "instructor", "date": date,
                      "source": "newspapers_com",
                      "source_url": npc_url(pages[0])}))
        if eid in PALACE_EVENTS:
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.LOCATED_IN, dst_id=PALACE,
                metadata={"source_url": npc_url(pages[0])}))
        for p in pages:
            nodes.append(GraphNode(
                id=f"work:npc-{p}", type=NodeType.WORK,
                label=PAGE_LABELS.get(p, f"newspapers.com page {p}"),
                metadata={"work_type": "newspaper_page"},
                source_urls=[npc_url(p)]))
            edges.append(GraphEdge(
                src_id=f"work:npc-{p}", rel_type=RelationType.DESCRIBES,
                dst_id=eid, metadata={"source": "newspapers_com"}))

    # dojo source pages + founding
    for p, note in DOJO_PAGES.items():
        nodes.append(GraphNode(
            id=f"work:npc-{p}", type=NodeType.WORK,
            label=PAGE_LABELS.get(p, f"newspapers.com page {p}"),
            metadata={"work_type": "newspaper_page", "notes": note},
            source_urls=[npc_url(p)]))
        edges.append(GraphEdge(
            src_id=f"work:npc-{p}", rel_type=RelationType.DESCRIBES,
            dst_id=DOJO, metadata={"source": "newspapers_com"}))
    edges.append(GraphEdge(
        src_id=MOON, rel_type=RelationType.FOUNDED, dst_id=DOJO,
        metadata={"date": "1985", "source": "newspapers_com",
                  "context": "filed fictitious business name 'Aikido of "
                             "Marin', Feb 1985"}))
    edges.append(GraphEdge(
        src_id=MOON, rel_type=RelationType.HEAD_INSTRUCTOR, dst_id=DOJO,
        metadata={"source": "newspapers_com"}))

    # dedupe nodes by id
    uniq = {}
    for n in nodes:
        if n.id in uniq:
            ex = uniq[n.id]
            ex.source_urls = sorted(set(ex.source_urls + n.source_urls))
            ex.metadata = {**n.metadata, **ex.metadata}
        else:
            uniq[n.id] = n
    nodes = list(uniq.values())

    print(f"{len(nodes)} nodes, {len(edges)} edges "
          f"({'would upsert' if args.dry_run else 'upserting'})")
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
