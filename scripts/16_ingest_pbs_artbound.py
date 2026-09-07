#!/usr/bin/env python3
"""
Ingest the PBS SoCal Artbound article: "Meet The New Aquarians"
by Caroline Ryder (May 7, 2012)

URL: https://www.pbssocal.org/shows/artbound/meet-the-new-aquarians

This article documents the cultural ripple effect of the Source Family /
Father Yod on the contemporary psychedelic art and music underground — the
"New Aquarians" movement. It covers the 2007 Source Family book by Jodi
Wille, the YaHoWha13 reunion at the Echoplex, the Aquarian naming tradition
carried on by Djin Aquarian, and the influence on musicians like Billy
Corgan, Guy Blakeslee, Devendra Banhart, and artists like MEAR ONE.

Key entities and relationships established:
- Father Yod lived with 14 spiritual wives in Nichols Canyon with ~140 members
- The Source restaurant on the Sunset Strip (featured in Annie Hall)
- Father Yod died in a hang-gliding accident in Hawaii in 1975
- YaHoWha13 was the Family's psych band (Djin, Sunflower, Octavius Aquarian)
- YaHoWha13 reformed Nov 2007 at the Echoplex for the book release
- Djin Aquarian continues giving Aquarian names to new followers
- Isis Aquarian is Father Yod's former right-hand woman and record keeper
- Billy Corgan received the Aquarian name "Shmuel"
- Guy Blakeslee (Entrance Band) received "Sir Guyser Aquarian"
- Sky Saxon (Seeds) was a Source Family member, died 2009
- Father Yod prophesied a second incarnation of The Source with 4000 members

The script:
1. Creates a Work node + SourceRecord for the PBS SoCal article
2. Enriches the existing minimal work/source nodes for the KCET URL
   (the article was originally on kcet.org before the KCET/PBS SoCal merger)
3. Creates Person nodes for new entities (Caroline Ryder, Guy Blakeslee,
   Billy Corgan, Devendra Banhart, MEAR ONE, Sasha Vallely, etc.)
4. Creates Group nodes for YaHoWha13, Entrance Band, YaHoWha33, Spindrift
5. Creates Place nodes for the Echoplex, Mount Shasta
6. Extracts key claims as Claim nodes with proper attribution
7. Wires all edges (ABOUT, ASSERTED_BY, SUPPORTED_BY, CONTAINS, MENTIONS,
   DESCRIBES, MENTIONS, ALIAS_OF)
8. Exports to graph_snapshot/

Idempotent: safe to rerun (upsert semantics on nodes/sources, ignore
duplicates on edges).

Usage:
    python scripts/16_ingest_pbs_artbound.py
    python scripts/16_ingest_pbs_artbound.py --dry-run
    python scripts/16_ingest_pbs_artbound.py --db data/graph.db
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    ClaimStance,
    ClaimType,
    EvidenceMode,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

# --- Article metadata -------------------------------------------------------

ARTICLE_URL = "https://www.pbssocal.org/shows/artbound/meet-the-new-aquarians"
KCET_URL = "https://www.kcet.org/shows/artbound/meet-the-new-aquarians"
ARTICLE_TITLE = "Meet The New Aquarians"
ARTICLE_AUTHOR = "Caroline Ryder"
ARTICLE_DATE = "2012-05-07"
ARTICLE_PLATFORM = "PBS SoCal (Artbound)"
ARTICLE_CITATION = (
    f"Ryder, C. (2012). Meet The New Aquarians. Artbound, PBS SoCal. "
    f"Retrieved from {ARTICLE_URL}"
)

# Stable IDs for the new article
WORK_ID = "work:pbs-artbound-new-aquarians"
SOURCE_ID = "source:pbs-artbound-new-aquarians"

# Existing minimal work/source from prior crawl (KCET URL)
EXISTING_WORK_ID = "work:85eba8cdb9b35388"

# Author
AUTHOR_ID = "person:caroline-ryder"

# --- Existing entity IDs (from prior ingestion) -----------------------------

FATHER_YOD_ID = "person-jim-baker-father-yod"
SOURCE_FAMILY_ID = "group-source-family"
ISIS_AQUARIAN_ID = "person-isis-aquarian"
ISIS_AQUARIAN_ALT_ID = "person:isis-aquarian"
DJIN_AQUARIAN_ID = "person:djin-aquarian"
ELECTRICITY_AQUARIAN_ID = "person:electricity-aquarian"
SKY_SAXON_ID = "person:sky-saxon"
OCTAVIUS_ID = "person:octavius"
JODI_WILLE_ID = "person:jodi-wille"
YOGI_BHAJAN_ID = "person-yogi-bhajan"
THE_SOURCE_PLACE_ID = "place-the-source"
THE_SOURCE_ALT_ID = "place:the-source"
NICHOLS_CANYON_ID = "place:nichols-canyon"
SUNSET_STRIP_ID = "place:sunset-strip"
SOURCE_FAMILY_DOC_ID = "group:the-source-family-2012-documentary"

# --- New entity IDs ---------------------------------------------------------

# Persons
GUY_BLAKESLEE_ID = "person:guy-blakeslee"
BILLY_CORGAN_ID = "person:billy-corgan"
DEVENDRA_BANHART_ID = "person:devendra-banhart"
MEAR_ONE_ID = "person:mear-one"
SASHA_VALLELY_ID = "person:sasha-vallely"
DEREK_JAMES_ID = "person:derek-james"
OWLEYES_ID = "person:owleyes"
MICHAEL_CEPRESS_ID = "person:michael-cepress"
SUNFLOWER_ID = "person:sunflower-aquarian"
ASTARA_ID = "person:astara"

# Groups (bands)
YAHOWHA13_ID = "group:yahowha13"
ENTRANCE_BAND_ID = "group:the-entrance-band"
YAHOWHA33_ID = "group:yahowha33"
SPINDRIFT_ID = "group:spindrift"
SMASHING_PUMPKINS_ID = "group:smashing-pumpkins"
THE_SEEDS_ID = "group:the-seeds"

# Places
ECHOPLEX_ID = "place:echoplex"
MOUNT_SHASTA_ID = "place:mount-shasta"
HAWAII_ID = "place:hawaii"

# --- New Person nodes -------------------------------------------------------

NEW_PERSONS = [
    {
        "id": AUTHOR_ID,
        "label": "Caroline Ryder",
        "canonical_name": "Caroline Ryder",
        "metadata": {
            "roles": ["journalist", "writer"],
            "affiliation": "Artbound, PBS SoCal",
            "note": (
                "Author of 'Meet The New Aquarians' (Artbound, May 2012), "
                "documenting the cultural influence of the Source Family on "
                "the contemporary psychedelic art and music underground."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": GUY_BLAKESLEE_ID,
        "label": "Guy Blakeslee",
        "canonical_name": "Guy Blakeslee",
        "metadata": {
            "roles": ["musician", "guitarist", "vocalist"],
            "band": "The Entrance Band",
            "aquarian_name": "Sir Guyser Aquarian",
            "note": (
                "Frontman of LA rock band The Entrance Band. Early Source "
                "Family adopter in the contemporary psych scene. Given his "
                "Aquarian name by Djin Aquarian at the YaHoWha13 reunion in "
                "San Francisco. Describes the Nov 2007 Echoplex show as a "
                "'pivotal' moment in the LA psych scene."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": BILLY_CORGAN_ID,
        "label": "Billy Corgan",
        "canonical_name": "Billy Corgan",
        "metadata": {
            "roles": ["musician", "singer", "songwriter"],
            "band": "Smashing Pumpkins",
            "aquarian_name": "Shmuel",
            "note": (
                "Singer of Smashing Pumpkins. Played bass for Djin Aquarian "
                "at the Sky Saxon tribute show at the Echoplex (first "
                "performance by YaHoWha33). Given the Aquarian name 'Shmuel' "
                "by Sky Saxon and Djin Aquarian. Djin notes the name means "
                "Samuel in Hebrew — 'the prophet that anointed King David.'"
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": DEVENDRA_BANHART_ID,
        "label": "Devendra Banhart",
        "canonical_name": "Devendra Banhart",
        "metadata": {
            "roles": ["musician", "singer-songwriter"],
            "note": (
                "Freak folk musician. Named in the article as one of the free "
                "spirits influenced by the Source Family book. Met Isis "
                "Aquarian at a show at LA's Harvard and Stone venue, "
                "expressing honor at meeting her."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": MEAR_ONE_ID,
        "label": "MEAR ONE",
        "canonical_name": "MEAR ONE",
        "metadata": {
            "roles": ["graffiti artist", "painter"],
            "location": "Silverlake, Los Angeles",
            "note": (
                "LA graffiti artist known for vibrant use of color, rainbows, "
                "and psychedelic imagery. One of Isis Aquarian's biggest fans. "
                "Creating a stencil of Father Yod's face underscored with "
                "Yod's slogan 'Just Be Kind' — described as an 'OBEY GIANT' "
                "for the New Aquarian movement. Incorporates Source Family "
                "'vibrant light' inspirations into his collages."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": SASHA_VALLELY_ID,
        "label": "Sasha Vallely",
        "canonical_name": "Sasha Vallely",
        "metadata": {
            "roles": ["musician", "touring musician"],
            "band": "Spindrift",
            "aquarian_name": "Kaleidoscopia Aquarian",
            "note": (
                "Musician in LA band Spindrift. Received her Aquarian name "
                "after meeting Djin at the Sky Saxon tribute event, which she "
                "helped organize. Describes the Source as 'kind of like a "
                "cult, but now it's more spread out, and about like-minded "
                "people.' Picks and chooses elements of Source Family "
                "philosophy that fit her life as a touring musician."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": DEREK_JAMES_ID,
        "label": "Derek James",
        "canonical_name": "Derek James",
        "metadata": {
            "roles": ["musician", "drummer"],
            "band": "The Entrance Band",
            "aquarian_name": "Lux Deus Aquarian",
            "note": (
                "Drummer for The Entrance Band. Anointed with the Aquarian "
                "name 'Lux Deus Aquarian' by Djin Aquarian at the YaHoWha13 "
                "reunion in San Francisco."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": OWLEYES_ID,
        "label": "OwlEyes",
        "canonical_name": "OwlEyes",
        "metadata": {
            "roles": ["artist", "collagist"],
            "location": "Los Angeles",
            "note": (
                "LA artist known for vibrant use of color, rainbows, and "
                "psychedelic imagery. Started incorporating Source Family "
                "'vibrant light' inspirations into his collages. Appreciates "
                "the Source's 'advanced idea of the way food should be "
                "treated and used — Living food for the immortals.'"
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": MICHAEL_CEPRESS_ID,
        "label": "Michael Cepress",
        "canonical_name": "Michael Cepress",
        "metadata": {
            "roles": ["clothing designer", "experimental fashion designer"],
            "location": "Seattle",
            "note": (
                "Seattle-based experimental clothing designer. Creating "
                "Isis-inspired looks for an upcoming line. Admires the Source "
                "Family aesthetic: 'pure, natural beauty of their handmade "
                "clothes, their glorious long hair and glowing complexions.'"
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": SUNFLOWER_ID,
        "label": "Sunflower Aquarian",
        "canonical_name": "Sunflower Aquarian",
        "metadata": {
            "roles": ["musician", "Source Family member"],
            "band": "YaHoWha13",
            "note": (
                "Member of YaHoWha13, the Source Family's influential psych "
                "band. Described in the article as one of the 'longhaired, "
                "guitar-wielding and gong-smashing wizards.'"
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": ASTARA_ID,
        "label": "Astara",
        "canonical_name": "Astara",
        "metadata": {
            "roles": ["restaurant co-owner", "Source Family devotee"],
            "note": (
                "Co-owner of Elf restaurant in Echo Park. Described as "
                "another Source Family devotee. Isis Aquarian and MEAR ONE "
                "met up at Elf to discuss a Father Yod stencil project."
            ),
        },
        "source_urls": [ARTICLE_URL],
    },
]

# --- New Group nodes --------------------------------------------------------

NEW_GROUPS = [
    {
        "id": YAHOWHA13_ID,
        "label": "YaHoWha13",
        "canonical_name": "YaHoWha13",
        "metadata": {
            "group_type": "band",
            "description": (
                "The Source Family's influential psychedelic band, comprised "
                "of Djin, Sunflower, and Octavius Aquarian. Reformed in "
                "November 2007 for a concert at the Echoplex celebrating the "
                "release of the Source Family book. Their music influenced a "
                "generation of neo-hippie musicians."
            ),
            "members": ["Djin Aquarian", "Sunflower Aquarian", "Octavius Aquarian"],
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": ENTRANCE_BAND_ID,
        "label": "The Entrance Band",
        "canonical_name": "The Entrance Band",
        "metadata": {
            "group_type": "band",
            "description": (
                "LA rock band fronted by Guy Blakeslee. Backed Sky Saxon at "
                "the YaHoWha13 reunion show in San Francisco. Performed at "
                "the Echoplex book release concert in November 2007."
            ),
            "members": ["Guy Blakeslee", "Derek James"],
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": YAHOWHA33_ID,
        "label": "YaHoWha33",
        "canonical_name": "YaHoWha33",
        "metadata": {
            "group_type": "band",
            "description": (
                "An open band made up of any YaHoWha13 fan who wants to jam "
                "with Djin Aquarian. First performed at the Sky Saxon tribute "
                "show at the Echoplex, with Billy Corgan on bass."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": SPINDRIFT_ID,
        "label": "Spindrift",
        "canonical_name": "Spindrift",
        "metadata": {
            "group_type": "band",
            "description": "LA band featuring Sasha Vallely (Kaleidoscopia Aquarian).",
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": SMASHING_PUMPKINS_ID,
        "label": "Smashing Pumpkins",
        "canonical_name": "Smashing Pumpkins",
        "metadata": {
            "group_type": "band",
            "description": (
                "Rock band fronted by Billy Corgan. Corgan played bass for "
                "Djin Aquarian at the Sky Saxon tribute show."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": THE_SEEDS_ID,
        "label": "The Seeds",
        "canonical_name": "The Seeds",
        "metadata": {
            "group_type": "band",
            "description": (
                "Garage rock band led by Sky Saxon, a Source Family member "
                "in the 1970s."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
]

# --- New Place nodes --------------------------------------------------------

NEW_PLACES = [
    {
        "id": ECHOPLEX_ID,
        "label": "The Echoplex",
        "canonical_name": "The Echoplex",
        "metadata": {
            "place_type": "music_venue",
            "location": "Los Angeles, CA",
            "description": (
                "LA music venue. Site of the November 2007 YaHoWha13 reunion "
                "concert celebrating the Source Family book release, and the "
                "2009 Sky Saxon tribute show (first YaHoWha33 performance)."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": MOUNT_SHASTA_ID,
        "label": "Mount Shasta",
        "canonical_name": "Mount Shasta",
        "metadata": {
            "place_type": "location",
            "location": "Northern California",
            "description": (
                "Home of Djin Aquarian, the most active YaHoWha13 member and "
                "go-to guy for contemporary musicians interested in the Source."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
    {
        "id": HAWAII_ID,
        "label": "Hawaii",
        "canonical_name": "Hawaii",
        "metadata": {
            "place_type": "location",
            "description": (
                "Site of Father Yod's death in a hang-gliding accident in "
                "1975. Also the home of Isis Aquarian, who travels from "
                "Hawaii to LA to spread Father Yod's message."
            ),
            "source": ARTICLE_CITATION,
        },
        "source_urls": [ARTICLE_URL],
    },
]

# --- Key claims extracted from the article ----------------------------------
#
# Each claim is a structured assertion from the article, with:
# - id: stable slug
# - text: the claim text
# - claim_type: ClaimType
# - stance: ClaimStance
# - confidence: float
# - evidence_mode: secondary_report (Ryder is reporting)
# - about: list of node IDs the claim is about
# - quote: optional direct quote from the article

CLAIMS = [
    {
        "id": "claim:pbs-artbound-2012-father-yod-14-wives-nichols-canyon",
        "text": (
            "The Source Family was led by Father Yod, who lived with his 14 "
            "'spiritual wives' in a mansion in Nichols Canyon alongside "
            "around 140 other family members, operating LA's first health "
            "food restaurant 'The Source' on the Sunset Strip (featured in "
            "Woody Allen's Annie Hall), and living by 'Aquarian' principles "
            "of love, whole foods, Eastern and Western spiritual teachings, "
            "and rock 'n' roll."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [FATHER_YOD_ID, SOURCE_FAMILY_ID, NICHOLS_CANYON_ID,
                  THE_SOURCE_PLACE_ID, SUNSET_STRIP_ID],
        "quote": (
            "The Source Family was led by a bearded visionary called Father "
            "Yod, who lived with his 14 'spiritual wives' in a mansion in "
            "Nichols Canyon alongside around 140 other family members, "
            "operating LA's first health food restaurant 'The Source' on "
            "the Sunset Strip (featured in Woody Allen's Annie Hall)"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-father-yod-death-hang-gliding",
        "text": (
            "Father Yod died in a freak hang-gliding accident in Hawaii in "
            "1975. He was present at the 2007 YaHoWha13 reunion 'only in "
            "spirit.'"
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.9,
        "about": [FATHER_YOD_ID, HAWAII_ID],
        "quote": (
            "Father Yod was there too, but only in spirit--he died in a "
            "freak hang-gliding accident in Hawaii in 1975."
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-yahowha13-reunion-echoplex-2007",
        "text": (
            "YaHoWha13 reformed in November 2007 for a concert at the "
            "Echoplex celebrating the release of the Source Family book by "
            "Jodi Wille. Hundreds gathered to meet original Source Family "
            "members including book authors Isis and Electricity Aquarian, "
            "and the late Sky Saxon. Guy Blakeslee describes it as a "
            "'pivotal' moment in the LA psych scene, uniting generations of "
            "psychedelic music fans and spiritual warriors."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SUPPORTIVE,
        "confidence": 0.85,
        "about": [YAHOWHA13_ID, ECHOPLEX_ID, JODI_WILLE_ID, ISIS_AQUARIAN_ID,
                  ELECTRICITY_AQUARIAN_ID, SKY_SAXON_ID, GUY_BLAKESLEE_ID],
        "quote": (
            "That night at the Echoplex represents, as Blakeslee puts it, a "
            "'pivotal' moment in the development of the psych scene in LA"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-electricity-aquarian-star-exercise",
        "text": (
            "At the November 2007 Echoplex concert, Electricity Aquarian led "
            "the audience in a cycle of 108 breaths of fire, a Source Family "
            "ritual known as the 'star exercise.' Guy Blakeslee was impressed "
            "that so many hipsters were willing to let down their guard and "
            "do the exercise together."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [ELECTRICITY_AQUARIAN_ID, ECHOPLEX_ID, GUY_BLAKESLEE_ID],
        "quote": (
            "the white-robed, messianic figure of Electricity Aquarian led "
            "the audience in a cycle of 108 breaths of fire (a Source Family "
            "ritual known as the 'star exercise')"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-djin-aquarian-names-new-aquarians",
        "text": (
            "Djin Aquarian has given out several hundred Aquarian names over "
            "the last five or six years to an ever-growing group of young "
            "friends gravitating toward him and the Source. The names are "
            "based on love and friendship, giving recipients 'a little boost "
            "to feel like you belong to that energy movement.' Djin is the "
            "most active YaHoWha13 member and go-to guy for contemporary "
            "musicians interested in the Source."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SUPPORTIVE,
        "confidence": 0.85,
        "about": [DJIN_AQUARIAN_ID, YAHOWHA13_ID, SOURCE_FAMILY_ID],
        "quote": (
            "The names are based on love and friendship. It gives you a "
            "little boost to feel like you belong to that energy movement"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-father-yod-prophecy-4000",
        "text": (
            "Before Father Yod died, he told his 140 core followers that "
            "they should prepare for a second incarnation of The Source, "
            "made of friends and extended family, whose members would number "
            "4000."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SELF_MYTHOLOGIZING,
        "confidence": 0.7,
        "about": [FATHER_YOD_ID, SOURCE_FAMILY_ID],
        "quote": (
            "before Father Yod died, he told his 140 core followers that "
            "they should prepare for a second incarnation of The Source, "
            "made of friends and extended family, whose members would "
            "number 4000"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-isis-aquarian-right-hand-woman",
        "text": (
            "Isis Aquarian is Father Yod's former right hand woman, one of "
            "his spiritual wives, and designated record keeper of the Source "
            "Family. She makes regular trips to Los Angeles from her home in "
            "Hawaii to pursue her life's work — spreading Father Yod's "
            "'love, health, and rock n roll' message. She is a touchstone "
            "for young artists and musicians interested in the Source."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SUPPORTIVE,
        "confidence": 0.85,
        "about": [ISIS_AQUARIAN_ID, FATHER_YOD_ID, SOURCE_FAMILY_ID, HAWAII_ID],
        "quote": (
            "As Father Yod's former right hand woman, one of his spiritual "
            "wives, and designated record keeper of the Source family, Isis "
            "makes regular trips to Los Angeles from her home in Hawaii to "
            "pursue her life's work--spreading Father Yod's 'love, health, "
            "and rock n roll' message"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-billy-corgan-aquarian-name-shmuel",
        "text": (
            "Billy Corgan of Smashing Pumpkins was given the Aquarian name "
            "'Shmuel' by Sky Saxon and Djin Aquarian. When Sky Saxon passed "
            "away in 2009, Corgan played bass for Djin Aquarian at the Sky "
            "Saxon tribute show at the Echoplex — the first performance by "
            "YaHoWha33. Djin explains: 'It's Samuel in Hebrew. Samuel was "
            "the prophet that anointed King David, and King David was the "
            "songwriter.'"
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [BILLY_CORGAN_ID, SKY_SAXON_ID, DJIN_AQUARIAN_ID,
                  YAHOWHA33_ID, ECHOPLEX_ID, SMASHING_PUMPKINS_ID],
        "quote": (
            "Sky and Djin had given Billy Corgan his Aquarian name--Shmuel. "
            "'It's Samuel in Hebrew,' says Djin"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-guy-blakeslee-aquarian-name",
        "text": (
            "Guy Blakeslee was given his Aquarian name 'Sir Guyser Aquarian' "
            "by YaHoWha13's guitarist Djin Aquarian at the YaHoWha13 reunion "
            "in San Francisco. Entrance Band drummer Derek James was "
            "anointed 'Lux Deus Aquarian.'"
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [GUY_BLAKESLEE_ID, DJIN_AQUARIAN_ID, DEREK_JAMES_ID,
                  ENTRANCE_BAND_ID],
        "quote": (
            "Guy was pronounced 'Sir Guyser Aquarian', and the Entrance Band "
            "drummer Derek James was anointed 'Lux Deus Aquarian'"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-sky-saxon-source-family-member",
        "text": (
            "Sky Saxon was a garage rock legend and Source Family member in "
            "the 1970s. He was also known as Sky 'Sunlight Aquarian' Saxon. "
            "He passed away in 2009. At the YaHoWha13 reunion in San "
            "Francisco, members of the Entrance Band backed the 70-year-old "
            "Saxon."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [SKY_SAXON_ID, THE_SEEDS_ID, SOURCE_FAMILY_ID,
                  ENTRANCE_BAND_ID],
        "quote": (
            "the late Sky Saxon, garage rock legend who happened to be a "
            "Source family member in the 1970s"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-new-aquarians-postmodern-movement",
        "text": (
            "The 'New Aquarians' are a postmodern movement of interconnected "
            "individuals who aren't looking for a guru but are bonded by "
            "their common appreciation of the Source. Unlike the 1970s "
            "Source Family Aquarians who lived, ate, and slept together, the "
            "New Aquarians connect at rock shows, gallery openings, and on "
            "Facebook. Some have taken on Aquarian names and design "
            "Source-inspired clothing and Father Yod-inspired art."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SUPPORTIVE,
        "confidence": 0.8,
        "about": [SOURCE_FAMILY_ID, FATHER_YOD_ID],
        "quote": (
            "these New Aquarians are decidedly postmodern, a brightly-hued "
            "collage of inter-connected individuals who aren't looking for a "
            "guru, but are bonded by their common appreciation of the "
            "Source's radness"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-jodi-wille-book-2007-ripple-effect",
        "text": (
            "In 2007, independent publisher Jodi Wille published a book about "
            "the Source Family, triggering a chain reaction in the "
            "neo-hippie musicians, designers, writers, graffiti artists, "
            "restaurateurs, and spiritual seekers — some famous (Billy "
            "Corgan, Devendra Banhart, MEAR ONE), all free spirits. Wille's "
            "documentary 'The Source' premiered in March at SXSW."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.85,
        "about": [JODI_WILLE_ID, SOURCE_FAMILY_ID, SOURCE_FAMILY_DOC_ID,
                  BILLY_CORGAN_ID, DEVENDRA_BANHART_ID, MEAR_ONE_ID],
        "quote": (
            "when independent publisher Jodi Wille published a book about a "
            "1970s mystical tribe from L.A. called the Source Family, she "
            "had no idea the profound ripple effect it would have"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-mear-one-father-yod-stencil",
        "text": (
            "Graffiti artist MEAR ONE is creating a stencil of Father Yod's "
            "face, underscored with Yod's slogan 'Just Be Kind' — described "
            "as an 'OBEY GIANT' for the New Aquarian movement. MEAR says Isis "
            "Aquarian 'hunted me down in a spiritual sense' and her "
            "philosophy is 'like water for thirsty minds right now.'"
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.SUPPORTIVE,
        "confidence": 0.8,
        "about": [MEAR_ONE_ID, FATHER_YOD_ID, ISIS_AQUARIAN_ID],
        "quote": (
            "MEAR is making of Father Yod's face, underscored with Yod's "
            "slogan, Just Be Kind--kind of like an 'OBEY GIANT' for the New "
            "Aquarian movement"
        ),
    },
    {
        "id": "claim:pbs-artbound-2012-cafe-gratitude-source-burger",
        "text": (
            "Cafe Gratitude, arguably LA's hippest new health food "
            "restaurant, plans to come out with its own take on the 'Source "
            "burger' — one of the most popular items on the menu at the "
            "original Source restaurant. Isis Aquarian is expected to be "
            "present when they unveil the burger."
        ),
        "claim_type": ClaimType.BIOGRAPHICAL,
        "stance": ClaimStance.NEUTRAL,
        "confidence": 0.8,
        "about": [THE_SOURCE_PLACE_ID, ISIS_AQUARIAN_ID],
        "quote": (
            "Cafe Gratitude, arguably LA's hippest new health food "
            "restaurant, plans to come out with its own take on the 'Source "
            "burger'--one of the most popular items on the menu at the "
            "original Source restaurant"
        ),
    },
]


# --- MENTIONS targets (all entities the article mentions) -------------------

MENTION_TARGETS = [
    FATHER_YOD_ID,
    SOURCE_FAMILY_ID,
    ISIS_AQUARIAN_ID,
    ISIS_AQUARIAN_ALT_ID,
    DJIN_AQUARIAN_ID,
    ELECTRICITY_AQUARIAN_ID,
    SKY_SAXON_ID,
    OCTAVIUS_ID,
    SUNFLOWER_ID,
    JODI_WILLE_ID,
    YOGI_BHAJAN_ID,
    THE_SOURCE_PLACE_ID,
    THE_SOURCE_ALT_ID,
    NICHOLS_CANYON_ID,
    SUNSET_STRIP_ID,
    SOURCE_FAMILY_DOC_ID,
    AUTHOR_ID,
    GUY_BLAKESLEE_ID,
    BILLY_CORGAN_ID,
    DEVENDRA_BANHART_ID,
    MEAR_ONE_ID,
    SASHA_VALLELY_ID,
    DEREK_JAMES_ID,
    OWLEYES_ID,
    MICHAEL_CEPRESS_ID,
    ASTARA_ID,
    YAHOWHA13_ID,
    ENTRANCE_BAND_ID,
    YAHOWHA33_ID,
    SPINDRIFT_ID,
    SMASHING_PUMPKINS_ID,
    THE_SEEDS_ID,
    ECHOPLEX_ID,
    MOUNT_SHASTA_ID,
    HAWAII_ID,
]


# --- Main -------------------------------------------------------------------


def ingest(db: GraphDB, dry_run: bool = False) -> int:
    added = 0

    # 1. Create the Work node for the article
    print("  Creating Work node for the PBS SoCal article...")
    if not dry_run:
        db.add_node(GraphNode(
            id=WORK_ID,
            type=NodeType.WORK,
            label=ARTICLE_TITLE,
            canonical_name=None,
            metadata={
                "url": ARTICLE_URL,
                "platform": ARTICLE_PLATFORM,
                "work_type": "article",
                "publish_date": ARTICLE_DATE,
                "author": ARTICLE_AUTHOR,
                "citation": ARTICLE_CITATION,
                "note": (
                    "PBS SoCal Artbound article documenting the 'New "
                    "Aquarians' — the contemporary cultural influence of "
                    "the Source Family on the psychedelic art and music "
                    "underground."
                ),
            },
            source_urls=[ARTICLE_URL, KCET_URL],
        ))
        added += 1

    # Also enrich the existing minimal work node (from the KCET crawl)
    print("  Enriching existing minimal work node (KCET URL)...")
    if not dry_run:
        db.add_node(GraphNode(
            id=EXISTING_WORK_ID,
            type=NodeType.WORK,
            label=ARTICLE_TITLE,
            canonical_name=None,
            metadata={
                "url": KCET_URL,
                "platform": ARTICLE_PLATFORM,
                "work_type": "article",
                "publish_date": ARTICLE_DATE,
                "author": ARTICLE_AUTHOR,
                "citation": ARTICLE_CITATION,
                "enriched_by": "scripts/16_ingest_pbs_artbound.py",
                "note": (
                    "Originally crawled as a discovered reference from "
                    "kcet.org. Enriched with full metadata from the PBS "
                    "SoCal version (KCET merged with PBS SoCal)."
                ),
            },
            source_urls=[KCET_URL, ARTICLE_URL],
        ))

    # 2. Create the SourceRecord
    print("  Creating SourceRecord for the article...")
    if not dry_run:
        db.add_source(SourceRecord(
            id=SOURCE_ID,
            url=ARTICLE_URL,
            title=ARTICLE_TITLE,
            author=ARTICLE_AUTHOR,
            publish_date=ARTICLE_DATE,
            platform=ARTICLE_PLATFORM,
            source_class=SourceClass.JOURNALISTIC,
            bias_hint=BiasHint.NOSTALGIC,
            raw_text=(
                "In 2007, when independent publisher Jodi Wille published a "
                "book about a 1970s mystical tribe from L.A. called the "
                "Source Family, she had no idea the profound ripple effect "
                "it would have... The Source Family was led by a bearded "
                "visionary called Father Yod, who lived with his 14 "
                "spiritual wives in a mansion in Nichols Canyon alongside "
                "around 140 other family members, operating LA's first "
                "health food restaurant The Source on the Sunset Strip..."
            ),
        ))
        added += 1

    # 3. Create/enrich Person nodes
    print("  Creating/enriching Person nodes...")
    for person in NEW_PERSONS:
        existing = db.get_node(person["id"])
        if existing:
            print(f"    [exists] {person['id']} — enriching metadata")
        elif dry_run:
            print(f"    [dry-run] would add: {person['label']}")
            continue
        else:
            print(f"    Added: {person['id']} — {person['label']}")
            added += 1
        if not dry_run:
            merged_urls = sorted(set(
                (existing.source_urls if existing else []) +
                person["source_urls"]
            ))
            db.add_node(GraphNode(
                id=person["id"],
                type=NodeType.PERSON,
                label=person["label"],
                canonical_name=person["canonical_name"],
                metadata=person["metadata"],
                source_urls=merged_urls,
            ))

    # 4. Create Group nodes
    print("  Creating Group nodes...")
    for group in NEW_GROUPS:
        existing = db.get_node(group["id"])
        if existing:
            print(f"    [exists] {group['id']} — enriching metadata")
        elif dry_run:
            print(f"    [dry-run] would add: {group['label']}")
            continue
        else:
            print(f"    Added: {group['id']} — {group['label']}")
            added += 1
        if not dry_run:
            merged_urls = sorted(set(
                (existing.source_urls if existing else []) +
                group["source_urls"]
            ))
            db.add_node(GraphNode(
                id=group["id"],
                type=NodeType.GROUP,
                label=group["label"],
                canonical_name=group["canonical_name"],
                metadata=group["metadata"],
                source_urls=merged_urls,
            ))

    # 5. Create Place nodes
    print("  Creating Place nodes...")
    for place in NEW_PLACES:
        existing = db.get_node(place["id"])
        if existing:
            print(f"    [exists] {place['id']} — enriching metadata")
        elif dry_run:
            print(f"    [dry-run] would add: {place['label']}")
            continue
        else:
            print(f"    Added: {place['id']} — {place['label']}")
            added += 1
        if not dry_run:
            merged_urls = sorted(set(
                (existing.source_urls if existing else []) +
                place["source_urls"]
            ))
            db.add_node(GraphNode(
                id=place["id"],
                type=NodeType.PLACE,
                label=place["label"],
                canonical_name=place["canonical_name"],
                metadata=place["metadata"],
                source_urls=merged_urls,
            ))

    # 6. Create Claim nodes + edges
    print("  Creating Claim nodes...")
    for claim_data in CLAIMS:
        claim_id = claim_data["id"]
        existing = db.get_node(claim_id)
        if existing:
            print(f"    [exists] {claim_id}")
        elif dry_run:
            print(f"    [dry-run] would add claim: {claim_data['text'][:80]}...")
        else:
            db.add_node(GraphNode(
                id=claim_id,
                type=NodeType.CLAIM,
                label=claim_data["text"][:200],
                canonical_name=None,
                metadata={
                    "claim_text": claim_data["text"],
                    "claim_type": claim_data["claim_type"].value,
                    "stance": claim_data["stance"].value,
                    "confidence": claim_data["confidence"],
                    "evidence_mode": EvidenceMode.SECONDARY_REPORT.value,
                    "pending_independent_corroboration": False,
                    "source": ARTICLE_CITATION,
                    "quote": claim_data.get("quote", ""),
                },
                source_urls=[ARTICLE_URL],
            ))
            print(f"    Added claim: {claim_id}")
            added += 1

            # ASSERTED_BY Caroline Ryder
            db.add_edge(GraphEdge(
                src_id=claim_id,
                rel_type=RelationType.ASSERTED_BY,
                dst_id=AUTHOR_ID,
                metadata={"evidence": ARTICLE_CITATION},
            ))

            # CONTAINS — the article contains this claim
            db.add_edge(GraphEdge(
                src_id=WORK_ID,
                rel_type=RelationType.CONTAINS,
                dst_id=claim_id,
                metadata={"evidence": ARTICLE_URL},
            ))

            # ABOUT — claim is about each entity
            for about_id in claim_data["about"]:
                db.add_edge(GraphEdge(
                    src_id=claim_id,
                    rel_type=RelationType.ABOUT,
                    dst_id=about_id,
                    metadata={"evidence": ARTICLE_CITATION},
                ))

            # SUPPORTED_BY — claim is supported by the article source
            db.add_edge(GraphEdge(
                src_id=claim_id,
                rel_type=RelationType.SUPPORTED_BY,
                dst_id=WORK_ID,
                metadata={"evidence": ARTICLE_URL},
            ))

            # Link claim to the article's source record
            db.add_claim_source_link(ClaimSourceLink(
                claim_id=claim_id,
                source_id=SOURCE_ID,
            ))

    # 7. MENTIONS edges from the article work to all entities
    print("  Creating MENTIONS edges from article...")
    if not dry_run:
        for target_id in MENTION_TARGETS:
            db.add_edge(GraphEdge(
                src_id=WORK_ID,
                rel_type=RelationType.MENTIONS,
                dst_id=target_id,
                metadata={"evidence": ARTICLE_CITATION},
            ))

    # 8. DESCRIBES edges: article DESCRIBES key entities
    print("  Creating DESCRIBES edges...")
    if not dry_run:
        for target_id in [FATHER_YOD_ID, SOURCE_FAMILY_ID, ISIS_AQUARIAN_ID,
                          DJIN_AQUARIAN_ID, YAHOWHA13_ID]:
            db.add_edge(GraphEdge(
                src_id=WORK_ID,
                rel_type=RelationType.DESCRIBES,
                dst_id=target_id,
                metadata={"evidence": ARTICLE_CITATION},
            ))

    # 9. ALIAS_OF edges — link the PBS and KCET work nodes
    print("  Linking PBS and KCET work nodes (ALIAS_OF)...")
    if not dry_run:
        db.add_edge(GraphEdge(
            src_id=WORK_ID,
            rel_type=RelationType.ALIAS_OF,
            dst_id=EXISTING_WORK_ID,
            metadata={"note": "Same article, KCET merged with PBS SoCal"},
        ))

    # 10. Membership / relationship edges
    print("  Creating membership and relationship edges...")
    if not dry_run:
        membership_edges = [
            # YaHoWha13 members
            GraphEdge(src_id=DJIN_AQUARIAN_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=YAHOWHA13_ID, metadata={"role": "guitarist"}),
            GraphEdge(src_id=SUNFLOWER_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=YAHOWHA13_ID, metadata={"role": "musician"}),
            GraphEdge(src_id=OCTAVIUS_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=YAHOWHA13_ID, metadata={"role": "musician"}),
            # Entrance Band members
            GraphEdge(src_id=GUY_BLAKESLEE_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=ENTRANCE_BAND_ID,
                      metadata={"role": "frontman, guitarist, vocalist"}),
            GraphEdge(src_id=DEREK_JAMES_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=ENTRANCE_BAND_ID, metadata={"role": "drummer"}),
            # Smashing Pumpkins
            GraphEdge(src_id=BILLY_CORGAN_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SMASHING_PUMPKINS_ID,
                      metadata={"role": "singer, songwriter"}),
            # Spindrift
            GraphEdge(src_id=SASHA_VALLELY_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SPINDRIFT_ID, metadata={"role": "musician"}),
            # The Seeds
            GraphEdge(src_id=SKY_SAXON_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=THE_SEEDS_ID,
                      metadata={"role": "garage rock legend, vocalist"}),
            # Source Family members
            GraphEdge(src_id=SKY_SAXON_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SOURCE_FAMILY_ID,
                      metadata={"role": "member in the 1970s",
                                "aquarian_name": "Sunlight Aquarian"}),
            GraphEdge(src_id=ISIS_AQUARIAN_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SOURCE_FAMILY_ID,
                      metadata={"role": "right hand woman, spiritual wife, record keeper"}),
            GraphEdge(src_id=DJIN_AQUARIAN_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SOURCE_FAMILY_ID,
                      metadata={"role": "musician, YaHoWha13 guitarist"}),
            GraphEdge(src_id=ELECTRICITY_AQUARIAN_ID, rel_type=RelationType.MEMBER_OF,
                      dst_id=SOURCE_FAMILY_ID,
                      metadata={"role": "member, book co-author"}),
            # Father Yod founded the Source Family
            GraphEdge(src_id=FATHER_YOD_ID, rel_type=RelationType.FOUNDED,
                      dst_id=SOURCE_FAMILY_ID,
                      metadata={"role": "founder and spiritual leader"}),
            # Father Yod lived at Nichols Canyon
            GraphEdge(src_id=FATHER_YOD_ID, rel_type=RelationType.LIVED_AT,
                      dst_id=NICHOLS_CANYON_ID,
                      metadata={"note": "mansion in Nichols Canyon with 14 spiritual wives and ~140 members"}),
            # Source Family lived at Nichols Canyon
            GraphEdge(src_id=SOURCE_FAMILY_ID, rel_type=RelationType.LIVED_AT,
                      dst_id=NICHOLS_CANYON_ID,
                      metadata={"members": "~140", "note": "mansion in Nichols Canyon"}),
            # Source Family operated The Source restaurant
            GraphEdge(src_id=SOURCE_FAMILY_ID, rel_type=RelationType.WORKED_AT,
                      dst_id=THE_SOURCE_PLACE_ID,
                      metadata={"relationship": "operated LA's first health food restaurant"}),
            # The Source is on the Sunset Strip
            GraphEdge(src_id=THE_SOURCE_PLACE_ID, rel_type=RelationType.LOCATED_IN,
                      dst_id=SUNSET_STRIP_ID,
                      metadata={"note": "The Source restaurant on the Sunset Strip"}),
            # Djin Aquarian lives at Mount Shasta
            GraphEdge(src_id=DJIN_AQUARIAN_ID, rel_type=RelationType.LIVED_AT,
                      dst_id=MOUNT_SHASTA_ID,
                      metadata={"note": "home of Djin Aquarian"}),
            # Isis Aquarian lives in Hawaii
            GraphEdge(src_id=ISIS_AQUARIAN_ID, rel_type=RelationType.LIVED_AT,
                      dst_id=HAWAII_ID,
                      metadata={"note": "home of Isis Aquarian, travels to LA regularly"}),
            # Father Yod died in Hawaii
            GraphEdge(src_id=FATHER_YOD_ID, rel_type=RelationType.MENTIONS,
                      dst_id=HAWAII_ID,
                      metadata={"relationship": "died in hang-gliding accident, 1975"}),
        ]
        for edge in membership_edges:
            db.add_edge(edge)

    # 11. Link the existing documentary group to Jodi Wille
    print("  Creating additional relationship edges...")
    if not dry_run:
        extra_edges = [
            # Jodi Wille and the documentary
            GraphEdge(src_id=JODI_WILLE_ID, rel_type=RelationType.CREATED,
                      dst_id=SOURCE_FAMILY_DOC_ID,
                      metadata={"role": "director/producer",
                                "note": "The Source (2012 documentary)"}),
            # YaHoWha33 is related to YaHoWha13
            GraphEdge(src_id=YAHOWHA33_ID, rel_type=RelationType.MENTIONS,
                      dst_id=YAHOWHA13_ID,
                      metadata={"note": "YaHoWha33 is an open band of YaHoWha13 fans jamming with Djin"}),
        ]
        for edge in extra_edges:
            db.add_edge(edge)

    return added


def main():
    parser = argparse.ArgumentParser(
        description="Ingest PBS SoCal Artbound 'Meet The New Aquarians' into story_graph"
    )
    parser.add_argument("--db", default="data/graph.db", help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="No DB writes")
    parser.add_argument("--no-export", action="store_true", help="Skip snapshot export")
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("PBS SOCAL ARTBOUND ARTICLE INGESTION — story_graph")
    print(f"  {ARTICLE_TITLE} by {ARTICLE_AUTHOR} ({ARTICLE_DATE})")
    print("=" * 70)
    print()

    if args.dry_run:
        print("[dry-run mode — no DB writes]\n")

    db = GraphDB(Path(args.db))
    try:
        added = ingest(db, dry_run=args.dry_run)
        print(f"\nAdded {added} new nodes")

        if not args.dry_run and not args.no_export:
            print("\nExporting snapshot...")
            counts = export_to_json(db, Path("graph_snapshot"))
            print(f"Exported snapshot: {counts}")
    finally:
        db.close()

    print("\n" + "=" * 70)
    print("INGESTION COMPLETE")
    print("=" * 70)
    print("""
KEY FINDINGS:

1. ARTICLE INGESTED:
   - "Meet The New Aquarians" by Caroline Ryder, May 7, 2012
   - PBS SoCal Artbound (originally KCET)
   - URL: https://www.pbssocal.org/shows/artbound/meet-the-new-aquarians

2. NEW ENTITIES CREATED:
   - Caroline Ryder (author/journalist)
   - Guy Blakeslee (Entrance Band, Aquarian name: Sir Guyser)
   - Billy Corgan (Smashing Pumpkins, Aquarian name: Shmuel)
   - Devendra Banhart (freak folk musician)
   - MEAR ONE (graffiti artist, Father Yod stencil)
   - Sasha Vallely (Spindrift, Aquarian name: Kaleidoscopia)
   - Derek James (Entrance Band drummer, Aquarian name: Lux Deus)
   - OwlEyes (LA artist/collagist)
   - Michael Cepress (Seattle clothing designer)
   - Sunflower Aquarian (YaHoWha13 member)
   - Astara (Elf restaurant co-owner, Source Family devotee)
   - YaHoWha13 (Source Family psych band)
   - The Entrance Band (LA rock band)
   - YaHoWha33 (open jam band for YaHoWha13 fans)
   - Spindrift (LA band)
   - Smashing Pumpkins (rock band)
   - The Seeds (Sky Saxon's garage rock band)
   - The Echoplex (LA music venue)
   - Mount Shasta (Djin Aquarian's home)
   - Hawaii (Father Yod's death site, Isis Aquarian's home)

3. KEY CLAIMS EXTRACTED:
   - Father Yod: 14 spiritual wives, Nichols Canyon, ~140 members
   - Father Yod's death: hang-gliding accident, Hawaii, 1975
   - YaHoWha13 reunion at Echoplex, November 2007
   - Father Yod's prophecy: second incarnation with 4000 members
   - Isis Aquarian: right-hand woman, record keeper, spiritual wife
   - Billy Corgan's Aquarian name: Shmuel
   - Djin Aquarian: hundreds of Aquarian names given
   - New Aquarians: postmodern movement, not looking for a guru

4. LINKED TO EXISTING GRAPH:
   - Father Yod / Jim Baker (person-jim-baker-father-yod)
   - Source Family (group-source-family)
   - Isis Aquarian, Djin Aquarian, Electricity Aquarian, Sky Saxon
   - The Source restaurant, Nichols Canyon, Sunset Strip
   - Jodi Wille, Yogi Bhajan
   - The Source Family (2012 Documentary)
""")


if __name__ == "__main__":
    main()
