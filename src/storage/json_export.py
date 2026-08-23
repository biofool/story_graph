"""
JSON/JSONL export + import for the property graph store.

Source-of-truth model
----------------------
The tracked, version-controlled format for this project's research data is
JSONL under ``graph_snapshot/`` at the repo root — one file per entity type
(``nodes.jsonl``, ``edges.jsonl``, ``sources.jsonl``, ``claim_sources.jsonl``),
one JSON object per line, sorted deterministically so an MR diff only ever
shows what actually changed. SQLite (``data/graph.db``) is just a local
*working copy*: scripts rebuild it from the tracked snapshot at startup
(:func:`import_from_json` / :func:`load_from_json`) and write it back out to
the snapshot when they finish (:func:`export_to_json`). SQLite itself is
never committed — see ``.gitignore``.

This keeps the graph's history reviewable in a merge request instead of
opaque binary diffs, at the cost of JSON/JSONL's usual limits (no indexes,
no concurrent writers, full-file rewrites on export). That tradeoff can be
revisited — e.g. reverting to SQLite as the tracked format, or moving to a
real server-side DB — if the graph grows large enough for JSON export/import
or diffing to become a real performance problem. Until then, GraphDB stays
the only place that knows how to read/write the graph; this module only
translates between it and the two on-disk representations.

Each line is the JSON shape of the corresponding pydantic model in
src/storage/models.py (``GraphNode``, ``GraphEdge``, ``SourceRecord``,
``ClaimSourceLink``), via ``.model_dump(mode="json")`` — so enum fields
serialize as their plain string values, not ``Enum.NAME``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from src.storage.graph_db import GraphDB
from src.storage.models import (
    ClaimSourceLink,
    GraphEdge,
    GraphNode,
    SourceRecord,
)

NODES_FILENAME = "nodes.jsonl"
EDGES_FILENAME = "edges.jsonl"
SOURCES_FILENAME = "sources.jsonl"
CLAIM_SOURCES_FILENAME = "claim_sources.jsonl"

ALL_FILENAMES = (NODES_FILENAME, EDGES_FILENAME, SOURCES_FILENAME, CLAIM_SOURCES_FILENAME)


def _write_jsonl(path: Path, rows: list) -> None:
    """Write one JSON object per line, each on its own line with sorted
    object keys (keeps line-level diffs minimal even if a model gains a
    field whose alphabetical position shifts unrelated keys)."""
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row.model_dump(mode="json"), sort_keys=True))
            f.write("\n")


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def snapshot_exists(snapshot_dir: str | Path) -> bool:
    """True if ``snapshot_dir`` holds a JSONL snapshot worth loading.

    Used by scripts to decide, at startup, whether to rebuild the local
    SQLite working copy from the tracked snapshot or start from an empty
    graph (e.g. first run, before any snapshot has been committed).
    """
    return (Path(snapshot_dir) / NODES_FILENAME).exists()


def export_to_json(db: GraphDB, snapshot_dir: str | Path) -> dict[str, int]:
    """Serialize the full graph held by ``db`` into JSONL files under
    ``snapshot_dir`` (created if needed): ``nodes.jsonl``, ``edges.jsonl``,
    ``sources.jsonl``, ``claim_sources.jsonl``.

    Rows in every file are sorted by id (edges and claim-source links, which
    have no single id column, sort by their natural composite key instead)
    so re-exporting an unchanged graph reproduces byte-identical files —
    that determinism is what keeps the tracked snapshot's git history
    reviewable rather than churning on row order alone.

    Returns ``{filename: row_count}``, e.g. for a run summary.
    """
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    nodes = sorted(db.get_all_nodes(), key=lambda n: n.id)
    edges = sorted(db.get_all_edges(), key=lambda e: (e.src_id, e.rel_type.value, e.dst_id))
    sources = sorted(db.get_all_sources(), key=lambda s: s.id)
    claim_sources = sorted(
        db.get_all_claim_source_links(), key=lambda c: (c.claim_id, c.source_id)
    )

    _write_jsonl(snapshot_dir / NODES_FILENAME, nodes)
    _write_jsonl(snapshot_dir / EDGES_FILENAME, edges)
    _write_jsonl(snapshot_dir / SOURCES_FILENAME, sources)
    _write_jsonl(snapshot_dir / CLAIM_SOURCES_FILENAME, claim_sources)

    return {
        NODES_FILENAME: len(nodes),
        EDGES_FILENAME: len(edges),
        SOURCES_FILENAME: len(sources),
        CLAIM_SOURCES_FILENAME: len(claim_sources),
    }


def import_from_json(snapshot_dir: str | Path, db_path: str | Path) -> GraphDB:
    """Rebuild a fresh local SQLite working copy at ``db_path`` from the
    tracked JSONL snapshot in ``snapshot_dir``.

    Any file already at ``db_path`` is deleted first: the JSON snapshot is
    the source of truth, so the local SQLite copy is always rebuilt from it
    rather than merged with whatever happened to be on disk. If
    ``snapshot_dir`` has no ``nodes.jsonl`` yet (e.g. the very first run,
    before any snapshot has been committed), this just returns a fresh,
    empty ``GraphDB`` — see :func:`snapshot_exists`.

    Returns the open ``GraphDB``; the caller owns it and is responsible for
    closing it (or using it as a context manager), same as constructing a
    ``GraphDB`` directly.
    """
    snapshot_dir = Path(snapshot_dir)
    db_path = Path(db_path)
    if db_path.exists():
        db_path.unlink()

    db = GraphDB(db_path)
    if not snapshot_exists(snapshot_dir):
        return db

    for row in _read_jsonl(snapshot_dir / NODES_FILENAME):
        db.add_node(GraphNode(**row))
    for row in _read_jsonl(snapshot_dir / EDGES_FILENAME):
        db.add_edge(GraphEdge(**row))
    for row in _read_jsonl(snapshot_dir / SOURCES_FILENAME):
        db.add_source(SourceRecord(**row))
    for row in _read_jsonl(snapshot_dir / CLAIM_SOURCES_FILENAME):
        db.add_claim_source_link(ClaimSourceLink(**row))

    return db


# Scripts read more naturally calling "load the snapshot into a local
# working copy at startup" than "import from json" — same function, kept as
# a plain alias rather than a wrapper so there is exactly one implementation
# to maintain.
load_from_json = import_from_json
