#!/usr/bin/env python3
"""Ingest the Academia.edu Cyprus peacebuilding bundle into the graph.

Source: ~/Academia.edu_Bundle_-_The_Impacts_of_Peacebuilding_Work_on_the.zip
Extracted to: data/reference/cyprus/academia_peacebuilding_bundle/
Main paper: Hadjipavlou & Kanol, "The Impacts of Peacebuilding Work on the
Cyprus Conflict", CDA Reflecting on Peace Practice, Feb 2008.

Resolves the OPEN LEAD in claim:kkron:26412d9781ccb0ec — kkron reported a
2008 case study listing Chris Thorsen hired by the Cyprus Consortium in 1995
under "Aikido"; this bundle contains that case study (timeline entry on
p.63: "Aikido, Chris Thorsen, hired by Cyprus Consortium").

Usage:
    python scripts/56_ingest_academia_peacebuilding_bundle.py [--dry-run]
"""
import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = "data/graph.db"
BUNDLE = Path("data/reference/cyprus/academia_peacebuilding_bundle")
NOW = datetime.now(timezone.utc).isoformat()

MAIN = "The_Impacts_of_Peacebuilding_Work_on_the.pdf"
MAIN_ID = "work:academia:impacts-peacebuilding-cyprus-2008"

# Verified text hits in the main paper -> MENTIONS edges
MAIN_MENTIONS = [
    "person:christopher-thorsen",       # "Aikido, Chris Thorsen, hired by Cyprus Consortium" (1995)
    "group:cyprus-consortium",          # 13 mentions
    "group:cyprus-fulbright-commission",  # 17 mentions
    "person:louise-diamond",            # 8 mentions
]

OPEN_LEAD = "claim:kkron:26412d9781ccb0ec"


def slugify(name: str) -> str:
    import re
    s = re.sub(r"\.(pdf|docx?|txt)$", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:80]


def upsert(cur, nid, ntype, label, metadata):
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run
    cur = sqlite3.connect(DB).cursor()
    actions = []

    docs = sorted(p for p in BUNDLE.rglob("*")
                  if p.suffix.lower() in (".pdf", ".doc", ".docx"))
    for p in docs:
        rel = p.relative_to(BUNDLE)
        nid = MAIN_ID if p.name == MAIN else f"work:academia:{slugify(p.name)}"
        txt = p.with_suffix(".txt")
        meta = {
            "work_type": p.suffix.lstrip("."),
            "local_archive": str(p),
            "text_archive": str(txt) if txt.exists() else None,
            "bundle": "Academia.edu — Impacts of Peacebuilding Work (Cyprus)",
            "folder": str(rel.parent) if str(rel.parent) != "." else None,
            "sha1": hashlib.sha1(p.read_bytes()).hexdigest(),
            "ingested_at": NOW,
        }
        if p.name == MAIN:
            meta.update({
                "title": "The Impacts of Peacebuilding Work on the Cyprus Conflict",
                "authors": ["Maria Hadjipavlou", "Bulent Kanol"],
                "publisher": "CDA Collaborative Learning Projects — Reflecting on Peace Practice",
                "date": "2008-02",
                "key_evidence": "p.63 timeline: 'Aikido, Chris Thorsen, hired by Cyprus Consortium' (1995)",
            })
        if not dry:
            upsert(cur, nid, "Work", meta.get("title") or p.name, meta)
        actions.append(f"work -> {nid}")

    # MENTIONS edges for verified hits in the main paper
    for dst in MAIN_MENTIONS:
        if not dry:
            cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id,metadata_json) "
                        "VALUES (?,?,?,?)",
                        (MAIN_ID, "MENTIONS", dst,
                         json.dumps({"source": "text grep of extracted PDF"})))
        actions.append(f"{MAIN_ID} -[MENTIONS]-> {dst}")

    # Located-document claim (the evidence text itself)
    cid = "claim:citation:hadjipavlou-kanol-2008-aikido-thorsen"
    if not dry:
        upsert(cur, cid, "Claim",
               "Hadjipavlou & Kanol (2008) timeline records for 1995: 'Aikido, Chris Thorsen, hired by Cyprus Consortium'",
               {"claim_text": "The Impacts of Peacebuilding Work on the Cyprus Conflict (CDA Reflecting on Peace Practice, Feb 2008), bicommunal-activities timeline p.63, entry for 1995: 'Aikido, Chris Thorsen, hired by Cyprus Consortium'.",
                "claim_type": "biographical",
                "stance": "asserting",
                "confidence": 1.0,
                "evidence_mode": "archival_clipping",
                "local_archive": str(BUNDLE / MAIN),
                "source_url": None})
        for rel, dst in [("ABOUT", "person:christopher-thorsen"),
                         ("ABOUT", "group:cyprus-consortium"),
                         ("SUPPORTED_BY", MAIN_ID)]:
            cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) VALUES (?,?,?)",
                        (cid, rel, dst))
    actions.append(f"claim -> {cid}")

    # Resolve the kkron open lead: corroborated, keep the original text
    cur.execute("SELECT metadata_json FROM nodes WHERE id=?", (OPEN_LEAD,))
    row = cur.fetchone()
    if row:
        m = json.loads(row[0] or "{}")
        m["open_lead"] = False
        m["resolved"] = True
        m["resolved_by"] = MAIN_ID
        m["resolved_at"] = NOW
        m["resolution_note"] = ("Document located in Academia.edu bundle: Hadjipavlou & "
                                "Kanol (2008), CDA Reflecting on Peace Practice. Timeline "
                                "p.63 entry for 1995 reads 'Aikido, Chris Thorsen, hired "
                                "by Cyprus Consortium' — kkron's recollection corroborated.")
        if not dry:
            cur.execute("UPDATE nodes SET metadata_json=? WHERE id=?",
                        (json.dumps(m), OPEN_LEAD))
            cur.execute("INSERT OR IGNORE INTO edges (src_id,rel_type,dst_id) VALUES (?,?,?)",
                        (OPEN_LEAD, "SUPPORTED_BY", MAIN_ID))
        actions.append(f"resolved open lead -> {OPEN_LEAD}")

    # Manifest
    if not dry:
        manifest = {"bundle": "Academia.edu — Impacts of Peacebuilding Work (Cyprus)",
                    "zip_source": "~/Academia.edu_Bundle_-_The_Impacts_of_Peacebuilding_Work_on_the.zip",
                    "ingested_at": NOW, "files": len(docs)}
        (BUNDLE / "manifest.json").write_text(json.dumps(manifest, indent=2))
        cur.connection.commit()

    print(("DRY-RUN " if dry else "") + f"{len(actions)} actions:")
    for a in actions:
        print("  " + a)


if __name__ == "__main__":
    main()
