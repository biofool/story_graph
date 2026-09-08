#!/usr/bin/env python3
"""
Ingest the PBS SoCal Artbound article: "Meet The New Aquarians"
by Caroline Ryder (May 7, 2012)
URL: https://www.pbssocal.org/shows/artbound/meet-the-new-aquarians

This article documents the contemporary "New Aquarians" movement — musicians,
artists, and spiritual seekers inspired by Father Yod and the Source Family —
and the cultural ripple effect of Jodi Wille's 2007 Source Family book and
2012 documentary.

Key entities/relationships established:
- The Source Family book (2007, Jodi Wille) + documentary "The Source" (2012)
- YaHoWha13 reunion (Nov 2007, Echoplex) as a pivotal psych-scene moment
- "New Aquarians" — contemporary movement of Source-inspired artists
- Aquarian naming tradition carried on by Djin Aquarian (Billy Corgan = "Shmuel",
  Guy Blakeslee = "Sir Guyser Aquarian", Derek James = "Lux Deus Aquarian",
  Sasha Vallely = "Kaleidoscopia Aquarian")
- Sky Saxon tribute show (2009, Echoplex) — first YaHoWha33 performance with
  Billy Corgan on bass
- Isis Aquarian as spiritual mother of the New Aquarian movement
- MEAR ONE graffiti artist (Father Yod stencil "Just Be Kind")
- Café Gratitude health food restaurant (Source legacy in LA food scene)
- The Source restaurant featured in Woody Allen's Annie Hall (1977)

Links to existing graph nodes:
- person-jim-baker-father-yod, person-isis-aquarian, person:djin-aquarian,
  person:electricity-aquarian, person:sky-saxon, person:jodi-wille,
  group-source-family, group:ya-ho-wa-13, group:the-source-restaurant,
  group:the-source-family-2012-documentary

Usage:
    python scripts/29_ingest_pbs_artbound_new_aquarians.py
    python scripts/29_ingest_pbs_artbound_new_aquarians.py --dry-run
"""

import argparse
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
PBS_URL = "https://www.pbssocal.org/shows/artbound/meet-the-new-aquarians"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest PBS Artbound 'Meet The New Aquarians'")
    parser.add_argument("--db", default=None, help="Path to graph.db")
    parser.add_argument("--dry-run", action="store_true", help="Print plan, no DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip graph_snapshot export")
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "data" / "graph.db"

    print("=" * 70)
    print("INGESTING PBS SOCAL ARTBOUND: 'MEET THE NEW AQUARIANS'")
    print(f"URL: {PBS_URL}")
    print("Author: Caroline Ryder | Published: 2012-05-07")
    print("=" * 70)

    if args.dry_run:
        print("\n[dry-run] Would add 1 source, ~10 new person/group/place/work nodes,")
        print("and ~20 edges linking to existing Source Family nodes. No DB writes.")
        return 0

    with GraphDB(db_path) as db:
        # 1. SourceRecord — PBS SoCal Artbound article
        print("\n[1] Adding PBS SoCal article as source...")
        pbs_source = SourceRecord(
            id="pbs-socal-artbound-new-aquarians-2012",
            url=PBS_URL,
            title="Meet The New Aquarians",
            author="Caroline Ryder",
            publish_date="2012-05-07",
            platform="pbs_socal_artbound",
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        )
        db.add_source(pbs_source)
        print(f"  ✓ Source added: {pbs_source.id}")

        # 2. New person nodes (contemporary New Aquarians + author)
        print("\n[2] Adding new person nodes...")

        caroline_ryder = GraphNode(
            id="person:caroline-ryder",
            type=NodeType.PERSON,
            label="Caroline Ryder",
            canonical_name="Caroline Ryder",
            metadata={
                "roles": ["journalist", "writer"],
                "contribution": "Author of PBS Artbound 'Meet The New Aquarians' (2012)",
                "source_article": PBS_URL,
            },
            source_urls=[PBS_URL],
        )
        db.add_node(caroline_ryder)

        guy_blakeslee = GraphNode(
            id="person:guy-blakeslee",
            type=NodeType.PERSON,
            label="Guy Blakeslee",
            canonical_name="Guy Blakeslee",
            metadata={
                "roles": ["musician", "frontman"],
                "band": "The Entrance Band",
                "aquarian_name": "Sir Guyser Aquarian",
                "contribution": "Early Source Family adopter; pivotal figure connecting "
                                "1970s Source Family to contemporary LA psych scene",
                "named_by": "Djin Aquarian",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(guy_blakeslee)

        derek_james = GraphNode(
            id="person:derek-james",
            type=NodeType.PERSON,
            label="Derek James",
            canonical_name="Derek James",
            metadata={
                "roles": ["musician", "drummer"],
                "band": "The Entrance Band",
                "aquarian_name": "Lux Deus Aquarian",
                "named_by": "Djin Aquarian",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(derek_james)

        billy_corgan = GraphNode(
            id="person:billy-corgan",
            type=NodeType.PERSON,
            label="Billy Corgan",
            canonical_name="William Patrick Corgan",
            metadata={
                "roles": ["musician", "singer-songwriter"],
                "band": "Smashing Pumpkins",
                "aquarian_name": "Shmuel",
                "named_by": "Sky Saxon and Djin Aquarian",
                "contribution": "Played bass for Djin Aquarian at Sky Saxon tribute show "
                                "(2009, Echoplex) — first YaHoWha33 performance",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(billy_corgan)

        sasha_vallely = GraphNode(
            id="person:sasha-vallely",
            type=NodeType.PERSON,
            label="Sasha Vallely",
            canonical_name="Sasha Vallely",
            metadata={
                "roles": ["musician"],
                "band": "Spindrift",
                "aquarian_name": "Kaleidoscopia Aquarian",
                "named_by": "Djin Aquarian",
                "contribution": "Organized Sky Saxon tribute event; received Aquarian name "
                                "after meeting Djin there",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(sasha_vallely)

        mear_one = GraphNode(
            id="person:mear-one",
            type=NodeType.PERSON,
            label="MEAR ONE",
            canonical_name="MEAR ONE",
            metadata={
                "roles": ["graffiti artist", "visual artist"],
                "location": "Silverlake, Los Angeles",
                "contribution": "Creating a stencil of Father Yod's face underscored with "
                                "Yod's slogan 'Just Be Kind'; fan of Isis Aquarian",
                "relationship_to_source": "Admirer of Isis Aquarian; New Aquarian",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(mear_one)

        michael_cepress = GraphNode(
            id="person:michael-cepress",
            type=NodeType.PERSON,
            label="Michael Cepress",
            canonical_name="Michael Cepress",
            metadata={
                "roles": ["clothing designer", "experimental fashion"],
                "location": "Seattle",
                "contribution": "Creating Isis-inspired looks; admirer of Source Family aesthetic",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(michael_cepress)

        devendra_banhart = GraphNode(
            id="person:devendra-banhart",
            type=NodeType.PERSON,
            label="Devendra Banhart",
            canonical_name="Devendra Banhart",
            metadata={
                "roles": ["musician"],
                "contribution": "New Aquarian; fan of Isis Aquarian and the Source book",
                "notable_encounter": "Met Isis Aquarian at Harvard and Stone venue, LA",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(devendra_banhart)

        for n in [caroline_ryder, guy_blakeslee, derek_james, billy_corgan,
                  sasha_vallely, mear_one, michael_cepress, devendra_banhart]:
            print(f"  ✓ Person added: {n.id}")

        # 3. New group / place / work nodes
        print("\n[3] Adding new group, place, and work nodes...")

        new_aquarians = GraphNode(
            id="group:new-aquarians",
            type=NodeType.GROUP,
            label="New Aquarians",
            canonical_name="New Aquarians",
            metadata={
                "group_type": "cultural_movement",
                "description": "Contemporary network of musicians, artists, designers, and "
                               "spiritual seekers inspired by the Source Family, bonded by "
                               "appreciation rather than guru-worship",
                "era": "2007-present",
                "origin": "Triggered by Jodi Wille's 2007 Source Family book",
                "traditions": ["Aquarian naming", "Source-inspired art/clothing",
                               "rock shows and gallery openings"],
                "key_figures": ["Djin Aquarian", "Isis Aquarian", "Guy Blakeslee",
                                "Billy Corgan", "MEAR ONE", "Sasha Vallely"],
                "contrast_with_original": "Postmodern, individualistic, not looking for a guru; "
                                          "connected via social media and events rather than commune",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(new_aquarians)

        entrance_band = GraphNode(
            id="group:the-entrance-band",
            type=NodeType.GROUP,
            label="The Entrance Band",
            canonical_name="The Entrance Band",
            metadata={
                "group_type": "rock_band",
                "location": "Los Angeles",
                "members": ["Guy Blakeslee (frontman)", "Derek James (drummer)"],
                "genre": "psychedelic rock",
                "source_connection": "Backed Sky Saxon at YaHoWha13 reunion show in SF",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(entrance_band)

        spindrift = GraphNode(
            id="group:spindrift",
            type=NodeType.GROUP,
            label="Spindrift",
            canonical_name="Spindrift",
            metadata={
                "group_type": "rock_band",
                "location": "Los Angeles",
                "members": ["Sasha Vallely"],
                "genre": "psychedelic rock",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(spindrift)

        yahowha33 = GraphNode(
            id="group:yahowha33",
            type=NodeType.GROUP,
            label="YaHoWha33",
            canonical_name="YaHoWha33",
            metadata={
                "group_type": "band",
                "description": "Open band made up of any YaHoWha13 fan who wants to jam "
                               "with Djin Aquarian",
                "first_performance": "Sky Saxon tribute show, 2009, Echoplex (Billy Corgan on bass)",
                "relation_to_yahowha13": "Contemporary continuation/open jam of YaHoWha13",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(yahowha33)

        smashing_pumpkins = GraphNode(
            id="group:smashing-pumpkins",
            type=NodeType.GROUP,
            label="Smashing Pumpkins",
            canonical_name="Smashing Pumpkins",
            metadata={
                "group_type": "rock_band",
                "genre": "alternative rock",
                "lead_singer": "Billy Corgan",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(smashing_pumpkins)

        cafe_gratitude = GraphNode(
            id="place:cafe-gratitude",
            type=NodeType.PLACE,
            label="Café Gratitude",
            canonical_name="Café Gratitude",
            metadata={
                "place_type": "restaurant",
                "description": "LA health food restaurant; part of the Source Family "
                               "culinary legacy (vegetarian/whole foods)",
                "source_connection": "Plans Source-themed events; Isis Aquarian expected "
                                     "to attend burger unveiling",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(cafe_gratitude)

        echoplex = GraphNode(
            id="place:echoplex",
            type=NodeType.PLACE,
            label="Echoplex",
            canonical_name="Echoplex",
            metadata={
                "place_type": "music_venue",
                "location": "Los Angeles",
                "significance": "Hosted YaHoWha13 reunion (Nov 2007) and Sky Saxon tribute "
                                "(2009) — pivotal New Aquarian gatherings",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(echoplex)

        elf_restaurant = GraphNode(
            id="place:elf-restaurant",
            type=NodeType.PLACE,
            label="Elf Restaurant",
            canonical_name="Elf",
            metadata={
                "place_type": "restaurant",
                "location": "Echo Park, Los Angeles",
                "co_owner": "Astara (Source Family devotee)",
                "significance": "Meeting place for Isis Aquarian and MEAR ONE",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(elf_restaurant)

        # Works
        source_book = GraphNode(
            id="work:the-source-family-book-2007",
            type=NodeType.WORK,
            label="The Source: The Untold Story of Father Yod, Ya Ho Wa 13 and The Source Family",
            metadata={
                "work_type": "book",
                "author": "Jodi Wille (with Isis Aquarian)",
                "publish_year": 2007,
                "publisher": "Process Media",
                "significance": "Triggered the New Aquarian movement; illustrated with "
                                "Source Family photos",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(source_book)

        source_documentary = GraphNode(
            id="work:the-source-documentary-2012",
            type=NodeType.WORK,
            label="The Source (documentary, 2012)",
            metadata={
                "work_type": "documentary_film",
                "director": "Jodi Wille and Maria Demopoulos",
                "premiered": "SXSW, March 2012",
                "significance": "Extended the New Aquarian ripple effect to a wider audience",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(source_documentary)

        annie_hall = GraphNode(
            id="work:annie-hall-1977",
            type=NodeType.WORK,
            label="Annie Hall (1977 film)",
            metadata={
                "work_type": "film",
                "director": "Woody Allen",
                "release_year": 1977,
                "source_connection": "Featured The Source restaurant on the Sunset Strip",
            },
            source_urls=[PBS_URL],
        )
        db.add_node(annie_hall)

        for n in [new_aquarians, entrance_band, spindrift, yahowha33,
                  smashing_pumpkins, cafe_gratitude, echoplex, elf_restaurant,
                  source_book, source_documentary, annie_hall]:
            print(f"  ✓ {n.type} added: {n.id}")

        # 4. Edges
        print("\n[4] Adding relationship edges...")

        edges = [
            # Author wrote the article (about the New Aquarians)
            GraphEdge(src_id="person:caroline-ryder", rel_type=RelationType.CREATED,
                      dst_id="pbs-socal-artbound-new-aquarians-2012",
                      metadata={"role": "author"}),

            # New Aquarians movement
            GraphEdge(src_id="group:new-aquarians", rel_type=RelationType.MENTIONS,
                      dst_id="group-source-family",
                      metadata={"relationship": "contemporary movement inspired by",
                                "source_verification": "PBS Artbound journalism (2012)"}),
            GraphEdge(src_id="group:new-aquarians", rel_type=RelationType.MENTIONS,
                      dst_id="work:the-source-family-book-2007",
                      metadata={"relationship": "triggered by the 2007 book"}),

            # Jodi Wille — book + documentary
            GraphEdge(src_id="person:jodi-wille", rel_type=RelationType.CREATED,
                      dst_id="work:the-source-family-book-2007",
                      metadata={"role": "author/publisher", "year": 2007}),
            GraphEdge(src_id="person:jodi-wille", rel_type=RelationType.CREATED,
                      dst_id="work:the-source-documentary-2012",
                      metadata={"role": "director (with Maria Demopoulos)", "year": 2012}),

            # Documentary links to existing
            GraphEdge(src_id="work:the-source-documentary-2012", rel_type=RelationType.ABOUT,
                      dst_id="group-source-family",
                      metadata={"subject": "Father Yod, Ya Ho Wa 13, and the Source Family"}),
            GraphEdge(src_id="work:the-source-documentary-2012", rel_type=RelationType.ABOUT,
                      dst_id="person-jim-baker-father-yod",
                      metadata={"subject": "Father Yod"}),

            # Book links
            GraphEdge(src_id="work:the-source-family-book-2007", rel_type=RelationType.ABOUT,
                      dst_id="group-source-family",
                      metadata={"subject": "Source Family history"}),
            GraphEdge(src_id="work:the-source-family-book-2007", rel_type=RelationType.ABOUT,
                      dst_id="person-jim-baker-father-yod",
                      metadata={"subject": "Father Yod"}),

            # Guy Blakeslee + Entrance Band
            GraphEdge(src_id="person:guy-blakeslee", rel_type=RelationType.MEMBER_OF,
                      dst_id="group:the-entrance-band",
                      metadata={"role": "frontman"}),
            GraphEdge(src_id="person:derek-james", rel_type=RelationType.MEMBER_OF,
                      dst_id="group:the-entrance-band",
                      metadata={"role": "drummer"}),
            GraphEdge(src_id="person:guy-blakeslee", rel_type=RelationType.MENTIONS,
                      dst_id="group:new-aquarians",
                      metadata={"relationship": "early adopter of Source Family"}),
            GraphEdge(src_id="person:guy-blakeslee", rel_type=RelationType.MENTIONS,
                      dst_id="person:djin-aquarian",
                      metadata={"relationship": "named by Djin; regular contact",
                                "aquarian_name": "Sir Guyser Aquarian"}),

            # Billy Corgan + Smashing Pumpkins
            GraphEdge(src_id="person:billy-corgan", rel_type=RelationType.MEMBER_OF,
                      dst_id="group:smashing-pumpkins",
                      metadata={"role": "lead singer"}),
            GraphEdge(src_id="person:billy-corgan", rel_type=RelationType.MENTIONS,
                      dst_id="person:djin-aquarian",
                      metadata={"relationship": "named by Sky Saxon and Djin",
                                "aquarian_name": "Shmuel"}),
            GraphEdge(src_id="person:billy-corgan", rel_type=RelationType.MENTIONS,
                      dst_id="person:sky-saxon",
                      metadata={"relationship": "played bass at Sky Saxon tribute (2009)"}),

            # YaHoWha33
            GraphEdge(src_id="group:yahowha33", rel_type=RelationType.MENTIONS,
                      dst_id="group:ya-ho-wa-13",
                      metadata={"relationship": "contemporary open-jam continuation"}),
            GraphEdge(src_id="person:billy-corgan", rel_type=RelationType.MEMBER_OF,
                      dst_id="group:yahowha33",
                      metadata={"role": "bass at first performance (2009)"}),
            GraphEdge(src_id="person:djin-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="group:yahowha33",
                      metadata={"role": "leads YaHoWha33 jams"}),

            # Sasha Vallely + Spindrift
            GraphEdge(src_id="person:sasha-vallely", rel_type=RelationType.MEMBER_OF,
                      dst_id="group:spindrift",
                      metadata={"role": "musician"}),
            GraphEdge(src_id="person:sasha-vallely", rel_type=RelationType.MENTIONS,
                      dst_id="person:djin-aquarian",
                      metadata={"relationship": "named by Djin",
                                "aquarian_name": "Kaleidoscopia Aquarian"}),

            # Djin Aquarian — naming tradition
            GraphEdge(src_id="person:djin-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="group:new-aquarians",
                      metadata={"role": "gives Aquarian names; go-to figure for contemporary musicians"}),
            GraphEdge(src_id="person:djin-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="person-jim-baker-father-yod",
                      metadata={"relationship": "carries on Father Yod's Aquarian naming tradition"}),

            # Isis Aquarian — spiritual mother of New Aquarians
            GraphEdge(src_id="person-isis-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="group:new-aquarians",
                      metadata={"role": "spiritual mother of the New Aquarian movement",
                                "activity": "spreads Father Yod's 'Just Be Kind' philosophy"}),
            GraphEdge(src_id="person-isis-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="person:mear-one",
                      metadata={"relationship": "MEAR ONE is one of Isis' biggest fans"}),
            GraphEdge(src_id="person-isis-aquarian", rel_type=RelationType.MENTIONS,
                      dst_id="person:devendra-banhart",
                      metadata={"relationship": "met at Harvard and Stone venue, LA"}),

            # MEAR ONE
            GraphEdge(src_id="person:mear-one", rel_type=RelationType.CREATED,
                      dst_id="group:new-aquarians",
                      metadata={"contribution": "Father Yod stencil 'Just Be Kind' — OBEY GIANT-style for New Aquarians"}),

            # Michael Cepress
            GraphEdge(src_id="person:michael-cepress", rel_type=RelationType.MENTIONS,
                      dst_id="person-isis-aquarian",
                      metadata={"relationship": "creating Isis-inspired clothing looks"}),

            # Places
            GraphEdge(src_id="place:echoplex", rel_type=RelationType.MENTIONS,
                      dst_id="group:ya-ho-wa-13",
                      metadata={"event": "YaHoWha13 reunion, November 2007"}),
            GraphEdge(src_id="place:echoplex", rel_type=RelationType.MENTIONS,
                      dst_id="person:sky-saxon",
                      metadata={"event": "Sky Saxon tribute show, 2009"}),
            GraphEdge(src_id="place:cafe-gratitude", rel_type=RelationType.MENTIONS,
                      dst_id="group-source-family",
                      metadata={"relationship": "culinary legacy of The Source (vegetarian/whole foods)"}),
            GraphEdge(src_id="place:elf-restaurant", rel_type=RelationType.MENTIONS,
                      dst_id="person-isis-aquarian",
                      metadata={"event": "Isis and MEAR ONE met here to discuss Father Yod stencil"}),

            # Annie Hall features The Source restaurant
            GraphEdge(src_id="work:annie-hall-1977", rel_type=RelationType.MENTIONS,
                      dst_id="group:the-source-restaurant",
                      metadata={"relationship": "film featured The Source restaurant on Sunset Strip"}),

            # PBS article mentions key entities
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="group:new-aquarians",
                      metadata={"type": "primary_subject"}),
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="person-jim-baker-father-yod",
                      metadata={"type": "subject"}),
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="person-isis-aquarian",
                      metadata={"type": "subject"}),
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="person:djin-aquarian",
                      metadata={"type": "subject"}),
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="person:sky-saxon",
                      metadata={"type": "subject"}),
            GraphEdge(src_id="pbs-socal-artbound-new-aquarians-2012",
                      rel_type=RelationType.MENTIONS,
                      dst_id="person:jodi-wille",
                      metadata={"type": "subject"}),
        ]

        for edge in edges:
            db.add_edge(edge)
            print(f"  ✓ Edge: {edge.src_id} → {edge.dst_id}")

        # 5. Export snapshot
        if not args.no_export:
            print("\n[5] Exporting graph snapshot...")
            snapshot_dir = PROJECT_ROOT / "graph_snapshot"
            counts = export_to_json(db, snapshot_dir)
            print(f"  ✓ Exported snapshot: {counts}")

    print("\n" + "=" * 70)
    print("✅ PBS ARTBOUND 'MEET THE NEW AQUARIANS' INGESTION COMPLETE")
    print("=" * 70)
    print("""
SUMMARY:
- 1 SourceRecord (PBS SoCal Artbound article, Caroline Ryder, 2012-05-07)
- 8 new Person nodes (Caroline Ryder, Guy Blakeslee, Derek James, Billy Corgan,
  Sasha Vallely, MEAR ONE, Michael Cepress, Devendra Banhart)
- 5 new Group nodes (New Aquarians, The Entrance Band, Spindrift, YaHoWha33,
  Smashing Pumpkins)
- 3 new Place nodes (Café Gratitude, Echoplex, Elf Restaurant)
- 3 new Work nodes (Source Family book 2007, The Source documentary 2012,
  Annie Hall 1977)
- ~35 edges linking new nodes to existing Source Family graph
- Links to existing: person-jim-baker-father-yod, person-isis-aquarian,
  person:djin-aquarian, person:electricity-aquarian, person:sky-saxon,
  person:jodi-wille, group-source-family, group:ya-ho-wa-13,
  group:the-source-restaurant

KEY FINDINGS:
1. The 2007 Source Family book (Jodi Wille) triggered the "New Aquarians" movement
2. YaHoWha13 reunion (Nov 2007, Echoplex) was a pivotal psych-scene moment
3. Djin Aquarian carries on Father Yod's Aquarian naming tradition (hundreds of names)
4. Isis Aquarian is the spiritual mother of the New Aquarian movement
5. The Source restaurant's legacy continues via Café Gratitude and LA food culture
6. Annie Hall (1977) featured The Source restaurant — pop-culture footprint
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
