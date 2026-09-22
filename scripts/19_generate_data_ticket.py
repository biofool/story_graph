#!/usr/bin/env python3
"""
Generate a GitHub issue (data ticket) containing all graph data for a given
entity — nodes, alias/duplicate nodes, kkron claims, key relationship edges,
ingested web sources with URLs, inaccessible URLs, and data-quality issues.

This is the standard data ticket generator. It reads from the tracked
graph_snapshot/ JSONL files (not the live SQLite DB) so the ticket reflects
the committed, reviewable state of the graph.

Usage:
    # Generate ticket body to stdout (review before posting)
    python scripts/19_generate_data_ticket.py "sig kufferath"

    # Write ticket body to a file
    python scripts/19_generate_data_ticket.py "sig kufferath" -o /tmp/ticket.md

    # Generate AND post to GitHub (requires gh CLI)
    python scripts/19_generate_data_ticket.py "sig kufferath" --post \\
        --title "Sig Kufferath: complete graph data dump"

    # Dry-run (show what would be included without posting)
    python scripts/19_generate_data_ticket.py "sig kufferath" --dry-run

    # Specify a different repo (default: biofool/story_graph)
    python scripts/19_generate_data_ticket.py "robert nadeau" --post \\
        --repo biofool/story_graph --title "Robert Nadeau: graph data dump"

The search term is matched case-insensitively against node labels, IDs,
canonical names, and source URLs. All matching Person nodes are collected;
the one with the most source_urls is treated as the canonical node.
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"

# Edge relation types that represent meaningful relationships (not just MENTIONS)
KEY_RELATIONS = {
    "FOUNDED",
    "MEMBER_OF",
    "WORKED_AT",
    "ALIAS_OF",
    "LIVED_AT",
    "CREATED",
    "PUBLISHED_AT",
    "LOCATED_IN",
    "PRECEDES",
    "DESCRIBES",
    "ABOUT",
    "ASSERTED_BY",
    "SUPPORTED_BY",
    "CONTRADICTS",
    "DEPICTS",
    "CONTAINS",
}


def load_jsonl(path: Path) -> list[dict]:
    """Load all records from a JSONL file."""
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def find_matching_nodes(search_term: str, nodes: list[dict]) -> list[dict]:
    """Find all nodes whose label, id, canonical_name, or source_urls match the search term."""
    term = search_term.lower()
    matches = []
    for n in nodes:
        blob = " ".join(
            [
                n.get("label", ""),
                n.get("id", ""),
                n.get("canonical_name", "") or "",
                " ".join(n.get("source_urls", []) or []),
            ]
        ).lower()
        if term in blob:
            matches.append(n)
    return matches


def select_canonical_person(matches: list[dict]) -> dict | None:
    """Select the canonical Person node — the one with the most source_urls."""
    persons = [n for n in matches if n.get("type") == "Person"]
    if not persons:
        return None
    return max(persons, key=lambda n: len(n.get("source_urls", []) or []))


def collect_kkron_claims(
    matches: list[dict], nodes: list[dict], search_term: str
) -> list[dict]:
    """Collect all Claim nodes that mention the entity and are kkron-sourced.

    Uses both the user's original search term and the canonical label,
    plus the surname (last word) for broader matching, since many claims
    reference only the surname (e.g. "Kufferath relocated..." not "Sig
    Kufferath relocated...").
    """
    canonical = select_canonical_person(matches)
    canonical_label = (canonical["label"] if canonical else "").lower()
    # Build a set of search terms: original, canonical label, and surname
    terms = {search_term.lower(), canonical_label}
    for t in list(terms):
        words = t.split()
        if len(words) > 1:
            terms.add(words[-1])  # surname (last word)
    # Filter out empty strings
    terms.discard("")

    claims = []
    for n in nodes:
        if n.get("type") != "Claim":
            continue
        blob = json.dumps(n).lower()
        if any(term in blob for term in terms):
            md = n.get("metadata", {})
            urls = n.get("source_urls", []) or []
            if md.get("asserted_by") == "kkron" or any(
                "kkron://" in u for u in urls
            ):
                claims.append(n)
    return claims


def search_term_from_nodes(matches: list[dict]) -> str:
    """Derive a search term from the matched nodes for cross-referencing."""
    # Use the canonical person's label, lowercased, first word(s)
    person = select_canonical_person(matches)
    if person:
        return person.get("label", "").lower()
    if matches:
        return matches[0].get("label", "").lower()
    return ""


def collect_key_edges(matches: list[dict], edges: list[dict]) -> list[dict]:
    """Collect edges involving matched node IDs that use key relation types
    OR that directly connect to the canonical person node."""
    match_ids = {n["id"] for n in matches}
    canonical = select_canonical_person(matches)
    canonical_id = canonical["id"] if canonical else None

    key_edges = []
    for e in edges:
        src = e.get("src_id", "")
        dst = e.get("dst_id", "")
        rel = e.get("rel_type", "")
        # Include if it's a key relation involving any matched node
        if rel in KEY_RELATIONS and (src in match_ids or dst in match_ids):
            key_edges.append(e)
        # Also include any edge directly involving the canonical person
        elif canonical_id and (src == canonical_id or dst == canonical_id):
            if rel != "MENTIONS":  # Skip noisy MENTIONS edges
                key_edges.append(e)
    return key_edges


def collect_sources(matches: list[dict], sources: list[dict]) -> list[dict]:
    """Collect all source records that mention the search term."""
    term = search_term_from_nodes(matches)
    result = []
    for s in sources:
        blob = json.dumps(s).lower()
        if term in blob:
            result.append(s)
    return result


def collect_claim_source_links(
    kkron_claims: list[dict], claim_sources: list[dict]
) -> dict[str, list[str]]:
    """Map claim IDs to their source IDs via claim_sources.jsonl."""
    claim_ids = {c["id"] for c in kkron_claims}
    links = defaultdict(list)
    for cs in claim_sources:
        cid = cs.get("claim_id", "")
        sid = cs.get("source_id", "")
        if cid in claim_ids:
            links[cid].append(sid)
    return dict(links)


def truncate_text(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len chars with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def format_source_summary(s: dict) -> str:
    """Format a source record as a one-line summary for the sources table."""
    title = s.get("title", "") or "(untitled)"
    platform = s.get("platform", "") or "(unknown)"
    url = s.get("url", "") or "(no url)"
    return f"| {title} | {platform} | {url} |"


def generate_ticket_body(
    search_term: str,
    nodes: list[dict],
    edges: list[dict],
    sources: list[dict],
    claim_sources: list[dict],
) -> str:
    """Generate the full markdown ticket body."""
    matches = find_matching_nodes(search_term, nodes)
    if not matches:
        return f"No nodes found matching '{search_term}'."

    canonical = select_canonical_person(matches)
    canonical_id = canonical["id"] if canonical else matches[0]["id"]
    canonical_label = canonical["label"] if canonical else matches[0]["label"]

    # Group matched nodes by type
    by_type = defaultdict(list)
    for n in matches:
        by_type[n.get("type", "Unknown")].append(n)

    # Collect kkron claims
    kkron_claims = collect_kkron_claims(matches, nodes, search_term)

    # Collect key edges
    key_edges = collect_key_edges(matches, edges)

    # Collect sources
    matched_sources = collect_sources(matches, sources)

    # Count all edges mentioning the search term (for provenance stats)
    term_for_count = canonical_label.lower()
    all_edge_count = sum(
        1 for e in edges if term_for_count in json.dumps(e).lower()
    )
    all_node_count = len(matches)

    lines = []
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"Complete dump of all **{canonical_label}** data currently in the "
        f"Story Graph: "
    )
    if canonical:
        lines.append(
            f"canonical Person node, alias/duplicate Person nodes, kkron "
            f"personal-communication claims, key relationship edges, "
            f"ingested web sources with URLs, and data-quality issues."
        )
    else:
        lines.append(
            f"matching nodes of type(s) {', '.join(by_type.keys())}, "
            f"claims, edges, and sources."
        )
    lines.append("")
    lines.append(f"Canonical node ID: `{canonical_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # --- Person Nodes ---
    if "Person" in by_type:
        persons = by_type["Person"]
        lines.append("## Person Nodes")
        lines.append("")
        lines.append(
            f"**Canonical:** `{canonical_id}` — \"{canonical_label}\""
        )
        if canonical:
            md = canonical.get("metadata", {})
            if md.get("asserted_by"):
                lines.append(f"- `metadata.asserted_by`: {md['asserted_by']}")
            urls = canonical.get("source_urls", []) or []
            if urls:
                lines.append("- `source_urls`:")
                for u in urls:
                    lines.append(f"  - {u}")
        lines.append("")

        aliases = [p for p in persons if p["id"] != canonical_id]
        if aliases:
            lines.append(
                "**Alias / duplicate Person nodes (spaCy-extracted variants, "
                "not yet merged):**"
            )
            lines.append("")
            lines.append("| Node ID | Label | Source URL |")
            lines.append("|---|---|---|")
            for p in aliases:
                urls = ", ".join(p.get("source_urls", []) or [])
                lines.append(f"| `{p['id']}` | {p.get('label', '')} | {urls} |")
            lines.append("")
            lines.append(
                "> **Data-quality note:** These variants should be merged into "
                f"`{canonical_id}` via `ALIAS_OF` edges (or deduplicated). "
                "Check whether any are actually different people (e.g. family "
                "members) mis-extracted as aliases."
            )
            lines.append("")

    # --- Other node types ---
    for ntype in sorted(by_type.keys()):
        if ntype == "Person":
            continue
        nodes_of_type = by_type[ntype]
        lines.append(f"## {ntype} Nodes ({len(nodes_of_type)} matched)")
        lines.append("")
        lines.append("| Node ID | Label | Source URLs |")
        lines.append("|---|---|---|")
        for n in nodes_of_type[:50]:  # Cap at 50 to avoid huge tables
            urls = "; ".join((n.get("source_urls") or [])[:3])
            if len(n.get("source_urls") or []) > 3:
                urls += f" (+{len(n['source_urls']) - 3} more)"
            lines.append(f"| `{n['id']}` | {n.get('label', '')} | {urls} |")
        if len(nodes_of_type) > 50:
            lines.append(f"| ... | *{len(nodes_of_type) - 50} more* | |")
        lines.append("")

    # --- kkron Claims ---
    if kkron_claims:
        lines.append("## kkron Personal-Communication Claims")
        lines.append("")
        kkron_urls = set()
        for c in kkron_claims:
            for u in c.get("source_urls", []) or []:
                if "kkron://" in u:
                    kkron_urls.add(u)
        if kkron_urls:
            lines.append(f"All sourced from `{', '.join(sorted(kkron_urls))}`.")
        lines.append("")
        for i, c in enumerate(kkron_claims, 1):
            md = c.get("metadata", {})
            text = md.get("claim_text", c.get("label", ""))
            ctype = md.get("claim_type", "")
            conf = md.get("confidence", "")
            evidence = md.get("evidence_mode", "")
            lines.append(f"{i}. **{truncate_text(c.get('label', ''), 80)}** "
                         f"(`{c['id']}`, {evidence})")
            lines.append(f"   > {text}")
            if ctype or conf:
                lines.append(f"   *Type: {ctype} | Confidence: {conf}*")
            lines.append("")
    else:
        lines.append("## kkron Personal-Communication Claims")
        lines.append("")
        lines.append("*No kkron-sourced claims found for this entity.*")
        lines.append("")

    # --- Key Relationship Edges ---
    if key_edges:
        lines.append("## Key Relationship Edges")
        lines.append("")
        lines.append("| Source | Relation | Target | Evidence |")
        lines.append("|---|---|---|---|")
        for e in key_edges:
            src = e.get("src_id", "")
            dst = e.get("dst_id", "")
            rel = e.get("rel_type", "")
            md = e.get("metadata", {})
            evidence = md.get("source", "") or md.get("evidence", "")
            lines.append(f"| `{src}` | {rel} | `{dst}` | {evidence} |")
        lines.append("")

    # --- Ingested Web Sources ---
    if matched_sources:
        lines.append("## Ingested Web Sources (with URLs)")
        lines.append("")
        lines.append("| # | Title | Platform | URL |")
        lines.append("|---|---|---|---|")
        for i, s in enumerate(matched_sources, 1):
            title = s.get("title", "") or "(untitled)"
            platform = s.get("platform", "") or "(unknown)"
            url = s.get("url", "") or "(no url)"
            lines.append(f"| {i} | {title} | {platform} | {url} |")
        lines.append("")

        # Detailed source summaries (truncated raw_text)
        lines.append("### Source Details")
        lines.append("")
        for i, s in enumerate(matched_sources, 1):
            title = s.get("title", "") or "(untitled)"
            url = s.get("url", "") or "(no url)"
            platform = s.get("platform", "") or "(unknown)"
            raw = s.get("raw_text", "") or ""
            author = s.get("author", "") or "(unknown)"
            sclass = s.get("source_class", "") or ""
            pdate = s.get("publish_date", "") or ""
            lines.append(f"#### Source {i} — {platform} ({title})")
            lines.append(f"- **URL:** {url}")
            lines.append(f"- **Author:** {author} | **Class:** {sclass} | "
                         f"**Published:** {pdate}")
            if raw:
                lines.append(f"- **Summary:** {truncate_text(raw, 500)}")
            lines.append("")

    # --- Graph Provenance ---
    lines.append("---")
    lines.append("")
    lines.append("## Graph Provenance")
    lines.append("")
    lines.append(
        f"- Data extracted from `graph_snapshot/` JSONL files "
        f"(nodes, edges, sources, claim_sources)."
    )
    lines.append(
        f"- Total matching nodes: {all_node_count}, "
        f"edges mentioning entity: {all_edge_count} "
        f"(most are `MENTIONS` edges from ingested Works)."
    )
    if kkron_claims:
        lines.append(
            "- kkron assertions are first-class evidence per `AGENTS.md` — "
            "recorded as `source_class: primary_first_person`."
        )
    lines.append("")

    return "\n".join(lines)


def post_to_github(
    title: str, body: str, repo: str, labels: list[str] | None = None
) -> str:
    """Post the ticket body as a GitHub issue using gh CLI."""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
    for label in labels or []:
        cmd.extend(["--label", label])

    # Write body to a temp file to avoid shell escaping issues
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, prefix="data_ticket_"
    ) as f:
        f.write(body)
        tmp_path = f.name

    cmd.extend(["--body-file", tmp_path])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a GitHub data ticket for a Story Graph entity."
    )
    parser.add_argument(
        "search_term",
        help="Entity name to search for (e.g. 'sig kufferath')",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        help="Write ticket body to this file instead of stdout",
    )
    parser.add_argument(
        "--post",
        action="store_true",
        help="Post the ticket to GitHub using gh CLI",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be included without posting",
    )
    parser.add_argument(
        "--repo",
        default="biofool/story_graph",
        help="GitHub repo to post to (default: biofool/story_graph)",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Issue title (default: auto-generated from search term)",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=["enhancement"],
        help="GitHub labels to apply (default: enhancement; repeatable)",
    )
    parser.add_argument(
        "--snapshot-dir",
        type=Path,
        default=SNAPSHOT_DIR,
        help=f"Path to graph_snapshot/ dir (default: {SNAPSHOT_DIR})",
    )

    args = parser.parse_args()

    # Load all snapshot files
    snapshot = args.snapshot_dir
    nodes = load_jsonl(snapshot / "nodes.jsonl")
    edges = load_jsonl(snapshot / "edges.jsonl")
    sources = load_jsonl(snapshot / "sources.jsonl")
    claim_sources = load_jsonl(snapshot / "claim_sources.jsonl")

    if not nodes:
        print(f"ERROR: No nodes found in {snapshot / 'nodes.jsonl'}", file=sys.stderr)
        sys.exit(1)

    # Generate the ticket body
    body = generate_ticket_body(args.search_term, nodes, edges, sources, claim_sources)

    if args.dry_run:
        # Show summary stats
        matches = find_matching_nodes(args.search_term, nodes)
        canonical = select_canonical_person(matches)
        kkron_claims = collect_kkron_claims(matches, nodes, args.search_term)
        key_edges = collect_key_edges(matches, edges)
        matched_sources = collect_sources(matches, sources)
        print(f"Dry run for '{args.search_term}':", file=sys.stderr)
        print(f"  Matched nodes: {len(matches)}", file=sys.stderr)
        if canonical:
            print(f"  Canonical Person: {canonical['id']}", file=sys.stderr)
        print(f"  kkron claims: {len(kkron_claims)}", file=sys.stderr)
        print(f"  Key edges: {len(key_edges)}", file=sys.stderr)
        print(f"  Sources: {len(matched_sources)}", file=sys.stderr)
        print(f"  Body length: {len(body)} chars", file=sys.stderr)
        print("\n--- Preview (first 2000 chars) ---", file=sys.stderr)
        print(body[:2000], file=sys.stderr)
        return

    if args.output:
        args.output.write_text(body)
        print(f"Ticket body written to {args.output}", file=sys.stderr)
    elif not args.post:
        print(body)
        return

    if args.post:
        title = args.title or (
            f"{args.search_term.title()}: complete graph data dump "
            f"with URLs and data-quality issues"
        )
        url = post_to_github(title, body, args.repo, args.labels)
        print(f"Created GitHub issue: {url}")


if __name__ == "__main__":
    main()
