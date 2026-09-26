#!/usr/bin/env python3
"""Scan graph_snapshot/ for reingest candidates (issue #78).

Read-only audit run after the scheduled news-feed ingest. As matching and
extraction algorithms improve, slices of the graph that were ingested under
the old code become worth re-fetching / re-extracting. This script computes
the current candidate sets so a human can turn one into a data/ingest/*.json
spec or a reingest run — it never mutates the graph itself.

Candidate sets reported:
    mojibake            sources whose raw_text still shows wrong-encoding
                        artifacts (the fixed crawler uses apparent_encoding)
    raw_text_no_claims  sources with fetched raw_text but zero claim_sources
                        links — extraction produced nothing; reingest when
                        the claim extractor improves
    stub_no_raw_text    journalistic sources with no raw_text (RSS stubs);
                        full-article fetch + extract could recover claims
    work_no_mentions    news_article Work nodes with zero MENTIONS edges —
                        matching produced nothing; re-match when the matcher
                        improves

Large sets are summarized by platform with a bounded sample of URLs so the
committed report stays small and stable.

Usage:
    python scripts/reingest_audit.py
    python scripts/reingest_audit.py --out data/audit/reingest_candidates.json
"""

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
DEFAULT_OUT = PROJECT_ROOT / "data" / "audit" / "reingest_candidates.json"

# Same heuristic as scripts/reingest_mojibake.py: 4+ consecutive chars in
# U+0080-U+00FF, at least 5 such sequences in the first 3000 chars.
MOJIBAKE_REGEX = re.compile(r"[-ÿ]{4,}")
STUB_SAMPLE_LIMIT = 100


def is_mojibake(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    if text.startswith(("%PDF", "OTTO")):
        return False
    matches = [m for m in MOJIBAKE_REGEX.findall(text[:3000]) if len(m) >= 4]
    return len(matches) >= 5


def _read_jsonl(path: Path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def audit(snapshot_dir: Path) -> dict:
    sources = _read_jsonl(snapshot_dir / "sources.jsonl")
    nodes = _read_jsonl(snapshot_dir / "nodes.jsonl")
    edges = _read_jsonl(snapshot_dir / "edges.jsonl")
    claim_source_ids = {
        r["source_id"] for r in _read_jsonl(snapshot_dir / "claim_sources.jsonl")
    }

    mojibake = [
        {"id": s["id"], "url": s.get("url")}
        for s in sources
        if is_mojibake(s.get("raw_text") or "")
    ]
    raw_text_no_claims = [
        {"id": s["id"], "url": s.get("url"), "platform": s.get("platform")}
        for s in sources
        if s.get("raw_text") and s["id"] not in claim_source_ids
    ]
    stubs = [s for s in sources
             if s.get("source_class") == "journalistic" and not s.get("raw_text")]
    mention_srcs = {e["src_id"] for e in edges if e.get("rel_type") == "MENTIONS"}
    work_no_mentions = [
        {"id": n["id"], "label": n.get("label")}
        for n in nodes
        if n.get("type") == "Work"
        and (n.get("metadata") or {}).get("work_type") == "news_article"
        and n["id"] not in mention_srcs
    ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "snapshot_dir": str(snapshot_dir),
        "mojibake": mojibake,
        "raw_text_no_claims": raw_text_no_claims,
        "stub_no_raw_text": {
            "count": len(stubs),
            "by_platform": dict(Counter(s.get("platform") for s in stubs).most_common()),
            "sample_urls": [s.get("url") for s in stubs[:STUB_SAMPLE_LIMIT]],
        },
        "work_no_mentions": work_no_mentions,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--snapshot", default=str(SNAPSHOT_DIR))
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="Report path; use '-' to skip writing a file")
    args = ap.parse_args()

    report = audit(Path(args.snapshot))
    print(f"mojibake:           {len(report['mojibake'])}")
    print(f"raw_text_no_claims: {len(report['raw_text_no_claims'])}")
    print(f"stub_no_raw_text:   {report['stub_no_raw_text']['count']}")
    print(f"work_no_mentions:   {len(report['work_no_mentions'])}")

    if args.out != "-":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
