#!/usr/bin/env python3
"""
Ingest the Richard Moon → Peter Ralston STUDENT_OF edge into the Story Graph.

Adds a TEACHER_STUDENT edge: person:peter-ralston (teacher) → person:richard-moon-aikido (student),
documenting that Richard Moon studied tai chi, boxing, and Cheng Hsin with Peter Ralston.

Sources (both primary / first-person, both authored or controlled by Richard Moon):
1. quantumaikido.com — Richard Moon's own author site. Multiple pages state:
   "55 years of Aikido with Robert Nadeau, tai chi and boxing with Peter Ralston"
   (index.html, media-kit.html, reviews.html, interviews.html, index.md)
2. nadeaushihan.com/authors — Richard Moon's author bio on the Nadeau book site. States:
   "practiced Cheng Hsin with world champion Peter Ralston"
   (likely also written by Moon himself — treat as same primary source class, different platform)

Per AGENTS.md, kkron's assertions are first-class graph evidence. This edge records
the Moon→Ralston training relationship as a primary-source claim with both URLs cited.
It is NOT independent corroboration — both sources are Moon's own self-description.

Usage:
    python scripts/30_ingest_moon_ralston_edge.py
    python scripts/30_ingest_moon_ralston_edge.py --dry-run
"""

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.lineage_db import LineageDB
from src.storage.models import GraphEdge, RelationType, SourceRecord, SourceClass

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("ingest_moon_ralston_edge")


# ============================================================
# MOON → RALSTON training sources (both primary / first-person)
# ============================================================

MOON_RALSTON_SOURCES = [
    {
        "url": "https://quantumaikido.com/",
        "title": "Quantum Aikido: The Power of Harmony — Richard Moon (author bio)",
        "platform": "quantumaikido.com",
        "source_class": SourceClass.PRIMARY_FIRST_PERSON,
        "quote": "Richard Moon is a lifelong student of the awareness arts. 55 years of Aikido with Robert Nadeau, tai chi and boxing with Peter Ralston, Capoeira with Mestre Acordeon.",
        "author": "Richard Moon",
        "note": "Moon's own author site. Primary/first-person. Not independent.",
    },
    {
        "url": "https://www.nadeaushihan.com/authors",
        "title": "Authors — Robert Nadeau Shihan (Richard Moon bio)",
        "platform": "nadeaushihan.com",
        "source_class": SourceClass.PRIMARY_FIRST_PERSON,
        "quote": "Richard was also a personal student of Bira Almeida, Mestre Acordeon of Brazilian Capoeira, practiced Cheng Hsin with world champion Peter Ralston, and trained in qigong with B.K. Frantzis.",
        "author": "Richard Moon (likely)",
        "note": "Moon's author bio on the Nadeau book site. Likely written by Moon himself. Same primary source class, different platform. Not independent of source 1.",
    },
]


def run_ingestion(gdb: GraphDB, ldb: LineageDB, dry_run: bool = False) -> dict:
    stats = {
        "sources_added": 0,
        "edges_added": 0,
        "nodes_updated": 0,
    }

    # ============================================================
    # 1. Add source records (if not already present)
    # ============================================================
    for src in MOON_RALSTON_SOURCES:
        src_id = f"src:moon-ralston:{src['platform']}"
        if dry_run:
            stats["sources_added"] += 1
            continue
        existing = gdb.get_source_by_url(src["url"])
        if existing:
            _log.info("Source already exists: %s", src["url"])
            continue
        gdb.add_source(SourceRecord(
            id=src_id,
            url=src["url"],
            title=src["title"],
            platform=src["platform"],
            source_class=src["source_class"],
        ))
        stats["sources_added"] += 1

    # ============================================================
    # 2. Add TEACHER_STUDENT edge: peter-ralston → richard-moon-aikido
    # ============================================================
    # Direction: Ralston is the teacher, Moon is the student.
    # TEACHER_STUDENT edge goes teacher → student (matches script 28 pattern:
    # Nadeau → Noha).
    if dry_run:
        stats["edges_added"] += 1
        stats["nodes_updated"] += 1
        return stats

    gdb.add_edge(GraphEdge(
        src_id="person:peter-ralston",
        rel_type=RelationType.TEACHER_STUDENT,
        dst_id="person:richard-moon-aikido",
        metadata={
            "context": "studied tai chi, boxing, and Cheng Hsin with Ralston",
            "source_urls": [
                "https://quantumaikido.com/",
                "https://www.nadeaushihan.com/authors",
            ],
            "source_class": "primary_first_person",
            "independent_corroboration": False,
            "note": "Both sources are Moon's own self-description (primary/first-person). Not independent corroboration. Per AGENTS.md, kkron assertions are first-class graph evidence.",
            "arts_studied": ["tai chi", "boxing", "Cheng Hsin"],
        },
    ))
    ldb.insert_lineage_edge(
        "person:peter-ralston", "TEACHER_STUDENT", "person:richard-moon-aikido",
        confidence=0.85,
        source_url="https://quantumaikido.com/",
        discovered_via="web_research",
        review_status="approved",
        metadata={
            "context": "studied tai chi, boxing, and Cheng Hsin with Ralston",
            "source_urls": [
                "https://quantumaikido.com/",
                "https://www.nadeaushihan.com/authors",
            ],
            "source_class": "primary_first_person",
            "independent_corroboration": False,
            "arts_studied": ["tai chi", "boxing", "Cheng Hsin"],
        },
    )
    stats["edges_added"] += 1

    # ============================================================
    # 3. Update Richard Moon person metadata with Ralston training info
    # ============================================================
    import sqlite3
    conn = sqlite3.connect(str(settings.graph_db_abs_path))
    row = conn.execute(
        "SELECT metadata_json FROM nodes WHERE id = ?",
        ("person:richard-moon-aikido",),
    ).fetchone()
    if row and row[0]:
        meta = json.loads(row[0])
    else:
        meta = {}

    cross_training = meta.get("cross_training", [])
    new_arts = ["tai chi", "boxing", "Cheng Hsin"]
    for art in new_arts:
        if art not in cross_training:
            cross_training.append(art)
    meta["cross_training"] = cross_training
    meta["cheng_hsin_teacher"] = "Peter Ralston"
    meta["ralston_training_sources"] = [
        "https://quantumaikido.com/",
        "https://www.nadeaushihan.com/authors",
    ]
    meta["ralston_training_source_class"] = "primary_first_person"

    conn.execute(
        "UPDATE nodes SET metadata_json = ? WHERE id = ?",
        (json.dumps(meta), "person:richard-moon-aikido"),
    )
    conn.commit()
    conn.close()
    stats["nodes_updated"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Richard Moon → Peter Ralston STUDENT_OF edge into the Story Graph"
    )
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST MOON → RALSTON STUDENT_OF EDGE — Story Graph              ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Database: {db_path}")
    print(f"Mode:     {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print()
    print("Edge: person:peter-ralston --TEACHER_STUDENT--> person:richard-moon-aikido")
    print("Context: studied tai chi, boxing, and Cheng Hsin with Ralston")
    print("Sources:")
    for s in MOON_RALSTON_SOURCES:
        print(f"  - {s['url']}")
        print(f"    [{s['source_class']}] {s['note']}")
    print()

    gdb = GraphDB(db_path)
    ldb = LineageDB(db_path)

    try:
        stats = run_ingestion(gdb, ldb, dry_run=args.dry_run)

        print()
        print("─── Ingestion Summary ───")
        print(f"  Sources added:    {stats['sources_added']:>4}")
        print(f"  Edges added:      {stats['edges_added']:>4}")
        print(f"  Nodes updated:    {stats['nodes_updated']:>4}")
        print()
    finally:
        ldb.close()


if __name__ == "__main__":
    main()
