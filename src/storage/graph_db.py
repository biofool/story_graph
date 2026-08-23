"""
SQLite graph storage: nodes, edges, sources, and claim-source links.
Provides add/upsert operations and query helpers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional, Any

from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
    SourceRecord,
    ClaimSourceLink,
    SourceClass,
    BiasHint,
)

_log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL,
    canonical_name TEXT,
    metadata_json TEXT DEFAULT '{}',
    source_urls_json TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    metadata_json TEXT DEFAULT '{}',
    UNIQUE(src_id, rel_type, dst_id)
);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    author TEXT,
    publish_date TEXT,
    platform TEXT,
    raw_text TEXT,
    source_class TEXT,
    bias_hint TEXT
);

CREATE TABLE IF NOT EXISTS claim_sources (
    claim_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    quote_span_start INTEGER,
    quote_span_end INTEGER,
    PRIMARY KEY (claim_id, source_id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_canonical_name ON nodes(canonical_name);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_edges_rel ON edges(rel_type);
CREATE INDEX IF NOT EXISTS idx_sources_url ON sources(url);
"""


class GraphDB:
    """SQLite-backed property graph store."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self):
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # --- Node operations ---

    def add_node(self, node: GraphNode):
        """Insert or update a node (upsert by id)."""
        existing = self.get_node(node.id)
        if existing:
            # Merge: update non-empty fields. source_urls is de-duplicated via
            # a sorted list (not a bare set()) so repeated upserts of the same
            # node produce byte-identical output across runs/processes — a
            # bare set()'s iteration order is randomized per-process (string
            # hash randomization), which would otherwise make
            # src/storage/json_export.py's JSONL export non-deterministic.
            merged_meta = {**existing.metadata, **node.metadata}
            merged_urls = sorted(set(existing.source_urls + node.source_urls))
            canonical = node.canonical_name or existing.canonical_name
            label = node.label or existing.label
        else:
            merged_meta = node.metadata
            merged_urls = node.source_urls
            canonical = node.canonical_name
            label = node.label

        self._conn.execute(
            """
            INSERT INTO nodes (id, type, label, canonical_name, metadata_json, source_urls_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                label = excluded.label,
                canonical_name = COALESCE(excluded.canonical_name, nodes.canonical_name),
                metadata_json = excluded.metadata_json,
                source_urls_json = excluded.source_urls_json
            """,
            (
                node.id,
                node.type.value,
                label,
                canonical,
                json.dumps(merged_meta),
                json.dumps(merged_urls),
            ),
        )
        self._conn.commit()

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if not row:
            return None
        return GraphNode(
            id=row["id"],
            type=NodeType(row["type"]),
            label=row["label"],
            canonical_name=row["canonical_name"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            source_urls=json.loads(row["source_urls_json"] or "[]"),
        )

    def get_all_nodes(self) -> list[GraphNode]:
        """Get every node across all types, ordered by id.

        Used by src/storage/json_export.py to produce a deterministic,
        diff-stable JSON export of the whole graph.
        """
        rows = self._conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        return [
            GraphNode(
                id=r["id"],
                type=NodeType(r["type"]),
                label=r["label"],
                canonical_name=r["canonical_name"],
                metadata=json.loads(r["metadata_json"] or "{}"),
                source_urls=json.loads(r["source_urls_json"] or "[]"),
            )
            for r in rows
        ]

    def get_nodes_by_type(self, node_type: NodeType) -> list[GraphNode]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE type = ? ORDER BY label",
            (node_type.value,),
        ).fetchall()
        return [
            GraphNode(
                id=r["id"],
                type=NodeType(r["type"]),
                label=r["label"],
                canonical_name=r["canonical_name"],
                metadata=json.loads(r["metadata_json"] or "{}"),
                source_urls=json.loads(r["source_urls_json"] or "[]"),
            )
            for r in rows
        ]

    # --- Edge operations ---

    def add_edge(self, edge: GraphEdge):
        """Insert edge if not already present (ignore duplicates)."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO edges (src_id, rel_type, dst_id, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                edge.src_id,
                edge.rel_type.value,
                edge.dst_id,
                json.dumps(edge.metadata),
            ),
        )
        self._conn.commit()

    def get_edges_from(self, node_id: str) -> list[GraphEdge]:
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE src_id = ?", (node_id,)
        ).fetchall()
        return [
            GraphEdge(
                src_id=r["src_id"],
                rel_type=RelationType(r["rel_type"]),
                dst_id=r["dst_id"],
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            for r in rows
        ]

    def get_edges_to(self, node_id: str) -> list[GraphEdge]:
        rows = self._conn.execute(
            "SELECT * FROM edges WHERE dst_id = ?", (node_id,)
        ).fetchall()
        return [
            GraphEdge(
                src_id=r["src_id"],
                rel_type=RelationType(r["rel_type"]),
                dst_id=r["dst_id"],
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            for r in rows
        ]

    def get_all_edges(self) -> list[GraphEdge]:
        rows = self._conn.execute("SELECT * FROM edges").fetchall()
        return [
            GraphEdge(
                src_id=r["src_id"],
                rel_type=RelationType(r["rel_type"]),
                dst_id=r["dst_id"],
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            for r in rows
        ]

    # --- Source operations ---

    def add_source(self, source: SourceRecord):
        """Insert or update a source record (upsert by id)."""
        self._conn.execute(
            """
            INSERT INTO sources (id, url, title, author, publish_date, platform, raw_text, source_class, bias_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = COALESCE(excluded.title, sources.title),
                author = COALESCE(excluded.author, sources.author),
                publish_date = COALESCE(excluded.publish_date, sources.publish_date),
                platform = COALESCE(excluded.platform, sources.platform),
                raw_text = COALESCE(excluded.raw_text, sources.raw_text),
                source_class = COALESCE(excluded.source_class, sources.source_class),
                bias_hint = COALESCE(excluded.bias_hint, sources.bias_hint)
            """,
            (
                source.id,
                source.url,
                source.title,
                source.author,
                source.publish_date,
                source.platform,
                source.raw_text,
                source.source_class.value if source.source_class else None,
                source.bias_hint.value if source.bias_hint else None,
            ),
        )
        self._conn.commit()

    def get_source_by_url(self, url: str) -> Optional[SourceRecord]:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE url = ?", (url,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_source(row)

    def get_source(self, source_id: str) -> Optional[SourceRecord]:
        row = self._conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_source(row)

    def get_all_sources(self) -> list[SourceRecord]:
        rows = self._conn.execute("SELECT * FROM sources ORDER BY url").fetchall()
        return [self._row_to_source(r) for r in rows]

    def _row_to_source(self, row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            author=row["author"],
            publish_date=row["publish_date"],
            platform=row["platform"],
            raw_text=row["raw_text"],
            source_class=SourceClass(row["source_class"]) if row["source_class"] else None,
            bias_hint=BiasHint(row["bias_hint"]) if row["bias_hint"] else None,
        )

    # --- Claim-source link operations ---

    def add_claim_source_link(self, link: ClaimSourceLink):
        self._conn.execute(
            """
            INSERT OR IGNORE INTO claim_sources (claim_id, source_id, quote_span_start, quote_span_end)
            VALUES (?, ?, ?, ?)
            """,
            (
                link.claim_id,
                link.source_id,
                link.quote_span_start,
                link.quote_span_end,
            ),
        )
        self._conn.commit()

    def get_all_claim_source_links(self) -> list[ClaimSourceLink]:
        """Get every claim-source link, ordered by (claim_id, source_id).

        Used by src/storage/json_export.py to produce a deterministic,
        diff-stable JSON export of the whole graph.
        """
        rows = self._conn.execute(
            "SELECT * FROM claim_sources ORDER BY claim_id, source_id"
        ).fetchall()
        return [
            ClaimSourceLink(
                claim_id=r["claim_id"],
                source_id=r["source_id"],
                quote_span_start=r["quote_span_start"],
                quote_span_end=r["quote_span_end"],
            )
            for r in rows
        ]

    # --- Query helpers ---

    def get_claims_about(self, node_id: str) -> list[GraphNode]:
        """Get all Claim nodes that have an ABOUT edge targeting node_id."""
        rows = self._conn.execute(
            """
            SELECT n.* FROM nodes n
            JOIN edges e ON e.src_id = n.id AND e.rel_type = 'ABOUT'
            WHERE e.dst_id = ? AND n.type = 'Claim'
            """,
            (node_id,),
        ).fetchall()
        return [
            GraphNode(
                id=r["id"],
                type=NodeType(r["type"]),
                label=r["label"],
                canonical_name=r["canonical_name"],
                metadata=json.loads(r["metadata_json"] or "{}"),
                source_urls=json.loads(r["source_urls_json"] or "[]"),
            )
            for r in rows
        ]

    def get_persons_connected_to_group(self, group_label_substr: str) -> list[tuple[str, str]]:
        """Get (person_label, relation_type) for persons connected to groups matching label substring."""
        rows = self._conn.execute(
            """
            SELECT n.label AS person_label, e.rel_type
            FROM edges e
            JOIN nodes n ON e.src_id = n.id AND n.type = 'Person'
            JOIN nodes g ON e.dst_id = g.id AND g.type = 'Group'
            WHERE g.label LIKE ?
            """,
            (f"%{group_label_substr}%",),
        ).fetchall()
        return [(r["person_label"], r["rel_type"]) for r in rows]

    def get_contradictions(self) -> list[tuple[str, str]]:
        """Get pairs of contradicting claim texts."""
        rows = self._conn.execute(
            """
            SELECT c1.label AS claim1, c2.label AS claim2
            FROM edges e
            JOIN nodes c1 ON e.src_id = c1.id AND c1.type = 'Claim'
            JOIN nodes c2 ON e.dst_id = c2.id AND c2.type = 'Claim'
            WHERE e.rel_type = 'CONTRADICTS'
            """,
        ).fetchall()
        return [(r["claim1"], r["claim2"]) for r in rows]

    def get_node_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()
        return row["c"]

    def get_edge_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()
        return row["c"]

    def get_source_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM sources").fetchone()
        return row["c"]
