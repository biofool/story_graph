#!/usr/bin/env python3
"""
Ingest Robert Nadeau Russia/USSR seminar sources into the Story Graph.

Adds independent Russian-language sources confirming Nadeau taught seminars
in the USSR in the early 1990s:

- aikiclub.ru/spb.html — Moscow Aiki Club history of aikido in St. Petersburg
  (independent, specific date Oct 27 1990, Lenkai club, Leningrad, 6th dan, USA)
- bujutsu.ru/aikido/ — Federal Alliance of Bujutsu Russia history
  (independent, mentions Robert Nado seminars in Moscow/Leningrad 1987-1994)
- rebenok-na-aikido.ru — Kazan children's aikido school history
  (same org as bujutsu.ru, slightly different rank figure)

Also adds a TEACHER_STUDENT / SEMINAR_TAUGHT edge from Nadeau to a new
 dojo:lenkai-leningrad node representing the Lenkai club where he taught
 on Oct 27, 1990.

Usage:
    python scripts/29_ingest_nadeau_russia_seminars.py
    python scripts/29_ingest_nadeau_russia_seminars.py --dry-run
"""

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.lineage_db import LineageDB
from src.storage.models import (
    GraphNode, GraphEdge, NodeType, RelationType,
    SourceRecord, SourceClass,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("ingest_nadeau_russia")


# ============================================================
# NADEAU RUSSIA SEMINAR — Independent sources
# ============================================================

NADEAU_RUSSIA_SOURCES = [
    # Primary independent source — Moscow Aiki Club history
    {"url": "http://www.aikiclub.ru/spb.html",
     "title": "Развитие Айкидо в Санкт-Петербурге (Development of Aikido in St. Petersburg) — Moscow Aiki Club",
     "platform": "aikiclub.ru",
     "source_class": "independent_history",
     "author": "V. Matveev",
     "date": "2003-01-13",
     "quote_ru": "27 октября 1990 года, в день проведения Учредительной конференции Федерации Айкидо СССР, в клубе \"Ленкай\" провел тренировку Роберт НАДО ( 6-й Дан, США ), посетивший Советский Союз по приглашению айкидок из Москвы.",
     "quote_en": "On October 27, 1990, the day of the founding conference of the USSR Aikido Federation, Robert NADO (6th dan, USA) conducted a training at the Lenkai club, having visited the Soviet Union at the invitation of aikidoka from Moscow.",
     "city": "Leningrad (St. Petersburg)",
     "date_of_event": "1990-10-27",
     "rank_at_time": "6th dan",
     "nationality_listed": "USA (correct)",
     "independent": True},
    # Secondary independent source — Federal Alliance of Bujutsu Russia
    {"url": "https://www.bujutsu.ru/aikido/",
     "title": "Айкидо — Федерация Боевых Искусств России (Aikido — Federal Alliance of Bujutsu Russia)",
     "platform": "bujutsu.ru",
     "source_class": "independent_history",
     "quote_ru": "Александру Леонидовичу и Алексею Георгиевичу, именно в тот период времени, посчастливилось тренироваться у таких известных мастеров Айкидо, как Джек Вада (7 Дан Aikido Aikikai США), Роберт Надо (6 Дан Aikido Aikikai, Канада), Кристиан Тисьер (7 Дан Aikido Aikikai, Франция) и многих других.",
     "quote_en": "Alexander Leonidovich and Alexey Georgievich, during that period, had the good fortune to train with such famous Aikido masters as Jack Wada (7 dan Aikido Aikikai USA), Robert Nado (6 dan Aikido Aikikai, Canada), Christian Tissier (7 dan Aikido Aikikai, France) and many others.",
     "city": "Moscow, Leningrad (and others)",
     "date_range": "1987-1994",
     "rank_at_time": "6th dan",
     "nationality_listed": "Canada (incorrect — should be USA)",
     "independent": True},
    # Tertiary source — Kazan children's aikido (same org as bujutsu.ru)
    {"url": "https://rebenok-na-aikido.ru/",
     "title": "История Айкидо в Казани — Детская школа Айкидо (History of Aikido in Kazan — Children's Aikido School)",
     "platform": "rebenok-na-aikido.ru",
     "source_class": "independent_history",
     "city": "Moscow, Leningrad (and others)",
     "date_range": "1987-1994",
     "rank_at_time": "7th dan (differs from bujutsu.ru which says 6th)",
     "nationality_listed": "Canada (incorrect)",
     "independent": True},
]

# Lenkai club (Leningrad) — where Nadeau taught on Oct 27, 1990
LENKAI_DOJO = {
    "name": "Lenkai Aikido Club",
    "city": "Leningrad",
    "country": "USSR",
    "founded_year": None,  # unknown, predates Nadeau's visit
    "notes": "Hosted Robert Nadeau (6th dan, USA) on Oct 27, 1990 — the day of the founding conference of the USSR Aikido Federation",
}


def slugify(text):
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def run_ingestion(gdb: GraphDB, ldb: LineageDB, dry_run: bool = False) -> dict:
    stats = {"sources_added": 0, "dojos_added": 0, "edges_added": 0,
             "nodes_updated": 0}

    # ============================================================
    # 1. Add Nadeau Russia seminar source records
    # ============================================================
    _log.info("Adding %d Nadeau Russia seminar source records", len(NADEAU_RUSSIA_SOURCES))
    for src in NADEAU_RUSSIA_SOURCES:
        if dry_run:
            stats["sources_added"] += 1
            continue
        existing = gdb.get_source_by_url(src["url"])
        if not existing:
            src_id = f"src:{hashlib.sha256(src['url'].encode()).hexdigest()[:16]}"
            source_class = SourceClass.JOURNALISTIC  # independent historical accounts
            gdb.add_source(SourceRecord(
                id=src_id,
                url=src["url"],
                title=src["title"],
                platform=src["platform"],
                source_class=source_class,
            ))
            stats["sources_added"] += 1

    # ============================================================
    # 2. Add Lenkai dojo node
    # ============================================================
    dojo_id = f"dojo:{slugify(LENKAI_DOJO['name'])}"
    if dry_run:
        stats["dojos_added"] += 1
    else:
        existing = ldb.get_dojo(dojo_id)
        if not existing:
            ldb.upsert_dojo(
                node_id=dojo_id,
                name=LENKAI_DOJO["name"],
                head_instructor=None,
                city=LENKAI_DOJO["city"],
                state=None,
                country=LENKAI_DOJO["country"],
                lineage="aikikai",
                federation_id=None,
                metadata={
                    "source": "aikiclub.ru",
                    "notes": LENKAI_DOJO["notes"],
                    "historical": True,
                    "founded_year": LENKAI_DOJO["founded_year"],
                },
            )

            if not gdb.get_node(dojo_id):
                gdb.add_node(GraphNode(
                    id=dojo_id,
                    type=NodeType.DOJO,
                    label=LENKAI_DOJO["name"],
                    canonical_name=LENKAI_DOJO["name"],
                    metadata={
                        "city": LENKAI_DOJO["city"],
                        "country": LENKAI_DOJO["country"],
                        "lineage": "aikikai",
                        "historical": True,
                        "notes": LENKAI_DOJO["notes"],
                    },
                    source_urls=["http://www.aikiclub.ru/spb.html"],
                ))
            stats["dojos_added"] += 1

    # ============================================================
    # 3. Add Nadeau → Lenkai seminar edge (CO_APPEARANCE / SEMINAR_TAUGHT)
    # ============================================================
    # Using CO_APPEARANCE as the relationship type (Nadeau appeared as guest instructor)
    if not dry_run:
        gdb.add_edge(GraphEdge(
            src_id="person:robert-nadeau",
            rel_type=RelationType.CO_APPEARANCE,
            dst_id=dojo_id,
            metadata={
                "source": "aikiclub.ru",
                "source_url": "http://www.aikiclub.ru/spb.html",
                "context": "Guest training at Lenkai club on Oct 27, 1990 — founding conference of USSR Aikido Federation",
                "date": "1990-10-27",
                "rank_at_time": "6th dan",
                "city": "Leningrad",
                "country": "USSR",
                "independent_source": True,
                "quote_ru": "27 октября 1990 года, в день проведения Учредительной конференции Федерации Айкидо СССР, в клубе \"Ленкай\" провел тренировку Роберт НАДО ( 6-й Дан, США )",
            },
        ))
        ldb.insert_lineage_edge(
            "person:robert-nadeau", "CO_APPEARANCE", dojo_id,
            confidence=0.90,
            source_url="http://www.aikiclub.ru/spb.html",
            discovered_via="russian_language_web_search",
            review_status="approved",
            valid_from="1990-10-27",
            metadata={
                "context": "Guest training at Lenkai club on Oct 27, 1990",
                "event": "Founding conference of USSR Aikido Federation",
                "rank_at_time": "6th dan",
                "independent_source": True,
                "valid_to": "1990-10-27",
            },
        )
        stats["edges_added"] += 1

    # ============================================================
    # 4. Update Nadeau person metadata with Russia seminar info
    # ============================================================
    if not dry_run:
        import sqlite3
        conn = sqlite3.connect(str(settings.graph_db_abs_path))
        row = conn.execute(
            "SELECT metadata_json FROM nodes WHERE id = ?",
            ("person:robert-nadeau",),
        ).fetchone()
        if row and row[0]:
            meta = json.loads(row[0])
        else:
            meta = {}

        # Add Russia seminar info
        russia_seminars = meta.get("russia_seminars", [])
        new_seminar = {
            "date": "1990-10-27",
            "city": "Leningrad (St. Petersburg)",
            "venue": "Lenkai club",
            "event": "Founding conference of USSR Aikido Federation",
            "rank_at_time": "6th dan",
            "source": "http://www.aikiclub.ru/spb.html",
            "source_type": "independent",
            "source_author": "V. Matveev, Moscow Aiki Club",
            "quote": "On October 27, 1990, the day of the founding conference of the USSR Aikido Federation, Robert NADO (6th dan, USA) conducted a training at the Lenkai club",
        }
        if new_seminar not in russia_seminars:
            russia_seminars.append(new_seminar)
        meta["russia_seminars"] = russia_seminars
        meta["taught_in_russia"] = True
        meta["russia_seminar_independently_confirmed"] = True

        conn.execute(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?",
            (json.dumps(meta), "person:robert-nadeau"),
        )
        conn.commit()
        conn.close()

        # Also update lineage_persons
        ldb.upsert_person(
            "person:robert-nadeau", "Robert Nadeau",
            aliases=["Robert Nadeau", "Robert Nado", "Роберт Надо"],
            primary_art="Aikido",
            official_url="https://www.cityaikido.com/nadeau-shihan",
            primary_url="https://www.cityaikido.com/nadeau-shihan",
            metadata={
                "taught_in_russia": True,
                "russia_seminar_independently_confirmed": True,
                "russia_seminar_date": "1990-10-27",
                "russia_seminar_venue": "Lenkai club, Leningrad",
                "russia_seminar_source": "http://www.aikiclub.ru/spb.html",
            },
        )
        stats["nodes_updated"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Robert Nadeau Russia/USSR seminar sources into the Story Graph"
    )
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST NADEAU RUSSIA SEMINARS — Story Graph                       ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Database: {db_path}")
    print(f"Mode:     {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print()

    gdb = GraphDB(db_path)
    ldb = LineageDB(db_path)

    try:
        stats = run_ingestion(gdb, ldb, dry_run=args.dry_run)

        print()
        print("─── Ingestion Summary ───")
        print(f"  Sources added:       {stats['sources_added']:>4}")
        print(f"  Dojos added:          {stats['dojos_added']:>4}")
        print(f"  Edges added:          {stats['edges_added']:>4}")
        print(f"  Nodes updated:        {stats['nodes_updated']:>4}")
        print()
        print("Done.")

    finally:
        ldb.close()


if __name__ == "__main__":
    main()
