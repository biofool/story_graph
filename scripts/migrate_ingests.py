#!/usr/bin/env python3
"""
One-shot migration: replay each legacy ingest script against a scratch DB
seeded from graph_snapshot, capture every graph write (add_node/add_edge/
add_source/add_claim_source_link — recorded via a GraphDB wrapper — plus
raw-SQL writes and deletions caught by a before/after diff), and emit a
declarative data/ingest/<name>.json for scripts/ingest.py.

Usage:
    python scripts/migrate_ingests.py                # all scripts in RUNS
    python scripts/migrate_ingests.py --only 27,46   # subset
"""

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.json_export import import_from_json
from src.storage.models import GraphEdge, GraphNode, SourceRecord

SNAPSHOT = PROJECT_ROOT / "graph_snapshot"
OUT_DIR = PROJECT_ROOT / "data" / "ingest"

# (json_name, script_filename, argv, seed)
#   seed "db"    = scratch is a copy of data/graph.db (keeps lineage_* tables)
#   seed "empty" = bare schema (for scripts that crash on existing rows or
#                  skip work when records already exist)
RUNS = [
    ("laist_article", "05_ingest_laist_article.py", [], "db"),
    ("moonsic", "12_ingest_moonsic.py", ["--no-export"], "both"),
    # 13 links sheet rows to existing persons/groups by name lookup —
    # db-seed only; empty-scratch would mint duplicate ids.
    ("yoga_abuse_sheet", "13_ingest_yoga_abuse_sheet.py",
     ["--local", "data/yoga_abuse_research_sheet.csv", "--no-export"], "db"),
    ("deslippe_paper", "14_ingest_deslippe_paper.py", ["--no-export"], "db"),
    ("pbs_artbound", "16_ingest_pbs_artbound.py", ["--no-export"], "db"),
    ("nadeau_relationships", "23_ingest_nadeau_relationships.py",
     ["--no-export"], "db"),
    ("peter_ralston", "25_ingest_peter_ralston.py", ["--no-export"], "db"),
    ("ralston_noha", "28_ingest_ralston_noha.py", [], "both"),
    ("nadeau_russia_seminars", "29_ingest_nadeau_russia_seminars.py", [], "both"),
    # crashes on seeded db (raw INSERT into sources, no upsert)
    ("pbs_artbound_new_aquarians", "29_ingest_pbs_artbound_new_aquarians.py",
     ["--no-export"], "empty"),
    ("moon_ralston_edge", "30_ingest_moon_ralston_edge.py", [], "both"),
    # skips sources already present — needs empty seed to capture them
    ("jack_wada", "31_ingest_jack_wada.py", [], "both"),
    ("aikiweb_ikeda_bridge", "46_ingest_aikiweb_seminars.py", [], "db"),
    ("moon_newspaper_events", "47_ingest_moon_newspaper_events.py", [], "db"),
    ("moon_europe_peacework", "49_ingest_moon_europe_peacework.py", [], "db"),
    ("issue50_findings", "51_ingest_issue50_findings.py", [], "db"),
    ("academia_peacebuilding_bundle", "56_ingest_academia_peacebuilding_bundle.py", [], "both"),
    ("ikeda_dojos", "27_add_ikeda_dojos.py", ["--no-export"], "db"),
    ("peterson_interview", "04_add_peterson_interview.py", [], "db"),
    ("aikidojournal_article", "16_ingest_aikidojournal.py", ["--no-export"], "db"),
    ("kkron_kufferath_nadeau_bunch", "18_add_kkron_assertions.py",
     ["--no-export"], "db"),
    ("dan_millman_sources", "20_ingest_dan_millman.py", ["--no-export"], "db"),
    ("dan_millman_person", "21_add_dan_millman_person.py", ["--no-export"], "db"),
    ("kkron_dojo_origins", "40_add_kkron_dojo_origins.py", ["--no-export"], "db"),
    ("nadeau_russia_search_sources",
     "ingest_nadeau_russia_search_sources.py", [], "db"),
    ("nadeau_russia_sources", "ingest_nadeau_russia_sources.py", [], "db"),
    ("ralston_netherlands_sources",
     "ingest_ralston_netherlands_sources.py", [], "db"),
]


class RecDB:
    """Wraps a real GraphDB on the scratch db; records every write call
    while delegating reads (and raw _conn access) to the real db."""

    def __init__(self, inner: GraphDB, rec: dict):
        self._db = inner
        self._rec = rec

    # writes — recorded AND applied
    def add_node(self, n: GraphNode):
        self._rec["nodes"][n.id] = n
        self._db.add_node(n)

    def add_edge(self, e: GraphEdge):
        self._rec["edges"][(e.src_id, e.rel_type.value, e.dst_id)] = e
        self._db.add_edge(e)

    def add_source(self, s: SourceRecord):
        self._rec["sources"][s.id] = s
        self._db.add_source(s)

    def add_claim_source_link(self, l):
        self._rec["claim_sources"][(l.claim_id, l.source_id)] = l
        self._db.add_claim_source_link(l)

    # context-manager + attribute passthrough
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._db.close()
        return None

    def __getattr__(self, k):
        return getattr(self._db, k)


def dump_state(db: GraphDB) -> dict:
    return {
        "nodes": {n.id: n.model_dump(mode="json") for n in db.get_all_nodes()},
        "edges": {
            (e.src_id, e.rel_type.value, e.dst_id): e.model_dump(mode="json")
            for e in db.get_all_edges()
        },
        "sources": {s.id: s.model_dump(mode="json") for s in db.get_all_sources()},
        "claim_sources": {
            (l.claim_id, l.source_id): l.model_dump(mode="json")
            for l in db.get_all_claim_source_links()
        },
    }


def load_module(script: str):
    spec = importlib.util.spec_from_file_location(
        f"legacy_{Path(script).stem.replace('.', '_')}",
        PROJECT_ROOT / "scripts" / script,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_script(script: str, argv: list[str], scratch: Path, seed: str) -> tuple[dict, dict, dict]:
    """Run a legacy script against scratch. Returns (recorded, before, after)."""
    rec = {"nodes": {}, "edges": {}, "sources": {}, "claim_sources": {}}
    if seed == "db":
        # copy the live db as-is: it carries lineage_* tables that aren't
        # in the JSONL snapshot, and its graph tables are already synced
        # (every recent ingest rebuilds graph.db from the snapshot).
        shutil.copy(PROJECT_ROOT / "data" / "graph.db", scratch)
    seeded_db = GraphDB(scratch)  # "empty" seed: bare schema
    recdb = RecDB(seeded_db, rec)
    # lineage_* tables are created by scripts/26, not LineageDB itself —
    # apply its DDL so scripts 28/29/30 can read/write them on scratch.
    import sqlite3 as _sq
    _lin = load_module("26_create_lineage_tables.py")
    _c = _sq.connect(str(scratch)); _c.executescript(_lin.LINEAGE_DDL); _c.close()
    before = dump_state(seeded_db)

    mod = load_module(script)
    # Every GraphDB(...) the script constructs writes to the scratch db.
    mod.GraphDB = lambda *a, **k: recdb
    if hasattr(mod, "import_from_json"):
        mod.import_from_json = lambda *a, **k: recdb
    if hasattr(mod, "export_to_json"):
        mod.export_to_json = lambda *a, **k: {}
    # Raw-sqlite side channels (sqlite3.connect(settings.graph_db_abs_path)
    # or module constants like DB / GRAPH_DB) -> scratch too.
    for const in ("DB", "GRAPH_DB", "DB_PATH"):
        if hasattr(mod, const):
            setattr(mod, const, str(scratch))

    # Raw-sqlite side channels via settings.graph_db_abs_path -> scratch.
    settings_cls = type(settings)
    orig_prop = settings_cls.graph_db_abs_path
    settings_cls.graph_db_abs_path = property(lambda self: scratch)

    old_argv = sys.argv
    sys.argv = [script] + argv
    try:
        mod.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
        settings_cls.graph_db_abs_path = orig_prop

    after = dump_state(GraphDB(scratch))
    return rec, before, after


def run_one(json_name: str, script: str, argv: list[str], seed: str) -> dict:
    tmp = Path(tempfile.mkdtemp())
    captures = []
    seeds = ["db", "empty"] if seed == "both" else [seed]
    for s in seeds:
        scratch = tmp / f"{s}.db"
        try:
            captures.append(_run_script(script, argv, scratch, s))
        except Exception as e:
            print(f"  [{s}] FAILED: {type(e).__name__}: {e}")

    # Merge: recorded add_* calls (script intent) + before/after diffs
    # (raw-SQL writes, deletions). db-seeded capture wins for shared keys;
    # empty-seed capture adds items skipped by exists-checks.
    rec = {"nodes": {}, "edges": {}, "sources": {}, "claim_sources": {}}
    diffs = {"nodes": {}, "edges": {}, "sources": {}, "claim_sources": {}}
    deleted_edges = {}
    # db-seeded capture wins on key conflicts: apply empty first, db last.
    for r, before, after in reversed(captures):
        for k in rec:
            rec[k].update(r[k])
    for r, before, after in captures:
        for key, n in after["nodes"].items():
            if key not in before["nodes"] or before["nodes"][key] != n:
                diffs["nodes"].setdefault(key, n)
        for key, e in after["edges"].items():
            if key not in before["edges"]:
                diffs["edges"].setdefault(key, e)
        for key, s_ in after["sources"].items():
            if key not in before["sources"] or before["sources"][key] != s_:
                diffs["sources"].setdefault(key, s_)
        for key, l in after["claim_sources"].items():
            if key not in before["claim_sources"]:
                diffs["claim_sources"].setdefault(key, l)
        for key in before["edges"]:
            if key not in after["edges"]:
                deleted_edges.setdefault(key,
                    {"src_id": key[0], "rel_type": key[1], "dst_id": key[2]})

    out = {"name": json_name,
           "description": f"Migrated from scripts/{script} (now deleted).",
           "migrated_from": f"scripts/{script}"}
    out["nodes"] = [n.model_dump(mode="json") for n in rec["nodes"].values()]
    out["nodes"] += [n for k, n in diffs["nodes"].items()
                     if k not in rec["nodes"]]
    out["edges"] = [e.model_dump(mode="json") for e in rec["edges"].values()]
    out["edges"] += [e for k, e in diffs["edges"].items()
                     if k not in rec["edges"]]
    out["sources"] = [s.model_dump(mode="json") for s in rec["sources"].values()]
    out["sources"] += [s for k, s in diffs["sources"].items()
                       if k not in rec["sources"]]
    out["claim_sources"] = [
        l.model_dump(mode="json") for l in rec["claim_sources"].values()]
    out["claim_sources"] += [l for k, l in diffs["claim_sources"].items()
                             if k not in rec["claim_sources"]]
    if deleted_edges:
        out["delete_edges"] = list(deleted_edges.values())
    for k in ("nodes", "edges", "sources", "claim_sources"):
        if not out[k]:
            del out[k]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="comma-separated script prefixes")
    args = ap.parse_args()
    only = args.only.split(",") if args.only else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for json_name, script, argv, seed in RUNS:
        if only and not any(script.startswith(o) for o in only):
            continue
        print(f"=== {script} -> data/ingest/{json_name}.json [{seed}]")
        try:
            spec = run_one(json_name, script, argv, seed)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            continue
        counts = {k: len(v) for k, v in spec.items()
                  if isinstance(v, list)}
        print(f"  captured: {counts}")
        (OUT_DIR / f"{json_name}.json").write_text(
            json.dumps(spec, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
