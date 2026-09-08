"""
Typed CRUD operations for the lineage graph tables.

Provides:
- LineageDB: wrapper around sqlite3.Connection for lineage tables
- upsert_person, upsert_dojo, upsert_federation, upsert_book, upsert_episode
- insert_lineage_edge: with valid_from/valid_until/observed_at versioning
- update_edge_with_version: close old edge, open new version
- query_graph_at_date: reconstruct graph state at any point in time
- lineage_network_at_date: person's lineage network snapshot
- record_rank_change: append-only rank history
- record_affiliation_change: append-only dojo affiliation history
- Name collision and entity reconciliation helpers
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LineageDB:
    """Typed CRUD for lineage graph tables with versioning support."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    # ================================================================
    # Person CRUD
    # ================================================================

    def upsert_person(
        self,
        node_id: str,
        canonical_name: str,
        aliases: list[str] | None = None,
        birth_year: int | None = None,
        death_year: int | None = None,
        birth_place: str | None = None,
        primary_art: str | None = None,
        current_rank: str | None = None,
        wikipedia_url: str | None = None,
        kg_id: str | None = None,
        official_url: str | None = None,
        primary_url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Insert or update a person row. Returns True if inserted, False if updated."""
        existing = self.query_one(
            "SELECT node_id FROM lineage_persons WHERE node_id = ?", (node_id,)
        )
        self.execute(
            """INSERT INTO lineage_persons
                (node_id, canonical_name, aliases_json, birth_year, death_year,
                 birth_place, primary_art, current_rank, wikipedia_url, kg_id,
                 official_url, primary_url, metadata_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                 canonical_name=excluded.canonical_name,
                 aliases_json=excluded.aliases_json,
                 birth_year=excluded.birth_year,
                 death_year=excluded.death_year,
                 birth_place=excluded.birth_place,
                 primary_art=excluded.primary_art,
                 current_rank=excluded.current_rank,
                 wikipedia_url=excluded.wikipedia_url,
                 kg_id=excluded.kg_id,
                 official_url=excluded.official_url,
                 primary_url=excluded.primary_url,
                 metadata_json=excluded.metadata_json,
                 updated_at=excluded.updated_at
            """,
            (
                node_id, canonical_name,
                json.dumps(aliases or []),
                birth_year, death_year, birth_place,
                primary_art, current_rank, wikipedia_url, kg_id,
                official_url, primary_url,
                json.dumps(metadata or {}),
                _now_iso(),
            ),
        )
        self.conn.commit()
        return existing is None

    def get_person(self, node_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM lineage_persons WHERE node_id = ?", (node_id,)
        )
        return dict(row) if row else None

    def find_persons_by_name(self, name: str) -> list[dict[str, Any]]:
        """Find persons by canonical_name (case-insensitive) or alias."""
        name_lower = name.strip().lower()
        rows = self.query_all(
            "SELECT * FROM lineage_persons WHERE lower(canonical_name) = ?",
            (name_lower,),
        )
        if rows:
            return [dict(r) for r in rows]
        # Try aliases
        all_persons = self.query_all("SELECT * FROM lineage_persons")
        results = []
        for p in all_persons:
            aliases = json.loads(p["aliases_json"] or "[]")
            if name_lower in [a.strip().lower() for a in aliases]:
                results.append(dict(p))
        return results

    # ================================================================
    # Dojo CRUD
    # ================================================================

    def upsert_dojo(
        self,
        node_id: str,
        name: str,
        aliases: list[str] | None = None,
        head_instructor: str | None = None,
        federation_id: str | None = None,
        division: str | None = None,
        website: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        address_line: str | None = None,
        city: str | None = None,
        state: str | None = None,
        country: str | None = None,
        lat: float | None = None,
        lng: float | None = None,
        geocode_source: str | None = None,
        lineage: str | None = None,
        youth_program: bool = False,
        web_maturity: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        existing = self.query_one(
            "SELECT node_id FROM lineage_dojos WHERE node_id = ?", (node_id,)
        )
        self.execute(
            """INSERT INTO lineage_dojos
                (node_id, name, aliases_json, head_instructor, federation_id,
                 division, website, email, phone, address_line, city, state,
                 country, lat, lng, geocode_source, lineage, youth_program,
                 web_maturity, metadata_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                 name=excluded.name,
                 aliases_json=excluded.aliases_json,
                 head_instructor=excluded.head_instructor,
                 federation_id=excluded.federation_id,
                 division=excluded.division,
                 website=excluded.website,
                 email=excluded.email,
                 phone=excluded.phone,
                 address_line=excluded.address_line,
                 city=excluded.city,
                 state=excluded.state,
                 country=excluded.country,
                 lat=excluded.lat,
                 lng=excluded.lng,
                 geocode_source=excluded.geocode_source,
                 lineage=excluded.lineage,
                 youth_program=excluded.youth_program,
                 web_maturity=excluded.web_maturity,
                 metadata_json=excluded.metadata_json,
                 updated_at=excluded.updated_at
            """,
            (
                node_id, name,
                json.dumps(aliases or []),
                head_instructor, federation_id, division,
                website, email, phone, address_line,
                city, state, country, lat, lng, geocode_source,
                lineage, int(youth_program), web_maturity,
                json.dumps(metadata or {}),
                _now_iso(),
            ),
        )
        self.conn.commit()
        return existing is None

    def get_dojo(self, node_id: str) -> dict[str, Any] | None:
        row = self.query_one(
            "SELECT * FROM lineage_dojos WHERE node_id = ?", (node_id,)
        )
        return dict(row) if row else None

    def find_dojos_by_domain(self, domain: str) -> list[dict[str, Any]]:
        """Find dojos by website domain (stored in metadata or website column)."""
        rows = self.query_all(
            "SELECT * FROM lineage_dojos WHERE website LIKE ?",
            (f"%{domain}%",),
        )
        return [dict(r) for r in rows]

    # ================================================================
    # Federation CRUD
    # ================================================================

    def upsert_federation(
        self,
        node_id: str,
        name: str,
        full_name: str | None = None,
        aliases: list[str] | None = None,
        parent_fed: str | None = None,
        website: str | None = None,
        founded_year: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        existing = self.query_one(
            "SELECT node_id FROM lineage_federations WHERE node_id = ?", (node_id,)
        )
        self.execute(
            """INSERT INTO lineage_federations
                (node_id, name, full_name, aliases_json, parent_fed, website,
                 founded_year, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                 name=excluded.name,
                 full_name=excluded.full_name,
                 aliases_json=excluded.aliases_json,
                 parent_fed=excluded.parent_fed,
                 website=excluded.website,
                 founded_year=excluded.founded_year,
                 metadata_json=excluded.metadata_json
            """,
            (
                node_id, name, full_name,
                json.dumps(aliases or []),
                parent_fed, website, founded_year,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return existing is None

    # ================================================================
    # Book CRUD
    # ================================================================

    def upsert_book(
        self,
        node_id: str,
        title: str,
        subtitle: str | None = None,
        isbn_10: str | None = None,
        isbn_13: str | None = None,
        publisher: str | None = None,
        publish_date: str | None = None,
        openlibrary_key: str | None = None,
        google_books_id: str | None = None,
        amazon_asin: str | None = None,
        author_ids: list[str] | None = None,
        page_count: int | None = None,
        language: str = "en",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        existing = self.query_one(
            "SELECT node_id FROM lineage_books WHERE node_id = ?", (node_id,)
        )
        self.execute(
            """INSERT INTO lineage_books
                (node_id, title, subtitle, isbn_10, isbn_13, publisher,
                 publish_date, openlibrary_key, google_books_id, amazon_asin,
                 author_ids_json, page_count, language, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(node_id) DO UPDATE SET
                 title=excluded.title,
                 subtitle=excluded.subtitle,
                 isbn_10=excluded.isbn_10,
                 isbn_13=excluded.isbn_13,
                 publisher=excluded.publisher,
                 publish_date=excluded.publish_date,
                 openlibrary_key=excluded.openlibrary_key,
                 google_books_id=excluded.google_books_id,
                 amazon_asin=excluded.amazon_asin,
                 author_ids_json=excluded.author_ids_json,
                 page_count=excluded.page_count,
                 language=excluded.language,
                 metadata_json=excluded.metadata_json
            """,
            (
                node_id, title, subtitle, isbn_10, isbn_13,
                publisher, publish_date, openlibrary_key,
                google_books_id, amazon_asin,
                json.dumps(author_ids or []),
                page_count, language,
                json.dumps(metadata or {}),
            ),
        )
        self.conn.commit()
        return existing is None

    # ================================================================
    # Edge CRUD with versioning
    # ================================================================

    def insert_lineage_edge(
        self,
        src_id: str,
        edge_type: str,
        dst_id: str,
        confidence: float = 0.5,
        source_url: str | None = None,
        discovered_via: str | None = None,
        review_status: str = "pending",
        metadata: dict[str, Any] | None = None,
        valid_from: str | None = None,
        valid_until: str | None = None,
        observed_at: str | None = None,
    ) -> int:
        """Insert a new lineage edge. Returns the edge ID.

        If an identical edge (same src+type+dst+valid_from) exists, it is
        a no-op (INSERT OR IGNORE semantics via UNIQUE constraint).
        """
        observed = observed_at or _now_iso()
        try:
            cur = self.execute(
                """INSERT OR IGNORE INTO lineage_edges
                    (src_id, edge_type, dst_id, confidence, source_url,
                     discovered_via, review_status, metadata_json,
                     valid_from, valid_until, observed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    src_id, edge_type, dst_id, confidence, source_url,
                    discovered_via, review_status,
                    json.dumps(metadata or {}),
                    valid_from, valid_until, observed,
                ),
            )
            self.conn.commit()
            return cur.lastrowid or 0
        except sqlite3.IntegrityError:
            _log.debug("Edge already exists: %s-%s->%s (valid_from=%s)",
                        src_id, edge_type, dst_id, valid_from)
            return 0

    def update_edge_with_version(
        self,
        src_id: str,
        edge_type: str,
        dst_id: str,
        new_metadata: dict[str, Any],
        valid_from: str,
        observed_at: str | None = None,
    ):
        """Close the current edge version and open a new one.

        This is the core versioning operation: when a relationship changes
        (e.g., a dojo changes division, a person gets promoted), the old
        edge is closed by setting valid_until, and a new edge is inserted
        with the updated metadata.
        """
        observed = observed_at or _now_iso()

        # Close existing current edge
        self.execute(
            """UPDATE lineage_edges
               SET valid_until = ?, observed_at = ?
               WHERE src_id = ? AND edge_type = ? AND dst_id = ?
                 AND valid_until IS NULL
            """,
            (valid_from, observed, src_id, edge_type, dst_id),
        )

        # Insert new version
        self.insert_lineage_edge(
            src_id=src_id,
            edge_type=edge_type,
            dst_id=dst_id,
            confidence=new_metadata.get("confidence", 0.5),
            source_url=new_metadata.get("source_url"),
            discovered_via=new_metadata.get("discovered_via", "etl"),
            review_status=new_metadata.get("review_status", "pending"),
            metadata=new_metadata,
            valid_from=valid_from,
            observed_at=observed,
        )
        self.conn.commit()
        _log.info("Edge versioned: %s-%s->%s valid_from=%s", src_id, edge_type, dst_id, valid_from)

    def get_current_edges(
        self, src_id: str | None = None, edge_type: str | None = None,
        dst_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all current edges (valid_until IS NULL) matching the criteria."""
        sql = "SELECT * FROM lineage_edges WHERE valid_until IS NULL"
        params: list = []
        if src_id:
            sql += " AND src_id = ?"
            params.append(src_id)
        if edge_type:
            sql += " AND edge_type = ?"
            params.append(edge_type)
        if dst_id:
            sql += " AND dst_id = ?"
            params.append(dst_id)
        sql += " ORDER BY edge_type, src_id"
        return [dict(r) for r in self.query_all(sql, tuple(params))]

    # ================================================================
    # Temporal reconstruction
    # ================================================================

    def query_graph_at_date(
        self, date: str, edge_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reconstruct all edges active as of a specific date.

        Args:
            date: ISO date string (e.g., "2005-06-01")
            edge_type: Optional filter by edge type

        Returns:
            List of edge dicts that were active on that date.
        """
        sql = """
            SELECT * FROM lineage_edges
            WHERE valid_from <= ?
              AND (valid_until IS NULL OR valid_until > ?)
        """
        params: list = [date, date]
        if edge_type:
            sql += " AND edge_type = ?"
            params.append(edge_type)
        sql += " ORDER BY edge_type, src_id"
        return [dict(r) for r in self.query_all(sql, tuple(params))]

    def lineage_network_at_date(
        self, person_id: str, date: str, depth: int = 3,
    ) -> list[dict[str, Any]]:
        """Reconstruct a person's lineage network as of a specific date.

        Uses recursive CTE to traverse TEACHER_STUDENT edges that were
        active on the given date.

        Answers: 'What did Nadeau's lineage network look like in 2005?'
        """
        # SQLite supports recursive CTEs
        sql = """
            WITH RECURSIVE lineage(person_id, edge_depth) AS (
                SELECT ?, 0
                UNION ALL
                SELECT e.dst_id, l.edge_depth + 1
                FROM lineage l
                JOIN lineage_edges e ON e.src_id = l.person_id
                  AND e.edge_type = 'TEACHER_STUDENT'
                WHERE e.valid_from <= ?
                  AND (e.valid_until IS NULL OR e.valid_until > ?)
                  AND l.edge_depth < ?
            )
            SELECT DISTINCT l.person_id, p.canonical_name, l.edge_depth,
                   d.name AS dojo_name, d.city, d.state
            FROM lineage l
            LEFT JOIN lineage_persons p ON l.person_id = p.node_id
            LEFT JOIN lineage_dojos d ON d.head_instructor = l.person_id
            ORDER BY l.edge_depth, p.canonical_name
        """
        rows = self.query_all(sql, (person_id, date, date, depth))
        return [dict(r) for r in rows]

    # ================================================================
    # Rank history (append-only)
    # ================================================================

    def record_rank_change(
        self,
        person_id: str,
        new_rank: str,
        awarded_date: str,
        awarded_by: str | None = None,
        source_url: str | None = None,
        rank_system: str = "aikikai",
    ):
        """Record a rank promotion. Never updates existing rank_history rows."""
        self.execute(
            """INSERT OR IGNORE INTO rank_history
                (person_id, rank_level, rank_system, awarded_by, awarded_date, source_url)
               VALUES (?, ?, ?, ?, ?, ?)
            """,
            (person_id, new_rank, rank_system, awarded_by, awarded_date, source_url),
        )

        # Update denormalized current_rank
        self.execute(
            "UPDATE lineage_persons SET current_rank = ?, updated_at = ? WHERE node_id = ?",
            (new_rank, _now_iso(), person_id),
        )
        self.conn.commit()
        _log.info("Rank recorded: %s → %s on %s", person_id, new_rank, awarded_date)

    def get_rank_history(self, person_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            "SELECT * FROM rank_history WHERE person_id = ? ORDER BY awarded_date",
            (person_id,),
        )
        return [dict(r) for r in rows]

    # ================================================================
    # Dojo affiliation history (append-only)
    # ================================================================

    def record_affiliation_change(
        self,
        dojo_id: str,
        new_fed_id: str,
        division: str | None = None,
        start_date: str | None = None,
        source_url: str | None = None,
    ):
        """Record a dojo changing federation/division.

        Closes the old affiliation (sets end_date) and inserts a new one.
        Also versions the DOJO_AFFILIATION edge.
        """
        start = start_date or _now_iso()[:10]

        # Close old affiliation
        self.execute(
            "UPDATE dojo_affiliation_history SET end_date = ? WHERE dojo_id = ? AND end_date IS NULL",
            (start, dojo_id),
        )

        # Insert new affiliation
        self.execute(
            """INSERT OR IGNORE INTO dojo_affiliation_history
                (dojo_id, federation_id, division, start_date, source_url)
               VALUES (?, ?, ?, ?, ?)
            """,
            (dojo_id, new_fed_id, division, start, source_url),
        )

        # Version the edge
        self.update_edge_with_version(
            dojo_id, "DOJO_AFFILIATION", new_fed_id,
            {"division": division, "source_url": source_url},
            valid_from=start,
        )

        # Update denormalized federation_id in lineage_dojos
        self.execute(
            "UPDATE lineage_dojos SET federation_id = ?, division = ?, updated_at = ? WHERE node_id = ?",
            (new_fed_id, division, _now_iso(), dojo_id),
        )
        self.conn.commit()
        _log.info("Affiliation change: %s → %s (division=%s) on %s",
                   dojo_id, new_fed_id, division, start)

    def get_affiliation_history(self, dojo_id: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            "SELECT * FROM dojo_affiliation_history WHERE dojo_id = ? ORDER BY start_date",
            (dojo_id,),
        )
        return [dict(r) for r in rows]

    # ================================================================
    # Name collisions
    # ================================================================

    def add_name_collision(
        self, canonical_name: str, node_id: str,
        disambiguator: str, context_note: str = "",
        resolved_by: str = "auto",
    ):
        """Record a name collision resolution."""
        self.execute(
            """INSERT OR IGNORE INTO name_collisions
                (canonical_name, node_id, disambiguator, context_note, resolved_by)
               VALUES (?, ?, ?, ?, ?)
            """,
            (canonical_name, node_id, disambiguator, context_note, resolved_by),
        )
        self.conn.commit()

    def get_name_collisions(self, canonical_name: str) -> list[dict[str, Any]]:
        rows = self.query_all(
            "SELECT * FROM name_collisions WHERE canonical_name = ?",
            (canonical_name,),
        )
        return [dict(r) for r in rows]

    # ================================================================
    # Entity reconciliation
    # ================================================================

    def queue_for_reconciliation(
        self, name: str, entity_type: str,
        candidate_data: dict[str, Any],
        confidence: float = 0.0,
    ):
        """Queue an ambiguous match for manual review."""
        self.execute(
            """INSERT INTO entity_reconciliation
                (entity_type, candidate_name, candidate_data, confidence, resolution_status)
               VALUES (?, ?, ?, ?, 'needs_review')
            """,
            (entity_type, name, json.dumps(candidate_data), confidence),
        )
        self.conn.commit()

    def resolve_reconciliation(
        self, rec_id: int, node_id: str, reviewer: str, notes: str = "",
    ):
        """Manually resolve a reconciliation candidate."""
        self.execute(
            """UPDATE entity_reconciliation
               SET matched_node_id = ?, match_method = 'manual',
                   resolution_status = 'resolved', resolved_by = ?,
                   resolved_at = ?, notes = ?
               WHERE id = ?
            """,
            (node_id, f"manual:{reviewer}", _now_iso(), notes, rec_id),
        )
        self.conn.commit()

    def get_pending_reconciliations(self) -> list[dict[str, Any]]:
        rows = self.query_all(
            "SELECT * FROM entity_reconciliation WHERE resolution_status = 'needs_review' ORDER BY created_at"
        )
        return [dict(r) for r in rows]

    # ================================================================
    # Person candidates
    # ================================================================

    def add_person_candidate(
        self, name: str, context: str, source_url: str,
        suggested_node_id: str | None = None,
        confidence: float = 0.0,
        source_file: str | None = None,
    ):
        """Add an uncertain person match as a candidate.

        If the candidate already exists, adds the source_url to
        corroborating_sources and bumps confidence.
        """
        existing = self.query_one(
            "SELECT id, corroborating_sources FROM person_candidate WHERE candidate_name = ? AND status = 'candidate'",
            (name,),
        )
        if existing:
            sources = json.loads(existing["corroborating_sources"] or "[]")
            if source_url and source_url not in sources:
                sources.append(source_url)
            new_confidence = min(1.0, confidence + 0.1)
            self.execute(
                "UPDATE person_candidate SET corroborating_sources = ?, confidence = ? WHERE id = ?",
                (json.dumps(sources), new_confidence, existing["id"]),
            )
        else:
            self.execute(
                """INSERT INTO person_candidate
                    (candidate_name, suggested_node_id, context, source_url,
                     source_file, confidence, corroborating_sources)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name, suggested_node_id, context, source_url,
                    source_file, confidence,
                    json.dumps([source_url] if source_url else []),
                ),
            )
        self.conn.commit()

    def promote_candidate(self, candidate_id: int, person_node_id: str, reviewer: str):
        """Promote a person candidate to a canonical person after review."""
        self.execute(
            """UPDATE person_candidate
               SET status = 'promoted', promoted_to = ?,
                   reviewed_at = ?, reviewed_by = ?
               WHERE id = ?
            """,
            (person_node_id, _now_iso(), reviewer, candidate_id),
        )
        self.conn.commit()

    def auto_promote_candidates(self, min_sources: int = 3, min_confidence: float = 0.7) -> int:
        """Auto-promote candidates with strong corroboration. Returns count promoted."""
        rows = self.query_all(
            """SELECT * FROM person_candidate
               WHERE status = 'candidate'
               AND json_array_length(corroborating_sources) >= ?
               AND confidence >= ?""",
            (min_sources, min_confidence),
        )
        count = 0
        for r in rows:
            if r["suggested_node_id"]:
                self.promote_candidate(r["id"], r["suggested_node_id"], "auto_promotion")
                count += 1
        _log.info("Auto-promoted %d person candidates", count)
        return count

    # ================================================================
    # Dojo raw staging
    # ================================================================

    def stage_dojo_raw(
        self, source_file: str, source_row: int, row: dict[str, Any],
    ):
        """Stage a raw CSV row into dojo_raw without transformation."""
        self.execute(
            """INSERT OR IGNORE INTO dojo_raw
                (source_file, source_row, dojo_name, website, head_name,
                 email, phone_number, division, city, region, state, country,
                 lat, lng, lineage, youth_program, web_maturity,
                 dojo_cho_name, heuristic_dojo_cho, philosophy_keywords, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_file, source_row,
                row.get("name", ""), row.get("website", ""),
                row.get("dojo_cho_name", "") or row.get("head_name", ""),
                row.get("email", ""), row.get("phone", ""),
                row.get("division", ""), row.get("city", ""),
                row.get("region", ""), row.get("state", ""),
                row.get("country", ""),
                row.get("lat"), row.get("lng"),
                row.get("lineage", ""), row.get("youth_program", ""),
                row.get("web_maturity", ""), row.get("dojo_cho_name", ""),
                row.get("heuristic_dojo_cho", ""),
                row.get("philosophy_keywords", ""),
                json.dumps(row),
            ),
        )
        self.conn.commit()

    def get_dojo_raw_count(self) -> int:
        row = self.query_one("SELECT count(*) as c FROM dojo_raw")
        return row["c"] if row else 0

    def get_all_dojo_raw(self) -> list[dict[str, Any]]:
        rows = self.query_all("SELECT * FROM dojo_raw ORDER BY source_file, source_row")
        return [dict(r) for r in rows]
