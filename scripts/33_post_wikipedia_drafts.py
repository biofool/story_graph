#!/usr/bin/env python3
"""
Post Wikipedia article drafts as GitHub issues for human review.

Reads article + reliability report pairs from docs/wikipedia-drafts/ and
creates a GitHub issue per person, with the article draft and reliability
report in the issue body. The issue is labeled `wikipedia-draft` for
tracking.

Usage:
    # Post all drafts in docs/wikipedia-drafts/
    python scripts/33_post_wikipedia_drafts.py

    # Post a specific person's draft
    python scripts/33_post_wikipedia_drafts.py --person "peter ralston"

    # Dry run — show what would be posted without creating issues
    python scripts/33_post_wikipedia_drafts.py --dry-run

    # Specify a different repo
    python scripts/33_post_wikipedia_drafts.py --repo biofool/story_graph

The script pairs files by stem:
    peter-ralston.md         → article
    peter-ralston-report.md  → reliability report
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = PROJECT_ROOT / "docs" / "wikipedia-drafts"

LABEL = "wikipedia-draft"


def find_draft_pairs(drafts_dir: Path) -> list[tuple[str, Path, Path]]:
    """Find article + report file pairs in the drafts directory.

    Returns a list of (person_slug, article_path, report_path) tuples.
    """
    pairs = []
    if not drafts_dir.exists():
        return pairs

    article_files = sorted(drafts_dir.glob("*-*.md"))
    # Exclude report files — they end with -report.md
    article_files = [f for f in article_files if not f.name.endswith("-report.md")]

    for article_path in article_files:
        slug = article_path.stem  # e.g. "peter-ralston"
        report_path = drafts_dir / f"{slug}-report.md"
        if report_path.exists():
            pairs.append((slug, article_path, report_path))
        else:
            pairs.append((slug, article_path, None))

    return pairs


def slug_to_title(slug: str) -> str:
    """Convert a slug like 'peter-ralston' to 'Peter Ralston'."""
    return " ".join(word.capitalize() for word in slug.split("-"))


def build_issue_body(
    person_slug: str,
    article_path: Path,
    report_path: Path | None,
) -> str:
    """Build the GitHub issue body from the article + report."""
    title = slug_to_title(person_slug)
    article = article_path.read_text()
    report = report_path.read_text() if report_path else "(no reliability report found)"

    # Extract WP:GNG status from the report
    gng_match = re.search(r"WP:GNG status:\s*\*?\*?(PASS|FAIL)\*?\*?", report, re.IGNORECASE)
    gng_status = gng_match.group(1).upper() if gng_match else "UNKNOWN"

    # Extract RELIABLE source count
    reliable_match = re.search(
        r"RELIABLE independent secondary sources.*?:\s*(\d+)", report,
    )
    reliable_count = reliable_match.group(1) if reliable_match else "?"

    body = f"""## Wikipedia Article Draft: {title}

**WP:GNG status:** {gng_status}
**Independent RELIABLE sources:** {reliable_count}

This is an auto-generated Wikipedia article draft from the Story Graph,
produced by `scripts/32_generate_wikipedia_article.py`. It is **not**
ready for Wikipedia — it needs human review for:

- Narrative quality (claim text is currently included verbatim)
- First-person quote filtering (interview quotes should be paraphrased)
- Source independence verification
- BLP sensitivity review
- Notability assessment (especially for MARGINAL sources)

---

### Article Draft

{article}

---

### Reliability Report

{report}

---

### How this was generated

1. `scripts/32_generate_wikipedia_article.py "{title.lower()}" --article {article_path.relative_to(PROJECT_ROOT)} --report {report_path.relative_to(PROJECT_ROOT) if report_path else "(none)"}`
2. Sources scored using the Source Reliability Score (SRS) per `.devin/skills/wikipedia-article-generator/SKILL.md`
3. kkron personal-communication claims are excluded from article text per AGENTS.md (listed in reliability report)
4. The draft reads from `graph_snapshot/` JSONL (committed, reviewable state)

### Automation

This issue was posted by `scripts/33_post_wikipedia_drafts.py`.
"""

    return body


def post_to_github(
    title: str, body: str, repo: str, labels: list[str] | None = None
) -> str:
    """Post the body as a GitHub issue using gh CLI."""
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", title]
    for label in labels or []:
        cmd.extend(["--label", label])

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, prefix="wiki_draft_"
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
        description="Post Wikipedia article drafts as GitHub issues."
    )
    parser.add_argument(
        "--person",
        default=None,
        help="Post only this person's draft (slug or name, e.g. 'peter-ralston' or 'peter ralston')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be posted without creating issues",
    )
    parser.add_argument(
        "--repo",
        default="biofool/story_graph",
        help="GitHub repo to post to (default: biofool/story_graph)",
    )
    parser.add_argument(
        "--drafts-dir",
        type=Path,
        default=DRAFTS_DIR,
        help=f"Path to drafts dir (default: {DRAFTS_DIR})",
    )
    parser.add_argument(
        "--label",
        action="append",
        dest="labels",
        default=[LABEL],
        help=f"GitHub labels (default: {LABEL}; repeatable)",
    )

    args = parser.parse_args()

    pairs = find_draft_pairs(args.drafts_dir)
    if not pairs:
        print(f"ERROR: No draft pairs found in {args.drafts_dir}", file=sys.stderr)
        sys.exit(1)

    # Filter by person if specified
    if args.person:
        person_filter = args.person.lower().replace(" ", "-")
        pairs = [
            p for p in pairs
            if person_filter in p[0] or args.person.lower() in p[0]
        ]
        if not pairs:
            print(f"ERROR: No drafts matching '{args.person}'", file=sys.stderr)
            sys.exit(1)

    print(f"Found {len(pairs)} draft(s) to post:", file=sys.stderr)
    for slug, article_path, report_path in pairs:
        print(f"  {slug} → {article_path.name} + {report_path.name if report_path else '(no report)'}", file=sys.stderr)
    print(file=sys.stderr)

    posted = []
    for slug, article_path, report_path in pairs:
        title = f"Wikipedia draft: {slug_to_title(slug)}"
        body = build_issue_body(slug, article_path, report_path)

        if args.dry_run:
            print(f"[DRY RUN] Would post: {title}", file=sys.stderr)
            print(f"  Body length: {len(body)} chars", file=sys.stderr)
            print(f"  First 200 chars: {body[:200]}...", file=sys.stderr)
            print(file=sys.stderr)
            posted.append((slug, "(dry run)"))
            continue

        print(f"Posting: {title} ...", file=sys.stderr)
        try:
            url = post_to_github(title, body, args.repo, args.labels)
            print(f"  Created: {url}", file=sys.stderr)
            posted.append((slug, url))
        except subprocess.CalledProcessError as e:
            print(f"  ERROR: {e.stderr}", file=sys.stderr)
            posted.append((slug, f"ERROR: {e}"))

    print(file=sys.stderr)
    print("Results:", file=sys.stderr)
    for slug, url in posted:
        print(f"  {slug}: {url}", file=sys.stderr)


if __name__ == "__main__":
    main()
