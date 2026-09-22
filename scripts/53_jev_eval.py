#!/usr/bin/env python3
"""Live JEV evaluation — test candidate decision kinds on ~10% samples.

Tests the three highest-value decision kinds from issue #62 / docs/PRD.md
against labeled data already in the repo:

  1. identity_match    — ~10% of the collision/unassociated terminal nodes
                         plus verified positive articles.
  2. entity_resolution — known duplicate person pairs vs different people.
  3. event_dedup       — known duplicate event clusters vs different events.

All calls are live against the TypeSafe System One endpoint
(JEV_BASE_URL / JEV_MODEL / JEV_API_KEY from .env). Results are written to
data/audit/jev_eval_<date>.json and summarized on stdout.

Usage:
    python scripts/53_jev_eval.py            # run live eval
    python scripts/53_jev_eval.py --dry-run  # print the eval plan only
"""
import argparse
import glob
import json
import random
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config.settings  # noqa: F401  (loads .env)
from src.llm.jev_client import JevClient

DB = Path("data/graph.db")
ARTICLES = Path("data/reference/newspapers-com/articles")
OUT = Path("data/audit")
RNG = random.Random(20260921)

IDENTITY_CARDS = {
    "moon": (
        "Richard Moon Sensei: American aikido teacher (born 1946), 6th dan, "
        "student of Robert Nadeau, founded Aikido of Marin in Marin County "
        "California, also taught in New Zealand and Europe. He is NOT the "
        "England rugby scrum-half, Sir Richard Moon the railway chairman "
        "(d.1899), a Grande Prairie painter, a Hanover NH photographer, or "
        "the law professor."
    ),
    "ikeda": (
        "Hiroshi Ikeda Shihan: aikido instructor, 8th dan, founder of Boulder "
        "Aikikai in Colorado, student of Mitsugi Saotome, teaches aikido "
        "seminars worldwide including Japan. He is NOT the Hilo bonsai "
        "master, Prime Minister Hayato Ikeda, a Toshiba executive, a Japanese "
        "Health Ministry spokesman, or Tadanori Ikeda (aikido intern)."
    ),
}

ENTITY_PAIRS = [
    # (a, b, expected)
    ("person-richard-moon", "person:richard-moon-aikido", "same_entity"),
    ("person:nadeau-shihan", "person:robert-nadeau", "same_entity"),
    ("person:nadeau-sensei", "person:robert-nadeau", "same_entity"),
    ("person:robert-nadeau-sensei", "person:robert-nadeau", "same_entity"),
    ("person:sig-kufferath", "person:siegfried-kufferath", "same_entity"),
    ("person:kufferath-sig-kufferath", "person:sig-kufferath", "same_entity"),
    ("person:richard-moon-aikido", "person:richard-moon-chef", "same_entity"),
    ("person:richard-moon-law-professor", "person:richard-moon-aikido", "different_entities"),
    ("person:rochelle-moon", "person:richard-moon-aikido", "different_entities"),
    ("person:shin-hori-kufferath", "person:sig-kufferath", "different_entities"),
    ("person:peter-ralston", "person:laura-ralston", "different_entities"),
]

EVENT_PAIRS = [
    ("event:peter-ralston-wins-world-championship", "event:peter-ralston-wins-world-tournament", "same_event"),
    ("event:peter-ralston-wins-world-championship", "event:won-world-championship-full-contact-martial-arts-tournament", "same_event"),
    ("event:won-world-championship-full-contact-martial-arts-tournament", "event:world-championship-full-contact-martial-arts-tournament", "same_event"),
    ("event:opened-cheng-hsin-school-of-internal-martial-arts-and-center-for-ontological-research",
     "event:opening-of-the-cheng-hsin-school-of-internal-martial-arts-and-center-for-ontological-research", "same_event"),
    ("event:peter-ralston-begins-martial-arts-in-singapore", "event:peter-ralston-s-first-enlightenment-experience", "different_event"),
    ("event:aikiweb-grand-opening-seminar-with-robert-nadeau-7th-dan-richard-moo-efd81a0f5d",
     "event:aikiweb-seminar-with-robert-nadeau-shihan-7th-dan-richard-moon-5th-d-d3694d611e", "different_event"),
]


def ask(client, state, qid, qtype, instructions, criteria):
    return client.decide(state=state, questions={qid: {
        "type": qtype, "instructions": instructions, "criteria": criteria}})


def node_meta(cur, nid):
    row = cur.execute("SELECT label, metadata_json FROM nodes WHERE id=?", (nid,)).fetchone()
    return (row[0], json.loads(row[1] or "{}")) if row else (nid, {})


def neighbors(cur, nid, limit=8):
    rows = cur.execute(
        "SELECT n.label FROM edges e JOIN nodes n ON n.id=e.dst_id WHERE e.src_id=? LIMIT ?",
        (nid, limit)).fetchall()
    return [r[0] for r in rows]


def identity_samples(cur):
    """~10% of labeled terminal nodes + verified positive articles."""
    rows = cur.execute(
        "SELECT id, metadata_json FROM nodes WHERE id LIKE 'work:npc-%'").fetchall()
    collisions, unassoc = [], []
    for nid, mj in rows:
        m = json.loads(mj or "{}")
        reason = m.get("reason", "")
        if reason.startswith("collision:"):
            collisions.append((nid, m))
        elif "no subject-relevant" in reason:
            unassoc.append((nid, m))
    RNG.shuffle(collisions); RNG.shuffle(unassoc)
    # ~10% of 227 labeled = ~22 → 16 collisions + 6 no-relevant
    samples = []
    for nid, m in collisions[:16] + unassoc[:6]:
        who = "ikeda" if "ikeda" in m.get("reason", "") or any(
            "ikeda" in q for q in m.get("queries", [])) else "moon"
        state = (f"Newspaper page listing — paper: {m.get('paper','?')}, "
                 f"page: {m.get('page','?')}, date: {m.get('date','?')}, "
                 f"location: {m.get('location','?')}. Surfaced by search "
                 f"queries: {m.get('queries')}. No article text available.")
        samples.append({"kind": "identity", "id": nid, "person": who,
                        "expected": "different_person", "state": state,
                        "label_reason": m.get("reason", "")})
    # positives — verified articles
    pos = []
    for f in sorted(glob.glob(str(ARTICLES / "*.txt"))):
        t = open(f, errors="ignore").read()
        if not re.search(r"(?i)aikido", t):
            continue
        who = ("moon" if re.search(r"(?i)richard moon|moon sensei", t)
               else "ikeda" if re.search(r"(?i)ikeda", t) else None)
        if who:
            pos.append({"kind": "identity", "id": Path(f).name, "person": who,
                        "expected": "same_person", "state": t[:3000],
                        "label_reason": "verified kept article"})
    RNG.shuffle(pos)
    samples += pos[:12]
    return samples


def identity_question(who):
    return (
        f"Identity card — {IDENTITY_CARDS[who]}\n\n"
        "Does the source text refer to the person in the identity card?",
        {
            "same_person": "The text is about the person in the identity card.",
            "different_person": "The text is about a different person with a same or similar name.",
            "insufficient_evidence": "Cannot tell from the available text.",
        })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    client = JevClient()
    if not a.dry_run and not client.is_available():
        print("JEV_API_KEY not configured"); return 1
    cur = sqlite3.connect(DB).cursor()
    results = {"date": str(date.today()), "model": client.model,
               "endpoint": client.base_url, "tasks": {}}

    # ---- 1. identity_match ----
    samples = identity_samples(cur)
    print(f"identity_match: {len(samples)} samples")
    if not a.dry_run:
        run = []
        for s in samples:
            instr, criteria = identity_question(s["person"])
            ans = ask(client, s["state"], "verdict", "choice", instr, criteria)
            choice = ((ans or {}).get("verdict") or {}).get("choice")
            ok = (choice == s["expected"] or
                  (s["expected"] == "different_person" and choice == "insufficient_evidence"))
            run.append({**{k: s[k] for k in ("id", "person", "expected", "label_reason")},
                        "got": choice, "correct": ok})
            time.sleep(0.15)
        results["tasks"]["identity_match"] = run

    # ---- 2. entity_resolution ----
    print(f"entity_resolution: {len(ENTITY_PAIRS)} pairs")
    if not a.dry_run:
        run = []
        for a_id, b_id, expected in ENTITY_PAIRS:
            la, ma = node_meta(cur, a_id); lb, mb = node_meta(cur, b_id)
            state = {
                "node_a": {"label": la, "metadata": ma, "linked_to": neighbors(cur, a_id)},
                "node_b": {"label": lb, "metadata": mb, "linked_to": neighbors(cur, b_id)},
            }
            ans = ask(client, json.dumps(state, default=str)[:8000], "verdict", "choice",
                      "Do node_a and node_b in this knowledge graph refer to the same real-world entity?",
                      {"same_entity": "Same real-world entity (merge or alias).",
                       "alias_only": "Same entity but one node is an alias/variant name node.",
                       "different_entities": "Distinct real-world entities.",
                       "uncertain": "Not enough information."})
            choice = ((ans or {}).get("verdict") or {}).get("choice")
            ok = (choice == expected or
                  (expected == "same_entity" and choice == "alias_only"))
            run.append({"a": a_id, "b": b_id, "expected": expected,
                        "got": choice, "correct": ok})
            time.sleep(0.15)
        results["tasks"]["entity_resolution"] = run

    # ---- 3. event_dedup ----
    print(f"event_dedup: {len(EVENT_PAIRS)} pairs")
    if not a.dry_run:
        run = []
        for a_id, b_id, expected in EVENT_PAIRS:
            la, ma = node_meta(cur, a_id); lb, mb = node_meta(cur, b_id)
            state = {"event_a": {"label": la, "metadata": ma},
                     "event_b": {"label": lb, "metadata": mb}}
            ans = ask(client, json.dumps(state, default=str)[:8000], "verdict", "choice",
                      "Do event_a and event_b describe the same real-world event?",
                      {"same_event": "The same event (duplicate nodes).",
                       "different_event": "Distinct events.",
                       "uncertain": "Not enough information."})
            choice = ((ans or {}).get("verdict") or {}).get("choice")
            ok = (choice == expected or
                  (expected == "same_event" and choice == "uncertain") is False and choice == expected)
            ok = choice == expected
            run.append({"a": a_id, "b": b_id, "expected": expected,
                        "got": choice, "correct": ok})
            time.sleep(0.15)
        results["tasks"]["event_dedup"] = run

    if a.dry_run:
        print("dry-run: no API calls made"); return 0

    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / f"jev_eval_{date.today()}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path}")
    for task, run in results["tasks"].items():
        n = len(run); correct = sum(1 for r in run if r["correct"])
        dist = {}
        for r in run:
            dist[r["got"]] = dist.get(r["got"], 0) + 1
        print(f"{task}: {correct}/{n} correct ({correct/n:.0%}) — verdict dist {dist}")
        for r in run:
            if not r["correct"]:
                key = r.get("id") or f"{r.get('a')} <-> {r.get('b')}"
                print(f"    MISS {key}: expected {r['expected']}, got {r['got']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
