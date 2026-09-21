#!/usr/bin/env python3
"""Ingest Richard Moon's Europe/peace-work findings into the story graph.

Source: web research for issue #60 — Aikido Maastricht, the 2025 Riviera
Seminar (Switzerland), Awase Helsinki 2025, IMTD Lake Trails 1999 /
Bosnia YLA program, and the Cyprus CRTG corpus (Laouris bicommunal map,
Wikipedia CRTG article, Wolleh Berghof report).

Creates:
  - event:* nodes for each verified appearance
  - dojo:aikido-maastricht, group:imtd, place nodes
  - person:richard-moon-aikido -[CO_APPEARANCE]-> event edges
  - work:* source nodes -[DESCRIBES]-> event/person nodes

Usage:
    python scripts/49_ingest_moon_europe_peacework.py --dry-run
    python scripts/49_ingest_moon_europe_peacework.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, GraphNode, NodeType, RelationType

GRAPH_DB = "data/graph.db"
MOON = "person:richard-moon-aikido"
IMTD = "group:imtd"
MAASTRICHT = "dojo:aikido-maastricht"
BOSNIA_EVENT = "event:international-peace-building-project-in-bosnia"

U = {
    "imtd": "https://imtdsite.wordpress.com/about/associates/",
    "maastricht": "http://www.aikido-maastricht.nl/index.php/english",
    "blog": "http://aikido-ro.blogspot.com/2010/10/richard-moon-sensei-aikido-lessons.html",
    "yt1": "https://www.youtube.com/watch?v=MedDDBQHt6Y",
    "yt2": "https://www.youtube.com/watch?v=MYgMVm1K1Fo",
    "yt3": "https://www.youtube.com/watch?v=OI9ZS55CPdE",
    "novum": "https://www.novumexperience.com/2025/06/09/riviera-seminar-2025-the-heart-of-freedom/",
    "awase": "https://www.awase.fi/aikido/language/fi/richard-moon-6-dan-awasessa-12-6-2025",
    "nautilus": "https://nautilus.org/network/associates/richard-moon/",
    "riai": "http://www.conradedwards.net/riaiaikido/index.php/Main/RichardMoon",
    "qa": "https://quantumaikido.com/",
    "sands": "https://www.simonandschuster.com/authors/Richard-Moon/221805059",
    "li_ch": "https://www.linkedin.com/posts/richard-moon-00891714_headed-to-switzerland-to-join-patrick-daniel-activity-7335354032279982082-wEOT",
    "li_nz": "https://www.linkedin.com/posts/richard-moon-00891714_just-about-to-start-last-day-teaching-in-activity-7372723745481936896-fgKy",
    "crtg": "https://en.wikipedia.org/wiki/Cyprus_Conflict_Resolution_Trainers_Group",
    "map": "https://www.futureworlds.eu/wiki/1/d/d9/Bicom_Groups_Map_Revised2007_12_08.jpg",
    "mapdesc": "https://www.futureworlds.eu/wiki/Historical_overview_of_all_bi-communal_groups_created_and_facilitated_by_the_CRTG",
    "wolleh": "https://berghof-foundation.org/files/publications/br8e.pdf",
}

# (event_id, label, date, description, [source keys])
EVENTS = [
    ("event:imtd-lake-trails-camp-1999",
     "First IMTD Lake Trails camp — Moon teaches aikido as conflict-resolution tool (1999)",
     "1999",
     "Richard Moon joined the Institute for Multi-Track Diplomacy at the "
     "first Lake Trails camp in 1999, showing young participants how to "
     "use aikido as a conflict-resolution tool. Per IMTD associates page. "
     "This camp fed into IMTD's Youth Leadership Adventure (YLA) program "
     "in Bosnia (Peace Trails lineage).",
     ["imtd"]),
    ("event:moon-aikido-maastricht-2010",
     "Richard Moon aikido course at Aikido Maastricht, Netherlands (c. early 2010)",
     "2010-03",
     "Aikido Maastricht lists Richard Moon among hosted guest teachers "
     "(with Robert Nadeau, Kitabu Roshi, Patrick Cassidy, Miles Kessler). "
     "Three 'moonsensei in maastricht' videos on Moon's own YouTube "
     "channel ('Aiki - Energy State', 'introduction to aiki-dance', "
     "'developing awareness') uploaded Mar 11-14, 2010 — seminar was "
     "on or before that date.",
     ["maastricht", "blog", "yt1", "yt2", "yt3"]),
    ("event:riviera-seminar-2025",
     "Riviera Seminar 2025 'The Heart of Freedom' — Lake Geneva, Switzerland (Jun 2025)",
     "2025-06-07",
     "Annual Riviera Seminar (Cassidy/Kessler format) held around "
     "Pentecost on Lake Geneva between Montreux and Vevey, Switzerland. "
     "2025 teaching team: Patrick Cassidy, Roberto Martucci, Dan "
     "Messisco, Richard Moon (Miles Kessler absent). Moon posted he was "
     "'headed to Switzerland to join Patrick Daniel and Robert' Jun 2, "
     "2025.",
     ["novum", "li_ch"]),
    ("event:moon-awase-helsinki-2025",
     "Richard Moon guest sessions at Awase dojo, Helsinki (Jun 9-12, 2025)",
     "2025-06-09",
     "Moon (billed 6th dan) led separately-booked sessions at Awase, "
     "Helsinki, Jun 9-12 2025, organized by Elisabeth Lahti.",
     ["awase"]),
    ("event:moon-nz-tour-2025",
     "Richard Moon three-weekend New Zealand teaching tour (Sep 2025)",
     "2025-09",
     "Three-weekend NZ seminar tour (South Island -> Wellington -> North "
     "Island), >200 attendees across aikido classes/workshops and "
     "'Extraordinary Listening'. Moon notes '38 years since Johan Lloyd "
     "Sutton, Val, Mike Ashwell etc invited us' -> first NZ invitation "
     "~1987.",
     ["li_nz", "riai"]),
]

# source work nodes: (key, label, local archive path or None)
SOURCES = [
    ("imtd", "IMTD — Associates page (Richard Moon bio)", "data/reference/moon/imtd_associates.html"),
    ("maastricht", "Aikido Maastricht — English welcome page (hosted teachers)", "data/reference/moon/aikido_maastricht_english.html"),
    ("blog", "aikido-ro.blogspot.com — 'Richard Moon Sensei - Aikido Lessons' (Oct 2010)", "data/reference/moon/moon_maastricht_blog.html"),
    ("yt1", "YouTube — 'moonsensei in maastricht: Aiki - Energy State' (uploaded 2010-03-14)", None),
    ("yt2", "YouTube — 'moonsensei in maastricht: introduction to aiki-dance' (uploaded 2010-03-11)", None),
    ("yt3", "YouTube — 'moonsensei in maastricht: developing awareness' (uploaded 2010-03-12)", None),
    ("novum", "Novum Experience — 'Riviera Seminar 2025: the heart of Freedom'", "data/reference/moon/novum_riviera_2025.html"),
    ("awase", "Awase.fi — 'Richard Moon, 6. dan Awasessa 12.6.2025'", "data/reference/moon/awase_fi_2025.html"),
    ("nautilus", "Nautilus Institute — Richard Moon associate bio", "data/reference/moon/nautilus_moon.html"),
    ("riai", "Riai Aikido — Richard Moon bio (Cyprus/IMTD paragraph)", "data/reference/moon/riai_moon_bio.html"),
    ("qa", "Quantum Aikido — Richard Moon author bio", "data/reference/moon/quantumaikido_home.html"),
    ("sands", "Simon & Schuster — Richard Moon author page (6th Dan)", None),
    ("li_ch", "LinkedIn — Moon: 'Headed to Switzerland...' (Jun 2, 2025)", None),
    ("li_nz", "LinkedIn — Moon: 'last day teaching in New Zealand' (Sep 13, 2025)", None),
    ("crtg", "Wikipedia — Cyprus Conflict Resolution Trainers Group", "data/reference/cyprus/crtg_wikipedia_wikitext.txt"),
    ("map", "Bicommunal Groups Map (Laouris 1997, rev. 2007)", "data/reference/cyprus/Bicom_Groups_Map_Revised2007_12_08.jpg"),
    ("mapdesc", "Future Worlds wiki — historical overview of CRTG bicommunal groups", "data/reference/cyprus/futureworlds_crtg_overview.html"),
    ("wolleh", "Wolleh (2001) — Local Peace Constituencies in Cyprus, Berghof Report 8", "data/reference/cyprus/wolleh_berghof_br8e.pdf"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    nodes, edges = [], []

    nodes.append(GraphNode(
        id=IMTD, type=NodeType.GROUP, label="Institute for Multi-Track Diplomacy",
        canonical_name="Institute for Multi-Track Diplomacy",
        metadata={"group_type": "ngo", "city": "Washington, D.C.",
                  "country": "USA",
                  "notes": "private non-profit focused on conflict "
                           "management and systems change; ran the Cyprus "
                           "conflict-management project (with Fulbright "
                           "Commission / Conflict Management Group / "
                           "Harvard Negotiation Project) and the Bosnia "
                           "Youth Leadership Adventure / Peace Trails "
                           "program"},
        source_urls=[U["imtd"], U["riai"], U["nautilus"]]))
    nodes.append(GraphNode(
        id=MAASTRICHT, type=NodeType.DOJO, label="Aikido Maastricht",
        canonical_name="Aikido Maastricht",
        metadata={"city": "Maastricht", "country": "Netherlands",
                  "notes": "dojo >20 yrs old (ex-Aikidoschool Tendo); "
                           "hosts guest teachers incl. Nadeau, Moon, "
                           "Kitabu Roshi, Cassidy, Kessler",
                  "url": "http://www.aikido-maastricht.nl/"},
        source_urls=[U["maastricht"]]))
    nodes.append(GraphNode(
        id="place:lake-geneva", type=NodeType.PLACE,
        label="Lake Geneva (Montreux-Vevey)",
        canonical_name="Lake Geneva",
        metadata={"country": "Switzerland",
                  "notes": "Riviera Seminar location"},
        source_urls=[U["novum"]]))
    nodes.append(GraphNode(
        id="dojo:awase-helsinki", type=NodeType.DOJO, label="Awase",
        canonical_name="Awase",
        metadata={"city": "Helsinki", "country": "Finland",
                  "url": "https://www.awase.fi/"},
        source_urls=[U["awase"]]))

    located = {"event:moon-aikido-maastricht-2010": MAASTRICHT,
               "event:riviera-seminar-2025": "place:lake-geneva",
               "event:moon-awase-helsinki-2025": "dojo:awase-helsinki"}

    for eid, label, date, desc, keys in EVENTS:
        nodes.append(GraphNode(
            id=eid, type=NodeType.EVENT, label=label, canonical_name=label,
            metadata={"start_date": date, "description": desc,
                      "event_type": "seminar" if "seminar" in eid or
                      "maastricht" in eid or "awase" in eid or
                      "nz-tour" in eid else "peace_work",
                      "source": "web_research_issue60"},
            source_urls=[U[k] for k in keys]))
        edges.append(GraphEdge(
            src_id=MOON, rel_type=RelationType.CO_APPEARANCE, dst_id=eid,
            metadata={"role": "instructor", "date": date,
                      "source": "web_research_issue60"}))
        if eid in located:
            edges.append(GraphEdge(
                src_id=eid, rel_type=RelationType.LOCATED_IN,
                dst_id=located[eid],
                metadata={"source_url": U[keys[0]]}))

    # Lake Trails -> IMTD membership/program link + Bosnia event tie-in
    edges.append(GraphEdge(
        src_id=MOON, rel_type=RelationType.MEMBER_OF, dst_id=IMTD,
        metadata={"since": "1999",
                  "context": "joined at first Lake Trails camp; "
                             "associate/consultant",
                  "source_url": U["imtd"]}))
    edges.append(GraphEdge(
        src_id="event:imtd-lake-trails-camp-1999",
        rel_type=RelationType.MEMBER_OF, dst_id=IMTD,
        metadata={"context": "IMTD program event"}))
    edges.append(GraphEdge(
        src_id="event:imtd-lake-trails-camp-1999",
        rel_type=RelationType.PRECEDES, dst_id=BOSNIA_EVENT,
        metadata={"context": "Lake Trails 1999 -> IMTD Bosnia YLA/"
                             "Peace Trails work Moon participated in"}))
    edges.append(GraphEdge(
        src_id=MOON, rel_type=RelationType.CO_APPEARANCE,
        dst_id=BOSNIA_EVENT,
        metadata={"role": "consultant/instructor",
                  "context": "IMTD Bosnia peace-building (per IMTD, "
                             "Nautilus, Riai, Quantum Aikido bios)",
                  "source_url": U["imtd"]}))

    # source work nodes + DESCRIBES edges
    for key, label, local in SOURCES:
        wid = f"work:web-{key}-issue60"
        md = {"work_type": "web_page",
              "ingested_for": "issue 60 Moon Europe/peace-work rescan"}
        if local:
            md["local_archive"] = local
        nodes.append(GraphNode(
            id=wid, type=NodeType.WORK, label=label, canonical_name=label,
            metadata=md, source_urls=[U[key]]))

    for eid, _, _, _, keys in EVENTS:
        for k in keys:
            edges.append(GraphEdge(
                src_id=f"work:web-{k}-issue60",
                rel_type=RelationType.DESCRIBES, dst_id=eid,
                metadata={"source": "web_research_issue60"}))
    # bio pages also describe the person + cyprus/bosnia context
    for k in ("riai", "nautilus", "qa", "sands", "imtd"):
        edges.append(GraphEdge(
            src_id=f"work:web-{k}-issue60", rel_type=RelationType.DESCRIBES,
            dst_id=MOON, metadata={"source": "web_research_issue60"}))
    for k in ("crtg", "map", "mapdesc", "wolleh"):
        edges.append(GraphEdge(
            src_id=f"work:web-{k}-issue60", rel_type=RelationType.DESCRIBES,
            dst_id="group:cyprus-consortium",
            metadata={"source": "web_research_issue60"}))
    edges.append(GraphEdge(
        src_id="work:web-map-issue60", rel_type=RelationType.DESCRIBES,
        dst_id="group:cyprus-peace-training-team",
        metadata={"source": "web_research_issue60",
                  "context": "Laouris 1997 illustration of ~40 bicommunal "
                             "groups facilitated by the CRTG; fig. in "
                             "Laouris & Laouri 2008 (Wikipedia "
                             "cite_note-23)"}))

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
