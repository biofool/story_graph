#!/usr/bin/env python3
"""
Ingest archived moonsic.com pages from the Wayback Machine into the story_graph.

moonsic.com was Richard Moon's music website. It 301-redirected to
extraordinarylistening.com/moonsic/ from ~2012 onward. The Wayback Machine
captured the site under both URLs. This script ingests the archived HTML
pages as SourceRecords + Work nodes, creates Person/Group nodes for the
artists and linked sites, and wires up MENTIONS / CONTAINS edges.

Pages ingested:
  - Homepage (2007 capture from moonsic.com)
  - about.html ("About Moonsic.com")
  - links.html ("Links We Like" — links to Open Mind Adventures, Quantum Edge)
  - contact.html (contact info: moon@moonsic.com, 75 Los Piños Rd, Nicasio CA)
  - rmoon/moonindex.html (R. Moon artist page — "Moon Tunes", "Moon Rocks")
  - liko/likoindex.html (Liko Martin artist page)
  - lesser/lesserindex.html (Eugene Lesser artist page)
  - jook/jook.html (The New Improved Jook Savages)
  - nn/nn.html (The New Improved Night Nurses)

Usage:
    python scripts/12_ingest_moonsic.py
    python scripts/12_ingest_moonsic.py --dry-run
    python scripts/12_ingest_moonsic.py --db data/graph.db
"""

import argparse
import hashlib
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json
from src.storage.models import (
    BiasHint,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Page data --------------------------------------------------------------
#
# Each entry: (source_id, wayback_url, original_url, title, raw_text, metadata)
# The raw_text is extracted from the archived HTML (visible text only).

PAGES = [
    {
        "source_id": "moonsic:home",
        "wayback_url": "https://web.archive.org/web/20070630014449/http://moonsic.com/",
        "original_url": "http://moonsic.com/",
        "title": "Moonsic — Homepage",
        "capture_date": "2007-06-30",
        "raw_text": (
            "Moonsic\n\n"
            "About | Links | Contact\n\n"
            "Keep the music flowin' — Donate to moonsic.com\n\n"
            "For More about O'Sensei's Process or other Aikido videos, please visit: "
            "Moonsensei.com\n\n"
            "Liko Martin — \"Liko Martin Right Now\" / \"Surfin' Bay Blues\"\n"
            "Eugene Lesser — The man, the myth, the poet\n"
            "R. Moon — Moon Music\n"
            "The New Improved Night Nurses\n"
            "The New Improved Jook Savages"
        ),
        "metadata": {
            "work_type": "website_homepage",
            "site": "moonsic.com",
            "capture_date": "2007-06-30",
            "note": "Richard Moon's music website. Linked to moonsensei.com for Aikido videos. "
                    "Featured artists: Liko Martin, Eugene Lesser, R. Moon, Night Nurses, Jook Savages.",
        },
        "mentions": [
            ("person:richard-moon-aikido", "R. Moon", "rmoon/moonindex.html"),
            ("person:liko-martin", "Liko Martin", "liko/likoindex.html"),
            ("person:eugene-lesser", "Eugene Lesser", "lesser/lesserindex.html"),
            ("group:new-improved-night-nurses", "The New Improved Night Nurses", "nn/nn.html"),
            ("group:new-improved-jook-savages", "The New Improved Jook Savages", "jook/jook.html"),
            ("group:moonsensei-com", "Moonsensei.com", None),
        ],
    },
    {
        "source_id": "moonsic:about",
        "wayback_url": "https://web.archive.org/web/20160518052810/http://extraordinarylistening.com:80/moonsic/about.html",
        "original_url": "http://moonsic.com/about.html",
        "title": "About Moonsic.com",
        "capture_date": "2016-05-18",
        "raw_text": (
            "About Moonsic.com\n"
            "Musical Streams of Conciousness\n\n"
            "These songs are resonant of mantras heard in the caves of Tibet. "
            "They produce a state of human consciousness that aligns itself with "
            "the universal intelligence, a state of awareness that governs itself. "
            "A state where self control is fostered by an inner wisdom, common sense "
            "and harmonious movement with the universe."
        ),
        "metadata": {
            "work_type": "web_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "note": "Describes moonsic.com music as mantra-like, fostering self-control "
                    "and harmonious movement with the universe.",
        },
        "mentions": [],
    },
    {
        "source_id": "moonsic:links",
        "wayback_url": "https://web.archive.org/web/20160518052752/http://extraordinarylistening.com:80/moonsic/links.html",
        "original_url": "http://moonsic.com/links.html",
        "title": "Links We Like",
        "capture_date": "2016-05-18",
        "raw_text": (
            "Links We Like\n\n"
            "Open Mind Adventures — http://openmindadventures.com/\n"
            "Quantum Edge — http://www.quantumedge.org/"
        ),
        "metadata": {
            "work_type": "web_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "note": "Links page with two recommended sites: Open Mind Adventures and Quantum Edge.",
        },
        "mentions": [
            ("group:open-mind-adventures", "Open Mind Adventures", None),
            ("group:quantum-edge", "Quantum Edge", None),
        ],
    },
    {
        "source_id": "moonsic:contact",
        "wayback_url": "https://web.archive.org/web/20160518052736/http://extraordinarylistening.com:80/moonsic/contact.html",
        "original_url": "http://moonsic.com/contact.html",
        "title": "Moonsic — Contact",
        "capture_date": "2016-05-18",
        "raw_text": (
            "Contact\n\n"
            "Email: moon@moonsic.com\n"
            "Snail Mail: 75 Los Piños Rd., Nicasio CA 94946"
        ),
        "metadata": {
            "work_type": "web_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "email": "moon@moonsic.com",
            "postal_address": "75 Los Piños Rd., Nicasio CA 94946",
            "note": "Contact page for moonsic.com. Email moon@moonsic.com, "
                    "postal address 75 Los Piños Rd, Nicasio CA 94946.",
        },
        "mentions": [
            ("person:richard-moon-aikido", "moon@moonsic.com", None),
        ],
    },
    {
        "source_id": "moonsic:rmoon",
        "wayback_url": "https://web.archive.org/web/20160518052827/http://extraordinarylistening.com:80/moonsic/rmoon/moonindex.html",
        "original_url": "http://moonsic.com/rmoon/moonindex.html",
        "title": "R. Moon — Moon Music",
        "capture_date": "2016-05-18",
        "raw_text": (
            "R. Moon — Music for the masses\n\n"
            "Moon Tunes\n"
            "Moon Rocks"
        ),
        "metadata": {
            "work_type": "artist_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "artist": "R. Moon",
            "albums": ["Moon Tunes", "Moon Rocks"],
            "note": "Richard Moon's artist page on moonsic.com. Two albums: Moon Tunes, Moon Rocks.",
        },
        "mentions": [
            ("person:richard-moon-aikido", "R. Moon", None),
        ],
    },
    {
        "source_id": "moonsic:liko",
        "wayback_url": "https://web.archive.org/web/20160518052748/http://extraordinarylistening.com:80/moonsic/liko/likoindex.html",
        "original_url": "http://moonsic.com/liko/likoindex.html",
        "title": "Liko Martin — A sleeping volcano awakens",
        "capture_date": "2016-05-18",
        "raw_text": (
            "Liko Martin\n"
            "A sleeping volcano awakens\n\n"
            "Liko Martin Right Now\n"
            "Surfin' Bay Blues (likomartin.com)\n"
            "more to come"
        ),
        "metadata": {
            "work_type": "artist_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "artist": "Liko Martin",
            "albums": ["Liko Martin Right Now", "Surfin' Bay Blues"],
            "external_link": "http://likomartin.com",
            "note": "Liko Martin's artist page on moonsic.com. Links to likomartin.com.",
        },
        "mentions": [
            ("person:liko-martin", "Liko Martin", None),
        ],
    },
    {
        "source_id": "moonsic:lesser",
        "wayback_url": "https://web.archive.org/web/20160518052822/http://extraordinarylistening.com:80/moonsic/lesser/lesserindex.html",
        "original_url": "http://moonsic.com/lesser/lesserindex.html",
        "title": "Eugene Lesser — A Man, A Plan, A Canal, Panama",
        "capture_date": "2016-05-18",
        "raw_text": (
            "Eugene Lesser\n"
            "A Man, A Plan, A Canal, Panama\n\n"
            "More Lesser\n"
            "The Greater Lesser"
        ),
        "metadata": {
            "work_type": "artist_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "artist": "Eugene Lesser",
            "albums": ["More Lesser", "The Greater Lesser"],
            "note": "Eugene Lesser's artist page on moonsic.com. Described as 'The man, the myth, the poet'.",
        },
        "mentions": [
            ("person:eugene-lesser", "Eugene Lesser", None),
        ],
    },
    {
        "source_id": "moonsic:jook",
        "wayback_url": "https://web.archive.org/web/20160518052742/http://extraordinarylistening.com:80/moonsic/jook/jook.html",
        "original_url": "http://moonsic.com/jook/jook.html",
        "title": "The New Improved Jook Savages Are Coming",
        "capture_date": "2016-05-18",
        "raw_text": (
            "The New Improved Jook Savages Are Coming\n\n"
            "Songs (commented out in source, not displayed):\n"
            "Ain't It Good, Sukiyaki, Legalize It, Sat Nam, The Moon Song, "
            "You Were the One, I Won't Stop, Ahamkara, I Want You To Love Me, "
            "The Nighttime, Sometimes, Comes & Goes"
        ),
        "metadata": {
            "work_type": "artist_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "artist": "The New Improved Jook Savages",
            "songs": [
                "Ain't It Good", "Sukiyaki", "Legalize It", "Sat Nam",
                "The Moon Song", "You Were the One", "I Won't Stop",
                "Ahamkara", "I Want You To Love Me", "The Nighttime",
                "Sometimes", "Comes & Goes",
            ],
            "note": "The New Improved Jook Savages band page. Song list was in HTML comments "
                    "(not visible on page). Songs include Sat Nam and Ahamkara — "
                    "Sikh/Sanskrit spiritual terms consistent with the Aikido/yoga context.",
        },
        "mentions": [
            ("group:new-improved-jook-savages", "The New Improved Jook Savages", None),
        ],
    },
    {
        "source_id": "moonsic:nn",
        "wayback_url": "https://web.archive.org/web/20160518052757/http://extraordinarylistening.com:80/moonsic/nn/nn.html",
        "original_url": "http://moonsic.com/nn/nn.html",
        "title": "The New Improved Night Nurses",
        "capture_date": "2016-05-18",
        "raw_text": (
            "The New Improved Night Nurses\n\n"
            "Songs (commented out in source, not displayed):\n"
            "Ain't It Good, Sukiyaki, Legalize It, Sat Nam, The Moon Song, "
            "You Were the One, I Won't Stop, Ahamkara, I Want You To Love Me, "
            "The Nighttime, Sometimes, Comes & Goes"
        ),
        "metadata": {
            "work_type": "artist_page",
            "site": "moonsic.com",
            "capture_date": "2016-05-18",
            "artist": "The New Improved Night Nurses",
            "songs": [
                "Ain't It Good", "Sukiyaki", "Legalize It", "Sat Nam",
                "The Moon Song", "You Were the One", "I Won't Stop",
                "Ahamkara", "I Want You To Love Me", "The Nighttime",
                "Sometimes", "Comes & Goes",
            ],
            "note": "The New Improved Night Nurses band page. Same song list as Jook Savages "
                    "(shared repertoire). Images titled 'radicalmilitant' and 'genderbias'.",
        },
        "mentions": [
            ("group:new-improved-night-nurses", "The New Improved Night Nurses", None),
        ],
    },
]

# --- Entity nodes to create -------------------------------------------------

ENTITY_NODES = [
    {
        "id": "person:liko-martin",
        "type": NodeType.PERSON,
        "label": "Liko Martin",
        "canonical_name": "Liko Martin",
        "metadata": {
            "description": "Musician featured on moonsic.com. Albums: 'Liko Martin Right Now', "
                           "'Surfin' Bay Blues'. External site: likomartin.com",
            "source": "moonsic.com",
        },
        "source_urls": ["http://moonsic.com/liko/likoindex.html"],
    },
    {
        "id": "person:eugene-lesser",
        "type": NodeType.PERSON,
        "label": "Eugene Lesser",
        "canonical_name": "Eugene Lesser",
        "metadata": {
            "description": "Poet/musician featured on moonsic.com. Described as 'The man, the "
                           "myth, the poet'. Albums: 'More Lesser', 'The Greater Lesser'.",
            "source": "moonsic.com",
        },
        "source_urls": ["http://moonsic.com/lesser/lesserindex.html"],
    },
    {
        "id": "group:new-improved-night-nurses",
        "type": NodeType.GROUP,
        "label": "The New Improved Night Nurses",
        "canonical_name": "The New Improved Night Nurses",
        "metadata": {
            "description": "Band featured on moonsic.com. Shared song repertoire with the "
                           "Jook Savages.",
            "source": "moonsic.com",
        },
        "source_urls": ["http://moonsic.com/nn/nn.html"],
    },
    {
        "id": "group:new-improved-jook-savages",
        "type": NodeType.GROUP,
        "label": "The New Improved Jook Savages",
        "canonical_name": "The New Improved Jook Savages",
        "metadata": {
            "description": "Band featured on moonsic.com. Songs include Sat Nam and Ahamkara "
                           "(Sikh/Sanskrit spiritual terms).",
            "source": "moonsic.com",
        },
        "source_urls": ["http://moonsic.com/jook/jook.html"],
    },
    {
        "id": "group:open-mind-adventures",
        "type": NodeType.GROUP,
        "label": "Open Mind Adventures",
        "canonical_name": "Open Mind Adventures",
        "metadata": {
            "description": "Organization linked from moonsic.com 'Links We Like' page. "
                           "Also hosts richard-moon and chris-thorsen pages.",
            "url": "http://openmindadventures.com/",
            "source": "moonsic.com/links.html",
        },
        "source_urls": ["http://openmindadventures.com/"],
    },
    {
        "id": "group:quantum-edge",
        "type": NodeType.GROUP,
        "label": "Quantum Edge",
        "canonical_name": "Quantum Edge",
        "metadata": {
            "description": "Organization linked from moonsic.com 'Links We Like' page.",
            "url": "http://www.quantumedge.org/",
            "source": "moonsic.com/links.html",
        },
        "source_urls": ["http://www.quantumedge.org/"],
    },
    {
        "id": "group:moonsensei-com",
        "type": NodeType.GROUP,
        "label": "Moonsensei.com",
        "canonical_name": "Moonsensei.com",
        "metadata": {
            "description": "Aikido video site linked from moonsic.com homepage. "
                           "Described as 'For More about O'Sensei's Process or other "
                           "Aikido videos'. Associated with Nadeau (button image).",
            "url": "http://www.moonsensei.com",
            "source": "moonsic.com homepage",
        },
        "source_urls": ["http://www.moonsensei.com"],
    },
]


def ingest(db: GraphDB, dry_run: bool = False) -> int:
    """Ingest all moonsic.com pages into the graph DB."""
    added = 0

    # 1. Create entity nodes (Person, Group)
    for ent in ENTITY_NODES:
        existing = db.get_node(ent["id"])
        if existing:
            print(f"  [exists] {ent['id']} — {ent['label']}")
            continue
        if dry_run:
            print(f"  [dry-run] would add node: {ent['id']} ({ent['type'].value}) — {ent['label']}")
            continue
        node = GraphNode(
            id=ent["id"],
            type=ent["type"],
            label=ent["label"],
            canonical_name=ent.get("canonical_name"),
            metadata=ent.get("metadata", {}),
            source_urls=ent.get("source_urls", []),
        )
        db.add_node(node)
        print(f"  Added node: {ent['id']} ({ent['type'].value}) — {ent['label']}")
        added += 1

    # 2. Create SourceRecords + Work nodes for each page
    for page in PAGES:
        source_id = page["source_id"]
        work_id = f"work:{source_id}"

        # Check if already ingested
        existing = db.get_node(work_id)
        if existing:
            print(f"  [exists] {work_id} — {page['title'][:60]}")
            continue

        if dry_run:
            print(f"  [dry-run] would add source+work: {source_id} — {page['title'][:60]}")
            continue

        # SourceRecord
        source = SourceRecord(
            id=source_id,
            url=page["original_url"],
            title=page["title"],
            author="Richard Moon (moonsic.com)",
            publish_date=page.get("capture_date"),
            platform="moonsic.com (Wayback Machine)",
            source_class=SourceClass.ARCHIVAL,
            bias_hint=BiasHint.NOSTALGIC,
            raw_text=page["raw_text"][:5000],
        )
        db.add_source(source)
        print(f"  Added source: {source_id}")

        # Work node
        work_node = GraphNode(
            id=work_id,
            type=NodeType.WORK,
            label=page["title"][:100],
            metadata={
                **page["metadata"],
                "wayback_url": page["wayback_url"],
                "original_url": page["original_url"],
            },
            source_urls=[page["wayback_url"], page["original_url"]],
        )
        db.add_node(work_node)
        print(f"  Added work node: {work_id} — {page['title'][:60]}")
        added += 1

        # MENTIONS edges
        for entity_id, evidence, subpath in page["mentions"]:
            edge_meta = {"evidence": evidence, "source": "moonsic.com"}
            if subpath:
                edge_meta["subpath"] = subpath
            db.add_edge(GraphEdge(
                src_id=work_id,
                rel_type=RelationType.MENTIONS,
                dst_id=entity_id,
                metadata=edge_meta,
            ))
            print(f"    MENTIONS -> {entity_id} ({evidence})")

    # 3. Link the homepage work to Richard Moon (aikido) with a MENTIONS edge
    #    The homepage references "R. Moon" and the contact email is moon@moonsic.com
    home_work_id = "work:moonsic:home"
    if not dry_run:
        db.add_edge(GraphEdge(
            src_id=home_work_id,
            rel_type=RelationType.MENTIONS,
            dst_id="person:richard-moon-aikido",
            metadata={"evidence": "R. Moon — Moon Music; site is Richard Moon's music website", "source": "moonsic.com"},
        ))
        print(f"  Linked {home_work_id} MENTIONS person:richard-moon-aikido")

        # Also link the contact page to Richard Moon
        contact_work_id = "work:moonsic:contact"
        db.add_edge(GraphEdge(
            src_id=contact_work_id,
            rel_type=RelationType.MENTIONS,
            dst_id="person:richard-moon-aikido",
            metadata={"evidence": "moon@moonsic.com — site contact email", "source": "moonsic.com"},
        ))
        print(f"  Linked {contact_work_id} MENTIONS person:richard-moon-aikido")

        # Link Open Mind Adventures to Richard Moon (existing graph already has
        # openmindadventures.com/richard-moon/ as a source)
        db.add_edge(GraphEdge(
            src_id="group:open-mind-adventures",
            rel_type=RelationType.MENTIONS,
            dst_id="person:richard-moon-aikido",
            metadata={"evidence": "openmindadventures.com hosts a Richard Moon page", "source": "moonsic.com/links.html"},
        ))
        print(f"  Linked group:open-mind-adventures MENTIONS person:richard-moon-aikido")

    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest moonsic.com Wayback pages into story_graph")
    parser.add_argument("--db", default=None, help="Path to graph.db")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip graph_snapshot export")
    args = parser.parse_args(argv)

    print("""
╔════════════════════════════════════════════════════════════════════╗
║       MOONSIC.COM WAYBACK INGESTION — story_graph                 ║
║   Richard Moon's music website (archived via Wayback Machine)     ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / "graph.db"

    if args.dry_run:
        print("[dry-run mode — no DB writes]\n")

    db = GraphDB(db_path)
    try:
        added = ingest(db, dry_run=args.dry_run)
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
