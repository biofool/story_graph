#!/usr/bin/env python3
"""
Create lineage graph tables in the Story Graph SQLite database.

Adds the structured relational tables that complement the existing
property-graph (nodes/edges/sources) tables. These tables provide
typed columns, time-series versioning, and disambiguation infrastructure
for the aikido lineage graph.

Idempotent: uses CREATE TABLE IF NOT EXISTS. Safe to run multiple times.

Usage:
    python scripts/26_create_lineage_tables.py
    python scripts/26_create_lineage_tables.py --db path/to/graph.db
    python scripts/26_create_lineage_tables.py --dry-run
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings


LINEAGE_DDL = """
-- ============================================================
-- LINEAGE GRAPH TABLES
-- Complements existing nodes/edges/sources/claim_sources tables
-- ============================================================

-- --- Persons (denormalized view of Person nodes) ---
CREATE TABLE IF NOT EXISTS lineage_persons (
    node_id         TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    aliases_json    TEXT DEFAULT '[]',       -- JSON array of strings
    birth_year      INTEGER,
    death_year      INTEGER,
    birth_place     TEXT,
    primary_art     TEXT,
    current_rank    TEXT,
    wikipedia_url   TEXT,
    kg_id           TEXT,
    official_url    TEXT,
    primary_url     TEXT,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- --- Dojos ---
CREATE TABLE IF NOT EXISTS lineage_dojos (
    node_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    aliases_json    TEXT DEFAULT '[]',
    head_instructor TEXT,
    federation_id   TEXT,
    division        TEXT,
    website         TEXT,
    email           TEXT,
    phone           TEXT,
    address_line    TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT,
    lat             REAL,
    lng             REAL,
    geocode_source  TEXT,
    lineage         TEXT,
    youth_program   INTEGER DEFAULT 0,       -- boolean
    web_maturity    TEXT,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- --- Federations ---
CREATE TABLE IF NOT EXISTS lineage_federations (
    node_id         TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    full_name       TEXT,
    aliases_json    TEXT DEFAULT '[]',
    parent_fed      TEXT,
    website         TEXT,
    founded_year    INTEGER,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- --- Books ---
CREATE TABLE IF NOT EXISTS lineage_books (
    node_id         TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    subtitle        TEXT,
    isbn_10         TEXT,
    isbn_13         TEXT,
    publisher       TEXT,
    publish_date    TEXT,
    openlibrary_key TEXT,
    google_books_id TEXT,
    amazon_asin     TEXT,
    author_ids_json TEXT DEFAULT '[]',       -- JSON array of person node_ids
    page_count      INTEGER,
    language        TEXT DEFAULT 'en',
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- --- Podcast episodes ---
CREATE TABLE IF NOT EXISTS lineage_episodes (
    node_id         TEXT PRIMARY KEY,
    show_name       TEXT NOT NULL,
    episode_title   TEXT NOT NULL,
    episode_number  INTEGER,
    publish_date    TEXT,
    duration_seconds INTEGER,
    guest_ids_json  TEXT DEFAULT '[]',
    host_ids_json   TEXT DEFAULT '[]',
    url             TEXT,
    rss_url         TEXT,
    transcript_url  TEXT,
    metadata_json   TEXT DEFAULT '{}',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- --- Structured edge table (typed columns, complements JSON edges table) ---
CREATE TABLE IF NOT EXISTS lineage_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id          TEXT NOT NULL,
    edge_type       TEXT NOT NULL,
    dst_id          TEXT NOT NULL,
    confidence      REAL DEFAULT 0.5,
    source_url      TEXT,
    discovered_via  TEXT,
    review_status   TEXT DEFAULT 'pending',
    metadata_json   TEXT DEFAULT '{}',
    valid_from      TEXT,                    -- ISO date
    valid_until     TEXT,                    -- NULL = current
    observed_at     TEXT DEFAULT (datetime('now')),
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(src_id, edge_type, dst_id, valid_from)
);

-- --- Raw dojo staging table (ETL layer 1) ---
CREATE TABLE IF NOT EXISTS dojo_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT NOT NULL,
    source_row      INTEGER NOT NULL,
    dojo_name       TEXT,
    website         TEXT,
    head_name       TEXT,
    email           TEXT,
    phone_number    TEXT,
    division        TEXT,
    city            TEXT,
    region          TEXT,
    state           TEXT,
    country         TEXT,
    lat             REAL,
    lng             REAL,
    lineage         TEXT,
    youth_program   TEXT,
    web_maturity    TEXT,
    dojo_cho_name   TEXT,
    heuristic_dojo_cho TEXT,
    philosophy_keywords TEXT,
    raw_json        TEXT,
    imported_at     TEXT DEFAULT (datetime('now')),
    UNIQUE(source_file, source_row)
);

-- --- Name collision resolution ---
CREATE TABLE IF NOT EXISTS name_collisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name  TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    disambiguator   TEXT,
    context_note    TEXT,
    resolved_at     TEXT DEFAULT (datetime('now')),
    resolved_by     TEXT DEFAULT 'auto',
    UNIQUE(canonical_name, disambiguator)
);

-- --- Entity reconciliation (ambiguous matches needing review) ---
CREATE TABLE IF NOT EXISTS entity_reconciliation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,
    candidate_name  TEXT NOT NULL,
    candidate_data  TEXT,                   -- JSON
    matched_node_id TEXT,
    match_method    TEXT,
    confidence      REAL DEFAULT 0.0,
    resolution_status TEXT DEFAULT 'pending',
    resolved_by     TEXT,
    resolved_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    notes           TEXT
);

-- --- Person candidates (uncertain matches, may be promoted later) ---
CREATE TABLE IF NOT EXISTS person_candidate (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_name  TEXT NOT NULL,
    suggested_node_id TEXT,
    context         TEXT,
    source_url      TEXT,
    source_file     TEXT,
    confidence      REAL DEFAULT 0.0,
    corroborating_sources TEXT DEFAULT '[]', -- JSON array
    status          TEXT DEFAULT 'candidate',
    promoted_to     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    reviewed_at     TEXT,
    reviewed_by     TEXT
);

-- --- Rank history (append-only time-series) ---
CREATE TABLE IF NOT EXISTS rank_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id       TEXT NOT NULL,
    rank_level      TEXT NOT NULL,
    rank_system     TEXT DEFAULT 'aikikai',
    awarded_by      TEXT,
    awarded_date    TEXT,
    source_url      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(person_id, rank_level, awarded_date)
);

-- --- Dojo affiliation history (append-only time-series) ---
CREATE TABLE IF NOT EXISTS dojo_affiliation_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dojo_id         TEXT NOT NULL,
    federation_id   TEXT NOT NULL,
    division        TEXT,
    start_date      TEXT,
    end_date        TEXT,
    source_url      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(dojo_id, federation_id, start_date)
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Persons
CREATE INDEX IF NOT EXISTS idx_lpersons_canonical_name ON lineage_persons(canonical_name);
CREATE INDEX IF NOT EXISTS idx_lpersons_primary_art ON lineage_persons(primary_art);
CREATE INDEX IF NOT EXISTS idx_lpersons_wikipedia ON lineage_persons(wikipedia_url) WHERE wikipedia_url IS NOT NULL;

-- Dojos
CREATE INDEX IF NOT EXISTS idx_ldojos_city ON lineage_dojos(city);
CREATE INDEX IF NOT EXISTS idx_ldojos_state ON lineage_dojos(state);
CREATE INDEX IF NOT EXISTS idx_ldojos_country ON lineage_dojos(country);
CREATE INDEX IF NOT EXISTS idx_ldojos_federation ON lineage_dojos(federation_id);
CREATE INDEX IF NOT EXISTS idx_ldojos_lineage ON lineage_dojos(lineage);
CREATE INDEX IF NOT EXISTS idx_ldojos_head_instructor ON lineage_dojos(head_instructor);
CREATE INDEX IF NOT EXISTS idx_ldojos_geo ON lineage_dojos(lat, lng) WHERE lat IS NOT NULL;

-- Books
CREATE INDEX IF NOT EXISTS idx_lbooks_isbn13 ON lineage_books(isbn_13) WHERE isbn_13 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_lbooks_openlibrary ON lineage_books(openlibrary_key) WHERE openlibrary_key IS NOT NULL;

-- Episodes
CREATE INDEX IF NOT EXISTS idx_lepisodes_date ON lineage_episodes(publish_date);
CREATE INDEX IF NOT EXISTS idx_lepisodes_show ON lineage_episodes(show_name);

-- Edges
CREATE INDEX IF NOT EXISTS idx_ledges_src ON lineage_edges(src_id);
CREATE INDEX IF NOT EXISTS idx_ledges_dst ON lineage_edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_ledges_type ON lineage_edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_ledges_src_type ON lineage_edges(src_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_ledges_dst_type ON lineage_edges(dst_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_ledges_valid ON lineage_edges(valid_from, valid_until) WHERE valid_until IS NULL;
CREATE INDEX IF NOT EXISTS idx_ledges_confidence ON lineage_edges(confidence);
CREATE INDEX IF NOT EXISTS idx_ledges_review ON lineage_edges(review_status);
CREATE INDEX IF NOT EXISTS idx_ledges_observed ON lineage_edges(observed_at);

-- Dojo raw
CREATE INDEX IF NOT EXISTS idx_dojo_raw_name ON dojo_raw(dojo_name);
CREATE INDEX IF NOT EXISTS idx_dojo_raw_website ON dojo_raw(website);
CREATE INDEX IF NOT EXISTS idx_dojo_raw_city ON dojo_raw(city, state, country);

-- Name collisions
CREATE INDEX IF NOT EXISTS idx_collisions_name ON name_collisions(canonical_name);
CREATE INDEX IF NOT EXISTS idx_collisions_node ON name_collisions(node_id);

-- Entity reconciliation
CREATE INDEX IF NOT EXISTS idx_recon_status ON entity_reconciliation(resolution_status);
CREATE INDEX IF NOT EXISTS idx_recon_name ON entity_reconciliation(candidate_name);
CREATE INDEX IF NOT EXISTS idx_recon_node ON entity_reconciliation(matched_node_id);

-- Person candidates
CREATE INDEX IF NOT EXISTS idx_pcandidate_name ON person_candidate(candidate_name);
CREATE INDEX IF NOT EXISTS idx_pcandidate_status ON person_candidate(status);

-- Rank history
CREATE INDEX IF NOT EXISTS idx_rank_person ON rank_history(person_id);
CREATE INDEX IF NOT EXISTS idx_rank_date ON rank_history(awarded_date);

-- Dojo affiliation history
CREATE INDEX IF NOT EXISTS idx_affil_dojo ON dojo_affiliation_history(dojo_id);
CREATE INDEX IF NOT EXISTS idx_affil_fed ON dojo_affiliation_history(federation_id);
CREATE INDEX IF NOT EXISTS idx_affil_current ON dojo_affiliation_history(dojo_id) WHERE end_date IS NULL;
"""


def main():
    parser = argparse.ArgumentParser(
        description="Create lineage graph tables in the Story Graph SQLite database"
    )
    parser.add_argument("--db", default=None, help="Database path (default: from settings)")
    parser.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = parser.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  CREATE LINEAGE TABLES — story_graph                               ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Database: {db_path}")

    if args.dry_run:
        print("[dry-run mode — DDL will be printed but not executed]")
        print()
        print(LINEAGE_DDL)
        return

    conn = sqlite3.connect(db_path)
    conn.executescript(LINEAGE_DDL)
    conn.commit()

    # Verify tables were created
    cur = conn.cursor()
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name LIKE 'lineage_%' OR name IN (
            'dojo_raw', 'name_collisions', 'entity_reconciliation',
            'person_candidate', 'rank_history', 'dojo_affiliation_history'
        )
        ORDER BY name
    """)
    tables = [row[0] for row in cur.fetchall()]
    print(f"\nCreated/verified {len(tables)} lineage tables:")
    for t in tables:
        cur.execute(f"SELECT count(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"  {t:35} {count:>6} rows")

    # Verify indexes
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='index' AND name LIKE 'idx_l%' OR name LIKE 'idx_dojo_raw%' OR
              name LIKE 'idx_collisions%' OR name LIKE 'idx_recon%' OR
              name LIKE 'idx_pcandidate%' OR name LIKE 'idx_rank%' OR
              name LIKE 'idx_affil%'
        ORDER BY name
    """)
    indexes = [row[0] for row in cur.fetchall()]
    print(f"\nCreated/verified {len(indexes)} indexes")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
