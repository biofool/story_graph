#!/usr/bin/env python3
"""
ETL pipeline: WorldStudioFinder aikido dojo CSV → lineage graph schema.

Full pipeline:
  1. Stage raw CSV rows into dojo_raw (preserves provenance)
  2. Clean names (trim, normalize case, remove redundant suffixes)
  3. Deduplicate by website domain + city
  4. Create Dojo nodes with full metadata
  5. Map head_name / dojo_cho_name → Person nodes via disambiguator
  6. Insert HEAD_INSTRUCTOR and DOJO_AFFILIATION edges
  7. Queue ambiguous matches in entity_reconciliation

Also syncs Dojo nodes into the existing property-graph (nodes/edges) tables
so they appear in the generic graph alongside Person/Work/etc nodes.

Usage:
    python scripts/27_etl_dojo_directory.py
    python scripts/27_etl_dojo_directory.py --dry-run
    python scripts/27_etl_dojo_directory.py --csv path/to/aikido_pilot_review.csv
    python scripts/27_etl_dojo_directory.py --skip-raw   # skip staging, use existing dojo_raw
"""

import argparse
import csv
import json
import logging
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.lineage_db import LineageDB
from src.storage.models import GraphNode, GraphEdge, NodeType, RelationType
from src.search.disambiguator import (
    build_alias_index, clean_dojo_name, deduplicate_dojos,
    map_head_to_person, normalize_domain, normalize_person_name, slugify,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("etl_dojo")

# Lineage display name → federation node_id mapping
# Based on data/reference/aikido_lineage_patterns.json
LINEAGE_TO_FED = {
    "Aikikai": "fed:aikikai",
    "Ki Society (Shin Shin Toitsu Aikido)": "fed:ki-society",
    "ASU (Aikido Schools of Ueshiba)": "fed:asu",
    "Iwama Style": "fed:iwama",
    "Yoshinkan": "fed:yoshinkan",
    "Kokikai": "fed:kokikai",
    "Shodokan / Tomiki Aikido": "fed:shodokan",
    "Birankai International": "fed:birankai",
    "Tissier Lineage": "fed:tissier",
    "Nadeau Lineage (Richard Moon lineage)": "fed:caa",
    # Hybrid/Eclectic → no federation
    "Hybrid / Eclectic": None,
}

# Federation node metadata for auto-creation
FEDERATION_META = {
    "fed:aikikai": {"name": "Aikikai", "full_name": "Aikikai Foundation", "website": "https://www.aikikai.or.jp/"},
    "fed:ki-society": {"name": "Ki Society", "full_name": "Ki Society (Shin Shin Toitsu Aikido)", "website": "https://ki-society.com/"},
    "fed:asu": {"name": "ASU", "full_name": "Aikido Schools of Ueshiba", "website": "https://www.asu-aikido.com/"},
    "fed:iwama": {"name": "Iwama Style", "full_name": "Iwama Ryu Aikido"},
    "fed:yoshinkan": {"name": "Yoshinkan", "full_name": "Yoshinkan Aikido", "website": "https://www.yoshinkan.net/"},
    "fed:kokikai": {"name": "Kokikai", "full_name": "Kokikai Aikido"},
    "fed:shodokan": {"name": "Shodokan", "full_name": "Shodokan / Tomiki Aikido"},
    "fed:birankai": {"name": "Birankai", "full_name": "Birankai International", "website": "https://www.birankai.org/"},
    "fed:tissier": {"name": "Tissier Lineage", "full_name": "Tissier Lineage"},
    "fed:caa": {"name": "CAA", "full_name": "California Aikido Association", "website": "https://ca-aikido.com/"},
}


def stage_csv_to_raw(csv_path: Path, ldb: LineageDB, dry_run: bool = False) -> int:
    """Stage raw CSV rows into dojo_raw table. Returns count staged."""
    _log.info("Staging CSV: %s", csv_path)
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        count = 0
        for row_num, row in enumerate(reader, start=2):
            if dry_run:
                count += 1
                continue
            ldb.stage_dojo_raw(csv_path.name, row_num, row)
            count += 1
    _log.info("Staged %d raw rows %s", count, "(dry-run)" if dry_run else "")
    return count


def create_federation_nodes(ldb: LineageDB, gdb: GraphDB, dry_run: bool = False):
    """Create Federation nodes for all lineages found in the data."""
    for fed_id, meta in FEDERATION_META.items():
        if dry_run:
            continue
        # Lineage table
        ldb.upsert_federation(
            node_id=fed_id,
            name=meta["name"],
            full_name=meta.get("full_name"),
            website=meta.get("website"),
        )
        # Generic graph node
        existing = gdb.get_node(fed_id)
        if not existing:
            node = GraphNode(
                id=fed_id,
                type=NodeType.FEDERATION,
                label=meta["name"],
                canonical_name=meta.get("full_name", meta["name"]),
                metadata={"website": meta.get("website")},
                source_urls=[meta["website"]] if meta.get("website") else [],
            )
            gdb.add_node(node)
    _log.info("Ensured %d federation nodes", len(FEDERATION_META))


def run_etl(csv_path: Path, ldb: LineageDB, gdb: GraphDB,
            dry_run: bool = False, skip_raw: bool = False) -> dict:
    """Run the full ETL pipeline. Returns summary stats."""
    stats = {
        "raw_staged": 0,
        "deduped": 0,
        "dojos_created": 0,
        "dojos_updated": 0,
        "edges_head_instructor": 0,
        "edges_dojo_affiliation": 0,
        "persons_resolved": 0,
        "persons_unresolved": 0,
        "federations_ensured": 0,
    }

    # Step 1: Stage raw CSV
    if not skip_raw:
        stats["raw_staged"] = stage_csv_to_raw(csv_path, ldb, dry_run)
    else:
        stats["raw_staged"] = ldb.get_dojo_raw_count()
        _log.info("Skipping raw staging, using %d existing rows", stats["raw_staged"])

    if dry_run and not skip_raw:
        # In dry-run with no raw data, we can't continue
        _log.info("[dry-run] Stopping after staging. Run without --dry-run to execute full ETL.")
        return stats

    # Step 2: Load raw rows and deduplicate
    raw_rows = ldb.get_all_dojo_raw()
    _log.info("Loaded %d raw rows from dojo_raw", len(raw_rows))

    # Convert sqlite3.Row to dict for dedup
    raw_dicts = []
    for r in raw_rows:
        d = dict(r)
        # Map dojo_raw column names to what dedup expects
        d["dojo_name"] = d.get("dojo_name") or ""
        d["website"] = d.get("website") or ""
        d["city"] = d.get("city") or ""
        raw_dicts.append(d)

    deduped = deduplicate_dojos(raw_dicts)
    stats["deduped"] = len(deduped)
    _log.info("After dedup: %d unique dojos", len(deduped))

    # Step 3: Ensure federation nodes exist
    create_federation_nodes(ldb, gdb, dry_run)
    stats["federations_ensured"] = len(FEDERATION_META)

    # Step 4: Build alias index for person resolution
    alias_index = build_alias_index(ldb)
    _log.info("Alias index: %d names", len(alias_index))

    # Step 5: Process each deduplicated dojo
    for row in deduped:
        dojo_name = clean_dojo_name(row.get("dojo_name", ""))
        if not dojo_name:
            continue

        dojo_id = f"dojo:{slugify(dojo_name)}"
        domain = normalize_domain(row.get("website", ""))
        lineage = (row.get("lineage") or "").strip()
        fed_id = LINEAGE_TO_FED.get(lineage)

        # Parse lat/lng
        lat = None
        lng = None
        try:
            if row.get("lat"):
                lat = float(row["lat"])
            if row.get("lng"):
                lng = float(row["lng"])
        except (ValueError, TypeError):
            pass

        # Step 5a: Upsert into lineage_dojos
        if not dry_run:
            inserted = ldb.upsert_dojo(
                node_id=dojo_id,
                name=dojo_name,
                head_instructor=None,  # will set after person resolution
                federation_id=fed_id,
                website=row.get("website") or None,
                email=row.get("email") or None,
                city=row.get("city") or None,
                state=row.get("state") or None,
                country=row.get("country") or None,
                lat=lat,
                lng=lng,
                geocode_source="csv" if lat else None,
                lineage=lineage or None,
                youth_program=(row.get("youth_program") or "").lower() == "yes",
                web_maturity=row.get("web_maturity") or None,
                metadata={
                    "source": "worldstudiofinder_etl",
                    "source_file": row.get("source_file"),
                    "source_row": row.get("source_row"),
                    "domain": domain,
                    "segment": row.get("segment"),
                    "resonance_score": row.get("resonance_score"),
                    "page_count": row.get("page_count"),
                    "philosophy_keywords": row.get("philosophy_keywords"),
                    "primary_service": row.get("primary_service"),
                    "target_audience": row.get("target_audience"),
                    "is_spam": row.get("is_spam"),
                },
            )
            if inserted:
                stats["dojos_created"] += 1
            else:
                stats["dojos_updated"] += 1

        # Step 5b: Sync to generic graph (nodes table)
        if not dry_run:
            existing = gdb.get_node(dojo_id)
            if not existing:
                node = GraphNode(
                    id=dojo_id,
                    type=NodeType.DOJO,
                    label=dojo_name,
                    canonical_name=dojo_name,
                    metadata={
                        "city": row.get("city"),
                        "state": row.get("state"),
                        "country": row.get("country"),
                        "website": row.get("website"),
                        "lineage": lineage,
                        "source": "worldstudiofinder_etl",
                    },
                    source_urls=[row["website"]] if row.get("website") else [],
                )
                gdb.add_node(node)

        # Step 5c: Map head instructor → Person
        cho_name = (row.get("dojo_cho_name") or "").strip()
        if not cho_name:
            cho_name = (row.get("heuristic_dojo_cho") or "").strip()

        person_id = None
        if cho_name:
            context = f"{dojo_name} {row.get('city', '')} {lineage}"
            person_id = map_head_to_person(
                cho_name, ldb, alias_index,
                context=context, domain=domain,
            )
            if person_id:
                stats["persons_resolved"] += 1
                # Insert HEAD_INSTRUCTOR edge
                if not dry_run:
                    ldb.insert_lineage_edge(
                        src_id=person_id,
                        edge_type="HEAD_INSTRUCTOR",
                        dst_id=dojo_id,
                        confidence=0.6,
                        source_url=row.get("website"),
                        discovered_via="dojo_etl",
                        review_status="auto",
                        metadata={
                            "is_primary": True,
                            "source": "worldstudiofinder_csv",
                            "raw_name": cho_name,
                        },
                    )
                    # Also sync to generic graph edges
                    gdb.add_edge(GraphEdge(
                        src_id=person_id,
                        rel_type=RelationType.HEAD_INSTRUCTOR,
                        dst_id=dojo_id,
                        metadata={"source": "worldstudiofinder_etl", "raw_name": cho_name},
                    ))
                    stats["edges_head_instructor"] += 1
            else:
                stats["persons_unresolved"] += 1
                # Queue as person candidate
                if not dry_run:
                    ldb.add_person_candidate(
                        name=cho_name,
                        context=f"dojo:{dojo_name} ({row.get('city','')}, {row.get('state','')})",
                        source_url=row.get("website") or "",
                        confidence=0.3,
                        source_file=row.get("source_file"),
                    )

        # Step 5d: Insert DOJO_AFFILIATION edge
        if fed_id and not dry_run:
            ldb.insert_lineage_edge(
                src_id=dojo_id,
                edge_type="DOJO_AFFILIATION",
                dst_id=fed_id,
                confidence=0.8,
                source_url=row.get("website"),
                discovered_via="dojo_etl",
                review_status="auto",
                metadata={
                    "lineage": lineage,
                    "source": "worldstudiofinder_csv",
                },
            )
            # Also sync to generic graph
            gdb.add_edge(GraphEdge(
                src_id=dojo_id,
                rel_type=RelationType.DOJO_AFFILIATION,
                dst_id=fed_id,
                metadata={"lineage": lineage, "source": "worldstudiofinder_etl"},
            ))
            stats["edges_dojo_affiliation"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="ETL: WorldStudioFinder aikido dojo CSV → lineage graph"
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to aikido_pilot_review.csv (default: auto-detect from WorldStudioFinder)",
    )
    parser.add_argument("--db", default=None, help="Database path (default: from settings)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--skip-raw", action="store_true", help="Skip CSV staging, use existing dojo_raw data")
    args = parser.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)

    # Auto-detect CSV path
    if args.csv:
        csv_path = Path(args.csv)
    else:
        wsf_csv = Path.home() / "projects/github/WorldStudioFinder/data/audit/aikido_pilot_review.csv"
        local_csv = PROJECT_ROOT / "data/audit/aikido_pilot_review.csv"
        if wsf_csv.exists():
            csv_path = wsf_csv
        elif local_csv.exists():
            csv_path = local_csv
        else:
            print(f"ERROR: Could not find aikido_pilot_review.csv")
            print(f"  Tried: {wsf_csv}")
            print(f"  Tried: {local_csv}")
            print(f"  Use --csv to specify the path")
            sys.exit(1)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  ETL DOJO DIRECTORY — WorldStudioFinder → lineage graph            ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"CSV:      {csv_path}")
    print(f"Database: {db_path}")
    print(f"Mode:     {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print()

    ldb = LineageDB(db_path)
    gdb = GraphDB(db_path)

    try:
        stats = run_etl(csv_path, ldb, gdb, dry_run=args.dry_run, skip_raw=args.skip_raw)

        print()
        print("─── ETL Summary ───")
        print(f"  Raw rows staged:       {stats['raw_staged']:>6}")
        print(f"  Deduplicated dojos:    {stats['deduped']:>6}")
        print(f"  Dojos created:         {stats['dojos_created']:>6}")
        print(f"  Dojos updated:         {stats['dojos_updated']:>6}")
        print(f"  Federations ensured:   {stats['federations_ensured']:>6}")
        print(f"  Persons resolved:      {stats['persons_resolved']:>6}")
        print(f"  Persons unresolved:    {stats['persons_unresolved']:>6}")
        print(f"  HEAD_INSTRUCTOR edges: {stats['edges_head_instructor']:>6}")
        print(f"  DOJO_AFFILIATION edges: {stats['edges_dojo_affiliation']:>6}")

        if not args.dry_run:
            # Show pending reconciliations
            pending = ldb.get_pending_reconciliations()
            if pending:
                print(f"\n  ⚠ {len(pending)} entities need reconciliation review")

            # Show person candidates
            candidates = ldb.query_all(
                "SELECT count(*) as c FROM person_candidate WHERE status = 'candidate'"
            )
            cand_count = candidates[0]["c"] if candidates else 0
            if cand_count:
                print(f"  ⚠ {cand_count} person candidates awaiting review")

        print()
        print("Done.")

    finally:
        ldb.close()


if __name__ == "__main__":
    main()
