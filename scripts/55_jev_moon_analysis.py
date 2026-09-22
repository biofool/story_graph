#!/usr/bin/env python3
"""Moon-scoped JEV analysis — all high-value decision kinds on the
Richard Moon corpus (issue #62 + 2026-09-22 unified-identity encoding).

Scenarios:
  1. entity_resolution — every Moon-named person pair (incl. the
     Australian chef + Canadian law professor collisions).
  2. identity_match — ALL Moon terminal nodes (rugby/painter/railway/
     no-relevant) + all verified Moon articles.
  3. event_dedup — Moon event pairs (sanity check; few true dupes).
  4. claim_verification — key Wikipedia-draft claims vs their cited
     source text (citation-check pattern).

Results -> data/audit/jev_moon_<date>.json + stdout summary.
Usage: python scripts/55_jev_moon_analysis.py [--dry-run]
"""
import argparse
import glob
import json
import re
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config.settings  # noqa: F401
from src.llm.jev_client import JevClient, verify_claim, answer_confidence

DB = Path("data/graph.db")
ARTICLES = Path("data/reference/newspapers-com/articles")
OUT = Path("data/audit")

CANON = "person:richard-moon-aikido"
MOON_CARD = (
    "Richard Moon Sensei: American aikido teacher (born 1946), 6th dan, "
    "student of Robert Nadeau, founder of Aikido of Marin (Marin County CA) "
    "and co-founder of City Aikido San Francisco. Also a chef (Source "
    "restaurant era, later Teriyaki Age / La Cocina SF), musician "
    "(moonsic.com), executive coach (Performance Edge, 'Aikido and "
    "Dialogue', Extraordinary Listening), and peace builder (IMTD, Cyprus, "
    "Bosnia). He is NOT the England rugby scrum-half, Sir Richard Moon the "
    "railway chairman (d.1899), a Grande Prairie painter, a Hanover NH "
    "photographer, the Australian Blue Mountains chef ('Moon on a Spoon'), "
    "or the Canadian law professor."
)

ENTITY_PAIRS = [
    ("person-richard-moon", CANON, "same_entity"),
    (CANON, "person:richard-moon-chef", "different_entities"),
    (CANON, "person:richard-moon-law-professor", "different_entities"),
    (CANON, "person:rochelle-moon", "different_entities"),
    ("person-richard-moon", "person:richard-moon-chef", "different_entities"),
    ("person-richard-moon", "person:rochelle-moon", "different_entities"),
]

EVENT_PAIRS = [
    ("event:aiki-dance-workshop-1997", "event:aiki-dance-intro-1998", "different_event"),
    ("event:aikiweb-spring-retreat-with-richard-moon-sensei-5th-dan-3616069211",
     "event:aikiweb-fall-retreat-with-richard-moon-5th-dan-4af92261aa", "different_event"),
    ("event:aikiweb-grand-opening-seminar-with-robert-nadeau-7th-dan-richard-moo-efd81a0f5d",
     "event:aikiweb-seminar-with-robert-nadeau-shihan-7th-dan-richard-moon-5th-d-d3694d611e", "different_event"),
    ("event:aikido-and-dialogue-durham-1997", "event:aikido-and-dialogue-2001", "different_event"),
]

# Wikipedia-draft claims -> source file (verify each cited sentence)
CLAIM_CHECKS = [
    ("By November 1980 Moon was teaching adult aikido classes at the Dance Palace in Point Reyes Station.",
     "1105183831__a15.txt", "1105183831__a15.txt"),
    ("In September 1983 he gave an aikido demonstration at the Dance Palace with David Gamble and Sandy Jacobs.",
     "1101135895__a6.txt", "1101135895__a6.txt"),
    ("In February 1985 Moon registered the fictitious business name 'Aikido of Marin' in Marin County.",
     "1100894910__a2.txt", "1100894910__a2.txt"),
    ("With Chris Thorsen, Moon co-led 'Aikido and Dialogue' programs through their consultancy Performance Edge.",
     "793520210__a0.txt", "793520210__a0.txt"),
    ("In March 2019 he taught alongside Nadeau at the 'O Sensei Revisited Down Under' workshop hosted by Riai Aikido in Auckland.",
     None, "../moon/awase_fi_2025.html"),  # placeholder; web cites checked via archived files
]

WEB_SOURCES = {
    "riai": "data/reference/moon/riai_moon_bio.html",
    "nadeau": "data/reference/moon/nautilus_moon.html",
    "maastricht": "data/reference/moon/aikido_maastricht_english.html",
    "imtd": "data/reference/moon/imtd_associates.html",
    "riviera": "data/reference/moon/novum_riviera_2025.html",
    "awase": "data/reference/moon/awase_fi_2025.html",
    "quantum": "data/reference/moon/quantumaikido_home.html",
}

WEB_CLAIMS = [
    ("Moon worked on the Cyprus conflict-resolution project developed by IMTD with the Cyprus Fulbright Commission.",
     "riai"),
    ("Moon joined IMTD at its first Lake Trails camp in 1999, teaching aikido as a conflict-resolution tool.",
     "imtd"),
    ("Aikido Maastricht lists Moon among its hosted guest teachers.",
     "maastricht"),
    ("In June 2025 Moon taught at the annual Riviera Seminar on Lake Geneva.",
     "riviera"),
    ("Moon led guest sessions at the Awase dojo in Helsinki in June 2025.",
     "awase"),
    ("Moon is a senior associate of the Nautilus Institute.",
     "nadeau"),
]

NODE_CLAIMS = [
    ("Moon was born in 1946.", "claim:moon-born-1946"),
    ("Moon presented 'Teriyaki Age' at La Cocina SF's Street Food Festival.",
     "event:richard-moon-at-la-cocina-street-food-festival"),
    ("Moon worked at The Source restaurant on the Sunset Strip during the Source Family era.",
     "claim:kkron:218252fe4b9771cb"),
    ("Moon also worked at the Aware Inn.", "claim:kkron:0e842747e2d98504"),
]


def node_meta(cur, nid):
    row = cur.execute("SELECT label, metadata_json FROM nodes WHERE id=?", (nid,)).fetchone()
    return (row[0], json.loads(row[1] or "{}")) if row else (nid, {})


def neighbors(cur, nid, limit=8):
    return [r[0] for r in cur.execute(
        "SELECT n.label FROM edges e JOIN nodes n ON n.id=e.dst_id WHERE e.src_id=? LIMIT ?",
        (nid, limit))]


def ask(client, state, instr, criteria):
    return client.decide(state=state, questions={"v": {
        "type": "choice", "instructions": instr, "criteria": criteria}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    client = JevClient()
    if not a.dry_run and not client.is_available():
        print("JEV_API_KEY not configured"); return 1
    cur = sqlite3.connect(DB).cursor()
    res = {"date": str(date.today()), "scope": "moon", "tasks": {}}

    # ---------- 1. entity_resolution ----------
    print(f"entity_resolution: {len(ENTITY_PAIRS)} pairs")
    if not a.dry_run:
        run = []
        for a_id, b_id, expected in ENTITY_PAIRS:
            la, ma = node_meta(cur, a_id); lb, mb = node_meta(cur, b_id)
            state = json.dumps({"node_a": {"label": la, "metadata": ma,
                                           "linked_to": neighbors(cur, a_id)},
                                "node_b": {"label": lb, "metadata": mb,
                                           "linked_to": neighbors(cur, b_id)}}, default=str)[:8000]
            got = ((ask(client, state,
                        "Do node_a and node_b refer to the same real-world person?",
                        {"same_entity": "Same person (merge/alias).",
                         "different_entities": "Distinct people.",
                         "uncertain": "Not enough information."}) or {}).get("v") or {}).get("choice")
            run.append({"a": a_id, "b": b_id, "expected": expected, "got": got,
                        "correct": got == expected})
            time.sleep(0.15)
        res["tasks"]["entity_resolution"] = run

    # ---------- 2. identity_match — ALL Moon nodes + articles ----------
    rows = cur.execute("SELECT id, metadata_json FROM nodes WHERE id LIKE 'work:npc-%'").fetchall()
    moon_nodes = []
    for nid, mj in rows:
        m = json.loads(mj or "{}")
        reason = m.get("reason", "")
        queries = " ".join(m.get("queries", []))
        if "moon" in reason or "moon" in queries or "riai" in queries:
            moon_nodes.append((nid, m))
    pos = []
    for f in sorted(glob.glob(str(ARTICLES / "*.txt"))):
        t = open(f, errors="ignore").read()
        if re.search(r"(?i)aikido", t) and re.search(r"(?i)richard moon|moon sensei", t):
            pos.append((Path(f).name, t[:3000]))
    print(f"identity_match: {len(moon_nodes)} terminal nodes + {len(pos)} articles")
    if not a.dry_run:
        run = []
        for nid, m in moon_nodes:
            state = (f"Newspaper page listing — paper: {m.get('paper','?')}, "
                     f"page: {m.get('page','?')}, date: {m.get('date','?')}, "
                     f"location: {m.get('location','?')}. Queries: {m.get('queries')}.")
            got = ((ask(client, state,
                        f"Identity card — {MOON_CARD}\n\nDoes this listing refer to the identity-card person?",
                        {"same_person": "About the identity-card Richard Moon.",
                         "different_person": "A different Richard Moon.",
                         "insufficient_evidence": "Cannot tell."}) or {}).get("v") or {}).get("choice")
            exp = "different_person" if m.get("reason", "").startswith("collision") else "insufficient_evidence"
            run.append({"id": nid, "expected": exp, "got": got,
                        "reason": m.get("reason", ""),
                        "correct": got == exp or (exp == "different_person" and got == "insufficient_evidence")})
            time.sleep(0.15)
        for name, t in pos:
            got = ((ask(client, t,
                        f"Identity card — {MOON_CARD}\n\nDoes this article text refer to the identity-card person?",
                        {"same_person": "About the identity-card Richard Moon.",
                         "different_person": "A different Richard Moon.",
                         "insufficient_evidence": "Cannot tell."}) or {}).get("v") or {}).get("choice")
            run.append({"id": name, "expected": "same_person", "got": got,
                        "reason": "verified article",
                        "correct": got == "same_person"})
            time.sleep(0.15)
        res["tasks"]["identity_match"] = run

    # ---------- 3. event_dedup ----------
    print(f"event_dedup: {len(EVENT_PAIRS)} pairs")
    if not a.dry_run:
        run = []
        for a_id, b_id, expected in EVENT_PAIRS:
            la, ma = node_meta(cur, a_id); lb, mb = node_meta(cur, b_id)
            state = json.dumps({"event_a": {"label": la, "metadata": ma},
                                "event_b": {"label": lb, "metadata": mb}}, default=str)[:8000]
            got = ((ask(client, state,
                        "Do event_a and event_b describe the same real-world event?",
                        {"same_event": "Same event (duplicates).",
                         "different_event": "Distinct events.",
                         "uncertain": "Not enough information."}) or {}).get("v") or {}).get("choice")
            run.append({"a": a_id, "b": b_id, "expected": expected, "got": got,
                        "correct": got == expected})
            time.sleep(0.15)
        res["tasks"]["event_dedup"] = run

    # ---------- 4. claim_verification ----------
    checks = []
    for claim, af, _ in CLAIM_CHECKS[:4]:
        p = ARTICLES / af
        if p.exists():
            checks.append({"claim": claim, "source_id": af,
                           "text": p.read_text(errors="ignore")[:6000]})
    for claim, key in WEB_CLAIMS:
        p = Path(WEB_SOURCES[key])
        if p.exists():
            text = re.sub(r"<[^>]+>", " ", p.read_text(errors="ignore"))
            checks.append({"claim": claim, "source_id": key,
                           "text": re.sub(r"\s+", " ", text)[:6000]})
    for claim, nid in NODE_CLAIMS:
        _, m = node_meta(cur, nid)
        st = m.get("description") or m.get("claim_text") or json.dumps(m)
        checks.append({"claim": claim, "source_id": nid, "text": st[:6000]})
    print(f"claim_verification: {len(checks)} claims")
    if not a.dry_run:
        run = []
        for c in checks:
            r = verify_claim(c["claim"], c["text"], client=client)
            run.append({"claim": c["claim"], "source": c["source_id"],
                        "result": r})
            time.sleep(0.15)
        res["tasks"]["claim_verification"] = run

    if a.dry_run:
        print("dry-run only"); return 0

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"jev_moon_{date.today()}.json"
    out.write_text(json.dumps(res, indent=2))
    print(f"\nwrote {out}\n")
    for task, run in res["tasks"].items():
        if task == "claim_verification":
            dist = {}
            for r in run:
                v = (r["result"] or {}).get("jev_verdict", "unverified")
                dist[v] = dist.get(v, 0) + 1
            print(f"{task}: verdicts {dist}")
            for r in run:
                if (r["result"] or {}).get("jev_verdict") != "supported":
                    print(f"    CHECK {r['source']}: {r['claim'][:70]} -> {r['result']}")
        else:
            n = len(run); ok = sum(1 for r in run if r["correct"])
            dist = {}
            for r in run:
                dist[r["got"]] = dist.get(r["got"], 0) + 1
            print(f"{task}: {ok}/{n} correct — dist {dist}")
            for r in run:
                if not r["correct"]:
                    print(f"    MISS {r.get('id', r.get('a','?'))}: exp {r['expected']} got {r['got']} ({r.get('reason','')[:60]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
