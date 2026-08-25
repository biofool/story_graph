#!/usr/bin/env python3
"""
Ingest the LAist article: "The Source, LA's Cult Favorite Vegetarian Restaurant, Returns — For One Night"
by Hadley Meares (Nov 29, 2019)

This article traces the history of Jim Baker/Father Yod, the Aware Inn, and The Source Family,
with multiple citations to LA Times articles from 1961, 1971, and 1972.

Key links established:
- Jim Baker became a follower of Yogi Bhajan (line 55)
- Baba Don (from Yogi Bhajan's ashram) connected Baker to the restaurant naming (line 65)
- Multiple LA Times articles referenced as primary sources

Distinction noted:
- CONFIRMED: LAist journalism confirms Baker-Bhajan link and Ashram connection
- UNCONFIRMED: Moon-Bhajan-Baker introduction (only in oral history, not in journalism yet)
"""

import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
    SourceRecord,
    SourceClass,
    BiasHint,
)


def main():
    db_path = Path(__file__).parent.parent / "data" / "graph.db"

    with GraphDB(db_path) as db:
        print("=" * 70)
        print("INGESTING LAIST ARTICLE & LA TIMES SOURCES")
        print("=" * 70)

        # 1. Add LAist article as a source
        print("\n[1] Adding LAist article as source...")
        laist_source = SourceRecord(
            id="laist-meares-20191129-source",
            url="https://laist.com/news/la-history/source-family-restaurant-vegetarian-dinner-gratitude-kitchen-dec-5",
            title="The Source, LA's Cult Favorite Vegetarian Restaurant, Returns — For One Night",
            author="Hadley Meares",
            publish_date="2019-11-29",
            platform="laist_nonprofit_news",
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NEUTRAL_ISH,
        )
        db.add_source(laist_source)
        print(f"  ✓ Source added: {laist_source.id}")

        # 2. Add LA Times sources (cited in the LAist article)
        print("\n[2] Adding referenced LA Times sources...")

        la_times_sources = [
            SourceRecord(
                id="la-times-winchell-1961-aware-inn",
                url="archival://los-angeles-times/1961/aware-inn-winchell",  # Unique archival reference
                title="Aware Inn Restaurant Review",
                author="Joan Winchell",
                publish_date="1961",
                platform="los_angeles_times",
                source_class=SourceClass.JOURNALISTIC,
                bias_hint=BiasHint.NEUTRAL_ISH,
            ),
            SourceRecord(
                id="la-times-1971-source-review",
                url="archival://los-angeles-times/1971/source-sunset-strip",  # Unique archival reference
                title="The Source on the Sunset Strip - Scene Report",
                author=None,  # Not specified in LAist article
                publish_date="1971",
                platform="los_angeles_times",
                source_class=SourceClass.JOURNALISTIC,
                bias_hint=BiasHint.NEUTRAL_ISH,
            ),
            SourceRecord(
                id="la-times-1972-source-family-profile",
                url="archival://los-angeles-times/1972/source-family-profile",  # Unique archival reference
                title="Source Family Profile: Diet and Daily Life",
                author=None,  # Not specified in LAist article
                publish_date="1972",
                platform="los_angeles_times",
                source_class=SourceClass.JOURNALISTIC,
                bias_hint=BiasHint.NEUTRAL_ISH,
            ),
        ]

        for source in la_times_sources:
            db.add_source(source)
            print(f"  ✓ Source added: {source.id}")

        # 3. Add/update key entities from the article
        print("\n[3] Adding entity nodes...")

        # Jim Baker / Father Yod
        baker_node = GraphNode(
            id="person-jim-baker-father-yod",
            type=NodeType.PERSON,
            label="Jim Baker / Father Yod",
            canonical_name="James Edward Baker",
            metadata={
                "aliases": ["Jim Baker", "Father Yod", "YaHoWha", "Ya Ho Wa 13"],
                "birth_year": 1922,
                "birth_place": "Ohio",
                "roles": ["restaurateur", "health_food_guru", "spiritual_leader", "cult_leader"],
                "known_for": "Founded the Aware Inn and The Source restaurants; established the Source Family commune",
                "spiritual_influences": "Paul Bragg (health food), Jack LaLanne (fitness), Yogi Bhajan (kundalini yoga)",
                "death_date": "1975-08-25",
                "death_cause": "hang-glider crash in Hawaii",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(baker_node)
        print(f"  ✓ Person added: {baker_node.id}")

        # Yogi Bhajan (as referenced in article)
        bhajan_node = GraphNode(
            id="person-yogi-bhajan",
            type=NodeType.PERSON,
            label="Yogi Bhajan",
            canonical_name="Yogi Bhajan",
            metadata={
                "roles": ["spiritual_guru", "kundalini_yoga_teacher"],
                "contribution": "Credited with bringing kundalini yoga to the west",
                "traditions_blended": ["kundalini_yoga", "astrology"],
                "presence_in_la": "Had an ashram in Los Angeles area",
                "context": "Jim Baker became a follower; Baba Don was from his ashram",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(bhajan_node)
        print(f"  ✓ Person added: {bhajan_node.id}")

        # Baba Don (intermediary)
        baba_don_node = GraphNode(
            id="person-baba-don",
            type=NodeType.PERSON,
            label="Baba Don",
            canonical_name="Baba Don",
            metadata={
                "roles": ["ashram_member", "intermediary"],
                "affiliation": "Friend from Yogi Bhajan's ashram",
                "contribution": "Helped Jim Baker name The Source restaurant",
                "context": "Connected Baker (yogi bhajan influence) to The Source project",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(baba_don_node)
        print(f"  ✓ Person added: {baba_don_node.id}")

        # Isis Aquarian (archivist/chronicler)
        isis_aquarian_node = GraphNode(
            id="person-isis-aquarian",
            type=NodeType.PERSON,
            label="Isis Aquarian",
            canonical_name="Isis Aquarian",
            metadata={
                "roles": ["Source Family member", "archivist", "historian", "photographer"],
                "contribution": "Meticulously photographed the family; keeper of Father Yod's teachings",
                "publications": "Co-author of 'The Source: The Untold Story of Father Yod, Ya Ho Wa 13 and The Source Family'",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(isis_aquarian_node)
        print(f"  ✓ Person added: {isis_aquarian_node.id}")

        # Aware Inn (restaurant)
        aware_inn_node = GraphNode(
            id="place-aware-inn",
            type=NodeType.PLACE,
            label="Aware Inn",
            canonical_name="Aware Inn",
            metadata={
                "place_type": "restaurant",
                "address": "8828 Sunset Blvd, Los Angeles",
                "opened": "1958",
                "founder": "Jim Baker and Elaine Baker",
                "description": "Health food restaurant with organic menu",
                "menu_items": ["fresh salads", "beef tartare", "fillet of sole", "cheesecake", "stuffed grape leaves"],
                "notable_features": "Upstairs private dining area with city views; fireplace",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(aware_inn_node)
        print(f"  ✓ Place added: {aware_inn_node.id}")

        # The Source (restaurant)
        source_restaurant_node = GraphNode(
            id="place-the-source",
            type=NodeType.PLACE,
            label="The Source (Restaurant)",
            canonical_name="The Source",
            metadata={
                "place_type": "restaurant",
                "address": "Sunset Boulevard at Sweetzer, Los Angeles",
                "opened": "1969-04-01",
                "closed": "1974",
                "founder": "Jim Baker",
                "previous_name": "Salad Bowl (working title)",
                "description": "Vegetarian restaurant influenced by Essene Gospel teachings",
                "menu_highlights": ["cheese and walnut loaf", "Mother's Eggplant", "fresh juices", "cheesecake", "French toast"],
                "famous_feature": "Waterfall fireplace with melting rainbow candles",
                "staff": "Young flower children in white",
                "regulars": ["Joni Mitchell", "Steve McQueen", "Warren Beatty", "Julie Christie", "Jack LaLanne"],
                "wiki_reference": "Referenced in Woody Allen's Annie Hall (1977)",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(source_restaurant_node)
        print(f"  ✓ Place added: {source_restaurant_node.id}")

        # Source Family (group)
        source_family_node = GraphNode(
            id="group-source-family",
            type=NodeType.GROUP,
            label="Source Family",
            canonical_name="Source Family",
            metadata={
                "group_type": "commune",
                "members_ca_1972": "160 people",
                "leader": "Father Yod / Jim Baker",
                "headquarters": "Chandler mansion, Los Feliz (1972-1973)",
                "activities": ["meditation", "vegetarian diet", "free love", "Eastern philosophy", "music"],
                "bands_formed": "9 psychedelic albums released during Yod's life",
                "disbanded": "After Yod's death in 1975",
                "spiritual_framework": "Essene Gospel teachings, Kundalini Yoga influence",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(source_family_node)
        print(f"  ✓ Group added: {source_family_node.id}")

        # Chandler Mansion (historical property)
        chandler_mansion_node = GraphNode(
            id="place-chandler-mansion",
            type=NodeType.PLACE,
            label="Harry Chandler Mansion",
            canonical_name="Harry Chandler Mansion, Los Feliz",
            metadata={
                "place_type": "residential_property",
                "location": "Inverness Street, Los Feliz, Los Angeles",
                "rooms": 24,
                "architecture": "Georgian-style",
                "previous_owner": "Harry Chandler (LA Times publisher)",
                "rented_by": "Source Family (1972-1973)",
                "history": "Called 'Mother House' by the Source Family",
                "residents_ca_1972": "~160 Source Family members",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(chandler_mansion_node)
        print(f"  ✓ Place added: {chandler_mansion_node.id}")

        # Harry Chandler (LA Times publisher)
        chandler_node = GraphNode(
            id="person-harry-chandler",
            type=NodeType.PERSON,
            label="Harry Chandler",
            canonical_name="Harry Chandler",
            metadata={
                "roles": ["newspaper publisher"],
                "affiliation": "Los Angeles Times",
                "historical_note": "Owned the mansion that would later house the Source Family",
            },
            source_urls=[laist_source.url],
        )
        db.add_node(chandler_node)
        print(f"  ✓ Person added: {chandler_node.id}")

        # 4. Create edges representing relationships
        print("\n[4] Adding relationship edges...")

        edges = [
            # Jim Baker relationships
            GraphEdge(
                src_id="person-jim-baker-father-yod",
                rel_type=RelationType.WORKED_AT,
                dst_id="place-aware-inn",
                metadata={"role": "founder and owner", "years": "1958-1963+"},
            ),
            GraphEdge(
                src_id="person-jim-baker-father-yod",
                rel_type=RelationType.WORKED_AT,
                dst_id="place-the-source",
                metadata={"role": "founder and owner", "years": "1969-1974"},
            ),
            GraphEdge(
                src_id="person-jim-baker-father-yod",
                rel_type=RelationType.FOUNDED,
                dst_id="group-source-family",
                metadata={"role": "founder and spiritual leader"},
            ),
            # **KEY LINK: Baker-Bhajan connection (CONFIRMED by journalism)**
            GraphEdge(
                src_id="person-jim-baker-father-yod",
                rel_type=RelationType.MENTIONS,
                dst_id="person-yogi-bhajan",
                metadata={
                    "relationship": "became a follower of",
                    "context": "spiritual influence",
                    "source_verification": "CONFIRMED via LAist journalism (line 55)",
                    "description": "Baker followed Yogi Bhajan, guru credited with bringing kundalini yoga to the west",
                },
            ),
            # Baba Don - intermediary connection
            GraphEdge(
                src_id="person-baba-don",
                rel_type=RelationType.MENTIONS,
                dst_id="person-yogi-bhajan",
                metadata={"relationship": "member of ashram"},
            ),
            GraphEdge(
                src_id="person-baba-don",
                rel_type=RelationType.MENTIONS,
                dst_id="person-jim-baker-father-yod",
                metadata={
                    "relationship": "helped name The Source restaurant",
                    "context": "Connection point between Bhajan ashram and Baker's restaurant",
                    "significance": "Named the restaurant, bridging spiritual and commercial domains",
                },
            ),
            # Source Family relationships
            GraphEdge(
                src_id="person-isis-aquarian",
                rel_type=RelationType.MEMBER_OF,
                dst_id="group-source-family",
                metadata={"role": "member, photographer, archivist"},
            ),
            GraphEdge(
                src_id="group-source-family",
                rel_type=RelationType.LIVED_AT,
                dst_id="place-chandler-mansion",
                metadata={"years": "1972-1973", "members": "~160"},
            ),
            GraphEdge(
                src_id="group-source-family",
                rel_type=RelationType.WORKED_AT,
                dst_id="place-the-source",
                metadata={"relationship": "operated the restaurant", "staff": "Members served as staff"},
            ),
            # Property history
            GraphEdge(
                src_id="person-harry-chandler",
                rel_type=RelationType.MENTIONS,
                dst_id="place-chandler-mansion",
                metadata={"relationship": "previous owner"},
            ),
            # Citation links (source to source) - using MENTIONS to indicate references/citations
            GraphEdge(
                src_id="laist-meares-20191129-source",
                rel_type=RelationType.MENTIONS,
                dst_id="la-times-winchell-1961-aware-inn",
                metadata={"type": "cites", "quote": "tiny Upstairs Aware provides a beautiful view of the city lights"},
            ),
            GraphEdge(
                src_id="laist-meares-20191129-source",
                rel_type=RelationType.MENTIONS,
                dst_id="la-times-1971-source-review",
                metadata={"type": "cites", "quote": "smiling swamis in white turbans and flowing eastern garments"},
            ),
            GraphEdge(
                src_id="laist-meares-20191129-source",
                rel_type=RelationType.MENTIONS,
                dst_id="la-times-1972-source-family-profile",
                metadata={"type": "cites", "quote": "pie of crushed nuts topped by guacamole, sliced tomatoes and alfalfa sprouts"},
            ),
        ]

        for edge in edges:
            db.add_edge(edge)
            print(f"  ✓ Edge: {edge.src_id} → {edge.dst_id}")

        print("\n" + "=" * 70)
        print("✅ INGESTION COMPLETE")
        print("=" * 70)
        print("""
KEY FINDINGS:

1. CONFIRMED LINK (via journalism):
   - Jim Baker became a follower of Yogi Bhajan ✓
   - Bhajan ashram member ("Baba Don") connected to The Source naming ✓
   - Source: LAist article by Hadley Meares, Nov 29, 2019

2. LA TIMES SOURCES REFERENCED:
   - 1961: Joan Winchell review of Aware Inn ("tiny Upstairs Aware")
   - 1971: Source review ("smiling swamis in white turbans")
   - 1972: Source Family profile ("pie of crushed nuts" diet article)

3. DISTINCTION NOTED:
   - Richard Moon-Yogi Bhajan-Jim Baker introduction: NOT mentioned in this article
   - Status: Supported by other primary sources/oral history only
   - Journalism confirms: Bhajan-Baker direct link ✓

4. ENTITIES CREATED:
   - Jim Baker / Father Yod (person)
   - Yogi Bhajan (person)
   - Baba Don (ashram intermediary)
   - Isis Aquarian (archivist)
   - Aware Inn (restaurant, 1958)
   - The Source (restaurant, 1969-1974)
   - Source Family (commune, ~160 members, 1972-1975)
   - Chandler Mansion (Los Feliz headquarters)
   - Harry Chandler (former owner, LA Times publisher)

5. NEXT STEPS:
   - Locate original LA Times articles in ProQuest/Newspapers.com
   - Cross-reference with other oral history sources
   - Track Moon-Bhajan-Baker connection through independent sources
""")


if __name__ == "__main__":
    main()
