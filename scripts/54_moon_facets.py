#!/usr/bin/env python3
"""Encode Richard Moon's unified multi-facet identity (kkron assertion 2026-09-22).

kkron asserts: the aikido Richard Moon is ONE person across facets —
aikido teacher, chef, musician, executive coach, peace negotiator.
Per AGENTS.md, kkron assertions are first-class evidence and go in the
graph by default.

What this encodes:
  - roles + facet detail on person:richard-moon-aikido (canonical) and
    person-richard-moon (alias)
  - WORKED_AT edges: The Source restaurant, Aware Inn (kkron claims)
  - CREATED edges: moonsic.com music works, extraordinarylistening.com,
    Teriyaki Age (already present)
  - MEMBER_OF Cyprus Peace Training Team on the canonical node (alias
    node already has it)
  - claim:kkron:moon-unified-identity — the explicit unified-facet claim
  - distinct_from guard on person:richard-moon-chef (the AUSTRALIAN chef —
    a different person; the "chef" facet is Source/La Cocina era)

Idempotent via INSERT OR IGNORE / metadata upsert.
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone

DB = "data/graph.db"
CANON = "person:richard-moon-aikido"
ALIAS = "person-richard-moon"
AU_CHEF = "person:richard-moon-chef"
NOW = datetime.now(timezone.utc).isoformat()

ROLES = ["aikido_teacher", "chef", "musician", "executive_coach", "peace_builder"]

FACETS = {
    "aikido_teacher": "6th dan; founder/chief instructor Aikido of Marin; co-founder City Aikido SF; 50+ year student of Robert Nadeau; guest teaching NZ/Europe since ~1987",
    "chef": "Worked at The Source restaurant (Sunset Strip) and the Aware Inn during the Source Family era; later food work incl. Teriyaki Age product and La Cocina SF Street Food Festival",
    "musician": "moonsic.com — R. Moon 'Moon Music' (Moon Rocks, Moon Tunes); US copyright registrations list 'Richard Moon, 1946-' on San Anselmo CA music releases",
    "executive_coach": "Performance Edge consultancy with Chris Thorsen — 'Aikido and Dialogue' organizational-learning programs; Open Mind Adventures; Extraordinary Listening communications program",
    "peace_builder": "Cyprus Peace Training Team (IMTD/Fulbright consortium behind the CRTG); IMTD Lake Trails camp 1999 teaching aikido as conflict-resolution tool feeding Bosnia YLA; senior associate Nautilus Institute",
}

EDGES = [
    (CANON, "WORKED_AT", "group:the-source-restaurant", "kkron personal communication 2026-09-22; claim:kkron:218252fe4b9771cb"),
    (CANON, "WORKED_AT", "group:aware-inn", "kkron personal communication 2026-09-22; claim:kkron:0e842747e2d98504"),
    (CANON, "WORKED_AT", "group:second-aware-inn", "kkron personal communication 2026-09-22; claim:kkron:0e842747e2d98504"),
    (CANON, "CREATED", "work:moonsic:rmoon", "moonsic.com R. Moon Moon Music; kkron 2026-09-22"),
    (CANON, "CREATED", "work:moonsic:home", "moonsic.com; kkron 2026-09-22"),
    (CANON, "CREATED", "work:b0b53e646a2cdd0e", "extraordinarylistening.com; kkron 2026-09-22"),
    (CANON, "MEMBER_OF", "group-cyprus-peace-training-team", "mirrored from alias node; Riai bio / IMTD"),
]

UNIFIED_CLAIM = {
    "id": "claim:kkron:moon-unified-identity",
    "label": "kkron: Richard Moon (aikidoka, b.1946) is one person across roles — aikido teacher, chef, musician, executive coach, peace negotiator",
    "metadata": {
        "claim_text": "The aikido Richard Moon is the same person as the chef (Source restaurant / Aware Inn era, later Teriyaki Age / La Cocina), the musician (moonsic.com, 1946- copyright releases), the executive coach (Performance Edge, Extraordinary Listening, Open Mind Adventures), and the peace negotiator (Cyprus PTT, IMTD, Bosnia).",
        "claim_type": "biographical",
        "stance": "asserting",
        "confidence": 0.95,
        "evidence_mode": "first_person",
        "platform": "kkron (personal communication)",
        "source_class": "verbal_confirmation",
        "source_url": "kkron://personal-communication",
        "asserted_at": NOW,
    },
}


def upsert_node(cur, nid, ntype, label, metadata):
    cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (nid,))
    row = cur.fetchone()
    if row:
        m = json.loads(row[0] or "{}")
        m.update(metadata)
        cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                    (json.dumps(m), nid))
    else:
        cur.execute("INSERT INTO nodes (id,type,label,metadata_json) VALUES (?,?,?,?)",
                    (nid, ntype, label, json.dumps(metadata)))


def main():
    dry = "--dry-run" in sys.argv
    cur = sqlite3.connect(DB).cursor()
    actions = []

    # 1. roles + facets on canonical and alias nodes
    for nid in (CANON, ALIAS):
        cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (nid,))
        m = json.loads((cur.fetchone() or ["{}"])[0] or "{}")
        m["roles"] = ROLES
        m["facets"] = FACETS
        m["facets_source"] = "kkron personal communication 2026-09-22"
        if not dry:
            cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                        (json.dumps(m), nid))
        actions.append(f"roles+facets -> {nid}")

    # 2. edges
    for src, rel, dst, src_note in EDGES:
        if not dry:
            cur.execute(
                "INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id,metadata_json) VALUES (?,?,?,?)",
                (src, rel, dst, json.dumps({"source": src_note})))
        actions.append(f"{src} -[{rel}]-> {dst}")

    # 3. unified identity claim + edges
    c = UNIFIED_CLAIM
    if not dry:
        upsert_node(cur, c["id"], "Claim", c["label"], c["metadata"])
        for rel, dst in [("ABOUT", CANON), ("ABOUT", ALIAS)]:
            cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) VALUES (?,?,?)",
                        (c["id"], rel, dst))
        cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) VALUES (?,?,?)",
                    (c["id"], "ASSERTED_BY", CANON))
    actions.append("claim:kkron:moon-unified-identity")

    # 4. guard the Australian chef node
    cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (AU_CHEF,))
    row = cur.fetchone()
    if row:
        m = json.loads(row[0] or "{}")
        m["distinct_from"] = CANON
        m["distinct_note"] = ("Australian chef (Blue Mountains, 'Moon on a Spoon'). "
                              "NOT the Source/La Cocina chef facet of the aikido Moon — "
                              "those are different Richard Moons.")
        if not dry:
            cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                        (json.dumps(m), AU_CHEF))
        actions.append(f"distinct_from guard -> {AU_CHEF}")

    if not dry:
        cur.connection.commit()
    print(("DRY-RUN " if dry else "") + f"{len(actions)} actions:")
    for a in actions:
        print("  " + a)


if __name__ == "__main__":
    main()
