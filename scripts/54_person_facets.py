#!/usr/bin/env python3
"""Generic person-facet / work-history encoder, driven by a JSON file.

Replaces per-person facet scripts. Usage:

    python scripts/54_person_facets.py --input data/facets/richard-moon.json
    python scripts/54_person_facets.py --input data/facets/richard-moon.json --dry-run

JSON schema (all sections optional):

{
  "person": {
    "canonical_id": "person:richard-moon-aikido",
    "aliases": ["person-richard-moon"],       // also get roles/facets
    "roles": ["aikido_teacher", ...],          // metadata.roles
    "facets": {"aikido_teacher": "...", ...},  // metadata.facets
    "facets_source": "kkron personal communication 2026-09-22"
  },
  "nodes": [    // stub nodes to upsert (existing metadata is merged)
    {"id": "group:x", "type": "Group", "label": "X", "metadata": {...}}
  ],
  "edges": [    // INSERT OR IGNORE
    {"src": "person:a", "rel": "WORKED_AT", "dst": "group:x",
     "source": "kkron personal communication 2026-09-22"}
  ],
  "claims": [   // Claim node + ABOUT / ASSERTED_BY edges
    {"id": "claim:kkron:x", "label": "...",
     "metadata": {...},
     "about": ["person:a"], "asserted_by": "person:a"}
  ],
  "distinct_from": [  // collision guard on OTHER nodes
    {"node": "person:richard-moon-chef", "note": "Australian chef — different person"}
  ]
}

Idempotent via INSERT OR IGNORE / metadata merge.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone

DB = "data/graph.db"
NOW = datetime.now(timezone.utc).isoformat()


def upsert_node(cur, nid, ntype, label, metadata):
    cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (nid,))
    row = cur.fetchone()
    if row:
        m = json.loads(row[0] or "{}")
        m.update(metadata or {})
        cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                    (json.dumps(m), nid))
    else:
        cur.execute("INSERT INTO nodes (id,type,label,metadata_json) VALUES (?,?,?,?)",
                    (nid, ntype, label, json.dumps(metadata or {})))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="facet JSON file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=DB)
    args = ap.parse_args()

    spec = json.load(open(args.input))
    cur = sqlite3.connect(args.db).cursor()
    actions = []
    dry = args.dry_run

    # 1. roles + facets on canonical and alias nodes
    person = spec.get("person") or {}
    canon = person.get("canonical_id")
    for nid in [canon] + person.get("aliases", []):
        if not nid:
            continue
        meta = {}
        if person.get("roles"):
            meta["roles"] = person["roles"]
        if person.get("facets"):
            meta["facets"] = person["facets"]
        if person.get("facets_source"):
            meta["facets_source"] = person["facets_source"]
        if not meta:
            continue
        cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (nid,))
        m = json.loads((cur.fetchone() or ["{}"])[0] or "{}")
        m.update(meta)
        if not dry:
            cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                        (json.dumps(m), nid))
        actions.append(f"roles+facets -> {nid}")

    # 2. stub nodes
    for n in spec.get("nodes", []):
        if not dry:
            upsert_node(cur, n["id"], n.get("type", "Group"),
                        n.get("label", n["id"]), n.get("metadata"))
        actions.append(f"node -> {n['id']}")

    # 3. edges
    for e in spec.get("edges", []):
        if not dry:
            cur.execute(
                "INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id,metadata_json) "
                "VALUES (?,?,?,?)",
                (e["src"], e["rel"], e["dst"],
                 json.dumps({"source": e.get("source", args.input)})))
        actions.append(f"{e['src']} -[{e['rel']}]-> {e['dst']}")

    # 4. claims (+ ABOUT / ASSERTED_BY edges)
    for c in spec.get("claims", []):
        md = dict(c.get("metadata") or {})
        md.setdefault("asserted_at", NOW)
        if not dry:
            upsert_node(cur, c["id"], "Claim", c["label"], md)
            for dst in c.get("about", []):
                cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) "
                            "VALUES (?,?,?)", (c["id"], "ABOUT", dst))
            if c.get("asserted_by"):
                cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) "
                            "VALUES (?,?,?)", (c["id"], "ASSERTED_BY", c["asserted_by"]))
        actions.append(f"claim -> {c['id']}")

    # 5. distinct_from guards on other nodes
    for g in spec.get("distinct_from", []):
        cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (g["node"],))
        row = cur.fetchone()
        if not row:
            continue
        m = json.loads(row[0] or "{}")
        m["distinct_from"] = canon
        m["distinct_note"] = g["note"]
        if not dry:
            cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                        (json.dumps(m), g["node"]))
        actions.append(f"distinct_from guard -> {g['node']}")

    if not dry:
        cur.connection.commit()
    print(("DRY-RUN " if dry else "") + f"{len(actions)} actions:")
    for a in actions:
        print("  " + a)


if __name__ == "__main__":
    main()
