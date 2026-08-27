#!/usr/bin/env python3
"""One-off fix: remove kkron://personal-communication from entity nodes' source_urls.

Entity nodes (Person, Group, Place, Event) had `kkron://personal-communication`
incorrectly added to their `source_urls` by `_ensure_entity_node()` in
`scripts/_targeted_research_helpers.py`. That URL is a source for kkron's
*claims* (stored on the Claim node), not for the entities' existence or
metadata. The code fix is in _ensure_entity_node (now accepts source_url=None);
this script cleans up the existing data in both the SQLite DB and the
graph_snapshot/nodes.jsonl file.

Excluded from cleanup (kkron URL is legitimate there):
  - Claim nodes (claims are sourced from kkron's testimony)
  - person:kkron-project-owner (kkron himself)
  - work:kkron-personal-communication (the Work node for kkron's communication)

Usage:
    python scripts/fix/remove_kkron_urls_from_entities.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.storage.graph_db import GraphDB

KKRON_URL = "kkron://personal-communication"

# Node IDs where the kkron URL is legitimate and should NOT be removed.
_EXCLUDE_IDS = {
    "person:kkron-project-owner",
    "work:kkron-personal-communication",
}


def fix_db(db_path: Path, dry_run: bool) -> int:
    """Remove kkron URL from entity nodes in the SQLite DB. Returns count fixed."""
    db = GraphDB(db_path)
    fixed = 0
    for node in db.get_all_nodes():
        if node.type.value == "Claim":
            continue
        if node.id in _EXCLUDE_IDS:
            continue
        if KKRON_URL not in node.source_urls:
            continue

        new_urls = [u for u in node.source_urls if u != KKRON_URL]
        if dry_run:
            print(f"  [DRY RUN] Would fix {node.id} ({node.type.value}): "
                  f"{len(node.source_urls)} -> {len(new_urls)} source_urls")
        else:
            # Direct SQL update — we only want to change source_urls_json,
            # not touch label/canonical_name/metadata (which add_node's
            # upsert merge might alter).
            db._get_conn().execute(
                "UPDATE nodes SET source_urls_json = ? WHERE id = ?",
                (json.dumps(new_urls), node.id),
            )
            print(f"  Fixed {node.id} ({node.type.value}): "
                  f"removed kkron URL, {len(new_urls)} source_urls remain")
        fixed += 1

    if not dry_run:
        db._get_conn().commit()
    db.close()
    return fixed


def fix_snapshot(snapshot_dir: Path, dry_run: bool) -> int:
    """Remove kkron URL from entity nodes in graph_snapshot/nodes.jsonl.
    Returns count fixed."""
    nodes_file = snapshot_dir / "nodes.jsonl"
    if not nodes_file.exists():
        print(f"  Snapshot file not found: {nodes_file}")
        return 0

    fixed = 0
    lines = nodes_file.read_text(encoding="utf-8").splitlines()
    new_lines = []
    for line in lines:
        if not line.strip():
            new_lines.append(line)
            continue
        obj = json.loads(line)
        ntype = obj.get("type", "")
        nid = obj.get("id", "")
        if ntype == "Claim" or nid in _EXCLUDE_IDS:
            new_lines.append(line)
            continue
        urls = obj.get("source_urls", [])
        if KKRON_URL not in urls:
            new_lines.append(line)
            continue

        new_urls = [u for u in urls if u != KKRON_URL]
        obj["source_urls"] = new_urls
        new_lines.append(json.dumps(obj, ensure_ascii=False))
        if dry_run:
            print(f"  [DRY RUN] Would fix snapshot node {nid} ({ntype})")
        else:
            print(f"  Fixed snapshot node {nid} ({ntype})")
        fixed += 1

    if not dry_run and fixed > 0:
        nodes_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return fixed


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    p.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "graph.db",
                   help="Path to graph.db")
    p.add_argument("--snapshot-dir", type=Path, default=PROJECT_ROOT / "graph_snapshot",
                   help="Path to graph_snapshot/ directory")
    args = p.parse_args(argv)

    print(f"Removing '{KKRON_URL}' from entity nodes (excluding Claims, "
          f"person:kkron-project-owner, work:kkron-personal-communication)")
    print(f"  DB: {args.db}")
    print(f"  Snapshot: {args.snapshot_dir}")
    print()

    print("Fixing SQLite DB:")
    db_fixed = fix_db(args.db, args.dry_run)
    print(f"  {'Would fix' if args.dry_run else 'Fixed'} {db_fixed} node(s) in DB")
    print()

    print("Fixing graph_snapshot/nodes.jsonl:")
    snap_fixed = fix_snapshot(args.snapshot_dir, args.dry_run)
    print(f"  {'Would fix' if args.dry_run else 'Fixed'} {snap_fixed} node(s) in snapshot")
    print()

    print(f"Total: {'would fix' if args.dry_run else 'fixed'} {db_fixed + snap_fixed} node(s)")


if __name__ == "__main__":
    main()
