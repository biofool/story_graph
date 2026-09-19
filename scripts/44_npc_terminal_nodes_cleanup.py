#!/usr/bin/env python3
"""Record unassociated newspapers.com pages as terminal graph nodes and
delete their local artifacts.

Context: the Ikeda and Richard Moon search sweeps discovered ~730 unique
newspapers.com pages. Most matched queries but are about OTHER people with
the same names (bonsai master Hiroshi Ikeda, PM Hayato Ikeda, rugby player
Richard Moon, Sir Richard Moon, etc.) or had the search terms in unrelated
articles on the same page.

This script:
  1. Unions every page id from data/reference/newspapers-com/search_results_*.json
  2. Subtracts the KEEP set (pages verified to cover the real subjects)
  3. Upserts each remaining page into data/graph.db as a Work node
     (work:npc-<page_id>) flagged metadata.not_connected=True — a terminal
     node preserving the search provenance and the rejection reason
  4. Deletes local artifacts for those pages: npc_<id>.pdf,
     page_images/<id>.jpg, articles/<id>__*

Usage:
    python scripts/44_npc_terminal_nodes_cleanup.py --dry-run
    python scripts/44_npc_terminal_nodes_cleanup.py
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.storage.graph_db import GraphDB
from src.storage.models import GraphNode, NodeType

NPC_DIR = "data/reference/newspapers-com"
GRAPH_DB = "data/graph.db"

# Pages verified to contain coverage of the real subjects.
# Ikeda: Missoulian 1982 x2, Bradenton 1991, Pensacola 2000, Tennessean 2006,
#        Santa Barbara 2012.
# Moon:  Point Reyes Light 1980-1998 cluster, Novato Advance FBNs,
#        Durham Herald-Sun x2, plus 3 pages whose article polygons failed
#        to extract but which are the same papers/context.
KEEP = {
    # Hiroshi Ikeda (aikidoka)
    "268725982",  # Pensacola News Journal 2000-09-30 seminar
    "349991222",  # Missoulian 1982-04-13 UM seminar
    "349994891",  # Missoulian 1982-04-25 martial arts feature
    "277508543",  # Tennessean 2006-03-30 Saotome/Ikeda lineage
    "719083882",  # Bradenton Herald 1991-09-29 Sarasota seminar
    "1196156737", # Santa Barbara News-Press 2012-07-13 Ikeda Shihan
    # Richard Moon (aikidoka)
    "1125183831", "1101135895", "1100933658", "1100894830", "1100894910",
    "1100894996", "1100898652", "1101035804", "1100842220", "1100842319",
    "1100916418", "1100916601", "1100943036", "1100943153", "1100943276",
    "1100943401", "793520210", "795545627",
    # article-polygon extraction failed, same-paper/context, kept for retry
    "1100894742", "1101035712", "793548759",
}

COLLISION_HINTS = [
    (r"bonsai", "collision: hiroshi ikeda (bonsai master, hilo)"),
    (r"tadanori", "collision: tadanori ikeda (aikido intern, superior mt)"),
    (r"prime minister|hayato ikeda|eisenhower", "collision: pm hayato ikeda"),
    (r"health ministr", "collision: japanese health ministry spokesman"),
    (r"toshiba", "collision: toshiba america executive"),
    (r"ikebana|tea ceremony|sumi-e", "collision: other ikeda (cultural arts)"),
    (r"scrum|rugby|twickenham|rosslyn", "collision: richard moon (rugby player)"),
    (r"sir richard|railway", "collision: sir richard moon (railway chairman)"),
    (r"painter|decorat", "collision: richard moon (painter, grande prairie)"),
]


def card_fields(text):
    """Parse 'Paper • Page N\\nDate\\nLocation' card text."""
    lines = [l.strip() for l in (text or "").split("\n") if l.strip()]
    paper = page = date = loc = ""
    if lines:
        m = re.match(r"(.+?)\s*•\s*(Page\s+\d+)", lines[0])
        paper = (m.group(1) if m else lines[0]).replace("\xa0", " ").strip()
        page = m.group(2) if m else ""
    if len(lines) > 1:
        date = lines[1]
    if len(lines) > 2:
        loc = lines[2]
    return paper, page, date, loc


def classify(pid):
    """Return a short reason string from any extracted article text."""
    blob = ""
    for a in glob.glob(f"{NPC_DIR}/articles/{pid}__a*.txt"):
        blob += open(a, errors="replace").read().lower()
    if not blob:
        return "unassociated: not extracted (outside priority set or fetch blocked)"
    for pat, reason in COLLISION_HINTS:
        if re.search(pat, blob):
            return reason
    return "unassociated: no subject-relevant article on page"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # union all discovered pages, tracking which query files found each
    pages = {}
    for f in sorted(glob.glob(f"{NPC_DIR}/search_results*.json")):
        q = os.path.basename(f).replace("search_results", "").replace(".json", "") or "_base"
        for h in json.load(open(f)):
            if not isinstance(h, dict) or "id" not in h:
                continue
            e = pages.setdefault(h["id"], {"hit": h, "queries": []})
            if not e["hit"].get("text") and h.get("text"):
                e["hit"] = h
            e["queries"].append(q.lstrip("_"))
    for f in ("ikeda_retry.json", "moon_retry.json"):
        p = f"{NPC_DIR}/{f}"
        if os.path.exists(p):
            for h in json.load(open(p)):
                e = pages.setdefault(h["id"], {"hit": h, "queries": []})
                if f not in e["queries"]:
                    e["queries"].append(f.replace(".json", ""))

    unassoc = sorted(set(pages) - KEEP)
    print(f"discovered pages: {len(pages)} | keep: {len(KEEP & set(pages))} | unassociated: {len(unassoc)}")

    deleted = {"pdf": 0, "img": 0, "articles": 0}
    nodes = 0
    db = None if args.dry_run else GraphDB(GRAPH_DB)
    now = datetime.now(timezone.utc).isoformat()
    for pid in unassoc:
        hit = pages[pid]["hit"]
        paper, pageno, date, loc = card_fields(hit.get("text", ""))
        label = " — ".join(x for x in [paper, pageno, date] if x) or f"newspapers.com page {pid}"
        meta = {
            "work_type": "newspaper_page",
            "not_connected": True,
            "not_connected_set_at": now,
            "disposition": "unassociated_search_result",
            "reason": classify(pid),
            "queries": sorted(set(pages[pid]["queries"])),
            "paper": paper, "page": pageno, "date": date, "location": loc,
        }
        if not args.dry_run:
            db.add_node(GraphNode(
                id=f"work:npc-{pid}", type=NodeType.WORK, label=label,
                metadata=meta, source_urls=[hit.get("url", f"https://www.newspapers.com/image/{pid}/")],
            ))
        nodes += 1
        for pat, key in [
            (f"{NPC_DIR}/npc_{pid}.pdf", "pdf"),
            (f"{NPC_DIR}/page_images/{pid}.jpg", "img"),
        ]:
            if os.path.exists(pat):
                deleted[key] += 1
                if not args.dry_run:
                    os.remove(pat)
        arts = glob.glob(f"{NPC_DIR}/articles/{pid}__*")
        deleted["articles"] += len(arts)
        if not args.dry_run:
            for a in arts:
                os.remove(a)
    if db:
        db.close()
    print(f"{'[dry-run] would ' if args.dry_run else ''}terminal nodes upserted: {nodes}")
    print(f"{'[dry-run] would ' if args.dry_run else ''}deleted: {deleted['pdf']} PDFs, {deleted['img']} page images, {deleted['articles']} article files")


if __name__ == "__main__":
    main()
