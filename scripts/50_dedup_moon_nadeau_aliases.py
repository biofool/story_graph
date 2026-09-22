#!/usr/bin/env python3
"""Dedup fix-ups for issue #50.

- person-richard-moon (Source Family era) ALIAS_OF person:richard-moon-aikido
  (same human — aikido instructor is the former Source Family member)
- person:nadeau-shihan ALIAS_OF person:robert-nadeau
- Moon + Nadeau CO_APPEARANCE edges on the 2019 Riai Auckland workshop
  ('O Sensei Revisited Down Under', Mar 16-18 2019 — aikidotravel.com)

Usage:
    python scripts/50_dedup_moon_nadeau_aliases.py --dry-run
    python scripts/50_dedup_moon_nadeau_aliases.py
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphEdge, RelationType

GRAPH_DB = "data/graph.db"

EDGES = [
    ("person-richard-moon", RelationType.ALIAS_OF,
     "person:richard-moon-aikido",
     {"context": "same person — Source Family member is the aikido "
                 "instructor; dedup per issue #50"}),
    ("person:nadeau-shihan", RelationType.ALIAS_OF,
     "person:robert-nadeau",
     {"context": "duplicate node for Robert Nadeau; dedup per issue #50"}),
    ("person:richard-moon-aikido", RelationType.CO_APPEARANCE,
     "event:o-sensei-revisited-down-under-workshop",
     {"role": "instructor", "dates": "2019-03-16..18",
      "source_url": "https://aikidotravel.com/seminar/481/"
                    "the-osensei-revisited-down-under-workshop"}),
    ("person:robert-nadeau", RelationType.CO_APPEARANCE,
     "event:o-sensei-revisited-down-under-workshop",
     {"role": "instructor", "dates": "2019-03-16..18",
      "source_url": "https://aikidotravel.com/seminar/481/"
                    "the-osensei-revisited-down-under-workshop"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = GraphDB(GRAPH_DB)
    for src, rel, dst, md in EDGES:
        missing = [x for x in (src, dst) if not db.get_node(x)]
        if missing:
            print(f"SKIP {src}->{dst}: missing {missing}")
            continue
        print(f"{'would add' if args.dry_run else 'upserting'} "
              f"{src} -[{rel.value}]-> {dst}")
        if not args.dry_run:
            db.add_edge(GraphEdge(src_id=src, rel_type=rel, dst_id=dst,
                                  metadata=md))
    db.close()


if __name__ == "__main__":
    main()
