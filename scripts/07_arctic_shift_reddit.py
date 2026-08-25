#!/usr/bin/env python3
"""
Arctic Shift Reddit Archive Extractor — Source Family / Father Yod

Queries the Arctic Shift Reddit archive API
(https://arctic-shift.photon-reddit.com) for historical Reddit submissions
about the Source Family, Father Yod, Jim Baker, and related topics, then
integrates the results into the story_graph.

WHY ARCTIC SHIFT (vs. the official Reddit API / PRAW used in 06_reddit_integration.py)?
- Free, unauthenticated, no API key, no rate-limit negotiation required
- Historical coverage from December 2005 through the current month
- ~120,000 requests/hour sustained capacity
- Bulk Parquet dumps on Hugging Face for offline analysis

PAID ACCOUNTS / PRICING:
- Arctic Shift is a community-maintained, free, open-source project
  (https://github.com/ArthurHeitmann/arctic_shift). There are NO paid
  accounts, no premium tier, no API keys, and no licensing fees. The
  service is sustained by the maintainer (Arthur Heitmann) on a
  best-effort basis. If you need SLA-backed access or higher rate
  limits, the project recommends downloading the bulk Parquet dumps
  from Hugging Face and querying them locally with DuckDB instead of
  hitting the REST API.

KEY LIMITATION:
- Full-text search is scoped to ONE subreddit or ONE user at a time.
  There is no global cross-subreddit search. This script iterates over
  the configured subreddit list and issues one query per subreddit per
  search term, mirroring the 06_reddit_integration.py pattern.

USAGE:
    python scripts/07_arctic_shift_reddit.py
    python scripts/07_arctic_shift_reddit.py --subreddits cults,communes
    python scripts/07_arctic_shift_reddit.py --limit 200 --dry-run

OUTPUTS:
- data/arctic_shift_extracts.json   (raw post dump for review)
- story_graph DB updates            (WORK nodes + SourceRecords)
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import (
    BiasHint,
    GraphNode,
    NodeType,
    SourceClass,
    SourceRecord,
)

BASE_URL = "https://arctic-shift.photon-reddit.com"
POSTS_ENDPOINT = f"{BASE_URL}/api/posts/search"
COMMENTS_ENDPOINT = f"{BASE_URL}/api/comments/search"
REQUEST_TIMEOUT = 60
# Be polite to a free, community-funded service. 1 req/sec is well under
# the published ~120k/hour ceiling and avoids stressing the host.
POLITE_DELAY_SEC = 1.0

DEFAULT_SEARCH_TERMS = [
    "Source Family",
    "Father Yod",
    "Jim Baker cult",
    "Ya Ho Wa",
    "YaHoWha",
]

DEFAULT_SUBREDDITS = [
    "cults",
    "communes",
    "spirituality",
    "cultsurvivors",
    "exvangelical",
    "hippies",
    "1970s",
    "losangeles",
    "FamousPeople",
]


class ArcticShiftExtractor:
    """Extract Source Family discussions from the Arctic Shift Reddit archive."""

    def __init__(
        self,
        subreddits: list[str] | None = None,
        search_terms: list[str] | None = None,
        limit: int = 100,
        polite_delay: float = POLITE_DELAY_SEC,
    ):
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.search_terms = search_terms or DEFAULT_SEARCH_TERMS
        self.limit = limit
        self.polite_delay = polite_delay
        self.submissions: dict[str, dict[str, Any]] = {}

    def _sleep_polite(self) -> None:
        if self.polite_delay > 0:
            time.sleep(self.polite_delay)

    def search_posts(self) -> None:
        """Search Arctic Shift for Source Family submissions across configured subreddits."""
        print("\n" + "=" * 70)
        print("SEARCHING ARCTIC SHIFT FOR SOURCE FAMILY DISCUSSIONS")
        print("=" * 70)
        print(f"Base URL: {BASE_URL}")
        print(f"Subreddits: {', '.join(self.subreddits)}")
        print(f"Search terms: {', '.join(self.search_terms)}")
        print(f"Limit per (subreddit, term): {self.limit}")
        print(f"Polite delay between requests: {self.polite_delay}s")
        print()

        for subreddit in self.subreddits:
            for term in self.search_terms:
                print(f"  [r/{subreddit}] query='{term}'")
                try:
                    self._fetch_posts(subreddit, term)
                except requests.HTTPError as e:
                    print(f"    HTTP error: {e.response.status_code} {e.response.text[:200]}")
                except requests.RequestException as e:
                    print(f"    Request error: {e}")
                self._sleep_polite()

        print(f"\n✓ Found {len(self.submissions)} unique submissions")

    def _fetch_posts(self, subreddit: str, query: str) -> None:
        params = {
            "subreddit": subreddit,
            "query": query,
            "limit": self.limit,
            "sort": "asc",
        }
        response = requests.get(POSTS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        posts = payload.get("data", [])
        print(f"    returned {len(posts)} posts")

        for post in posts:
            post_id = post.get("id")
            if not post_id or post_id in self.submissions:
                continue
            self.submissions[post_id] = self._normalize_post(post)

    @staticmethod
    def _normalize_post(post: dict[str, Any]) -> dict[str, Any]:
        created = post.get("created_utc")
        # Arctic Shift returns ISO strings or epoch floats depending on endpoint;
        # normalize to an ISO 8601 string for SourceRecord.publish_date.
        if isinstance(created, (int, float)):
            created_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
        elif isinstance(created, str) and created:
            created_iso = created
        else:
            created_iso = None

        permalink = post.get("permalink") or ""
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.reddit.com{permalink}"

        post_id = post.get("id")
        return {
            "id": post_id,
            "title": post.get("title", ""),
            "selftext": post.get("selftext", "") or post.get("body", ""),
            "author": post.get("author") or "[deleted]",
            "created_utc": created,
            "created_iso": created_iso,
            "subreddit": post.get("subreddit"),
            "permalink": permalink,
            "score": post.get("score"),
            "num_comments": post.get("num_comments"),
        }

    def fetch_comments_for(self, post_id: str, limit: int = 25) -> list[dict[str, Any]]:
        """Fetch top comments for a single post from Arctic Shift."""
        params = {"link_id": post_id, "limit": limit, "sort": "asc"}
        try:
            response = requests.get(COMMENTS_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as e:
            print(f"    comment fetch failed for {post_id}: {e}")
            return []

        comments = []
        for c in payload.get("data", [])[:limit]:
            comments.append({
                "id": c.get("id"),
                "author": c.get("author") or "[deleted]",
                "body": c.get("body", ""),
                "score": c.get("score"),
            })
        return comments

    def enrich_with_comments(self, max_posts: int | None = None) -> None:
        """Pull comments for each collected submission (best-effort, polite)."""
        print("\n" + "=" * 70)
        print("FETCHING COMMENTS FOR COLLECTED SUBMISSIONS")
        print("=" * 70)
        items = list(self.submissions.items())
        if max_posts is not None:
            items = items[:max_posts]
        for post_id, post in items:
            comments = self.fetch_comments_for(post_id)
            post["comments"] = comments
            if comments:
                print(f"  {post_id}: {len(comments)} comments")
            self._sleep_polite()

    def export_json(self, output_path: Path | None = None) -> Path:
        if output_path is None:
            output_path = Path(__file__).parent.parent / "data" / "arctic_shift_extracts.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w") as f:
            json.dump(self.submissions, f, indent=2, default=str)
        print(f"\n✓ Exported {len(self.submissions)} submissions to {output_path}")
        return output_path

    def integrate_into_graph(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).parent.parent / "data" / "graph.db"

        print("\n" + "=" * 70)
        print("INTEGRATING ARCTIC SHIFT DATA INTO STORY_GRAPH")
        print("=" * 70)

        with GraphDB(db_path) as db:
            sources_added = 0
            nodes_added = 0
            for post_id, post in self.submissions.items():
                try:
                    subreddit = post.get("subreddit") or "unknown"
                    source = SourceRecord(
                        id=f"arcticshift-{subreddit}-{post_id}",
                        url=post["permalink"],
                        title=post["title"],
                        author=post["author"],
                        publish_date=post.get("created_iso"),
                        platform="reddit",
                        source_class=SourceClass.COMMENT_THREAD,
                        bias_hint=BiasHint.NEUTRAL_ISH,
                    )
                    db.add_source(source)
                    sources_added += 1

                    work_node = GraphNode(
                        id=f"work-arcticshift-{post_id}",
                        type=NodeType.WORK,
                        label=(post["title"] or "(untitled)")[:100],
                        metadata={
                            "work_type": "reddit_discussion",
                            "source_archive": "arctic_shift",
                            "subreddit": subreddit,
                            "author": post["author"],
                            "score": post.get("score"),
                            "num_comments": post.get("num_comments"),
                            "text_preview": (post.get("selftext") or "")[:500],
                        },
                        source_urls=[post["permalink"]] if post.get("permalink") else [],
                    )
                    db.add_node(work_node)
                    nodes_added += 1
                    print(f"  ✓ Added: {(post['title'] or '(untitled)')[:60]}")
                except Exception as e:
                    print(f"  Error processing {post_id}: {e}")

            print(f"\n✓ Sources added: {sources_added}")
            print(f"✓ Discussion nodes added: {nodes_added}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Arctic Shift Reddit archive extractor for story_graph")
    p.add_argument("--subreddits", help="Comma-separated subreddit list (overrides defaults)")
    p.add_argument("--terms", help="Comma-separated search terms (overrides defaults)")
    p.add_argument("--limit", type=int, default=100, help="Max posts per (subreddit, term) query")
    p.add_argument("--no-comments", action="store_true", help="Skip comment enrichment")
    p.add_argument("--no-graph", action="store_true", help="Skip story_graph DB integration")
    p.add_argument("--dry-run", action="store_true", help="Search only; do not write JSON or DB")
    p.add_argument("--db", type=Path, default=None, help="Path to graph.db")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("""
╔════════════════════════════════════════════════════════════════════╗
║          ARCTIC SHIFT REDDIT ARCHIVE EXTRACTOR                     ║
║   Free, unauthenticated historical Reddit search (2005–present)    ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    subreddits = args.subreddits.split(",") if args.subreddits else None
    terms = args.terms.split(",") if args.terms else None

    extractor = ArcticShiftExtractor(
        subreddits=subreddits,
        search_terms=terms,
        limit=args.limit,
    )

    try:
        extractor.search_posts()
        if not args.no_comments and extractor.submissions:
            extractor.enrich_with_comments()

        if args.dry_run:
            print("\n[dry-run] Skipping JSON export and graph integration.")
            print(f"Would have written {len(extractor.submissions)} submissions.")
            return 0

        extractor.export_json()
        if not args.no_graph:
            extractor.integrate_into_graph(db_path=args.db)

        print("\n" + "=" * 70)
        print("✅ ARCTIC SHIFT INTEGRATION COMPLETE")
        print("=" * 70)
        print(f"\nFound {len(extractor.submissions)} historical Reddit submissions.")
        print("Review data/arctic_shift_extracts.json for full details.")
        print("All submissions linked to story_graph with source attribution.\n")
        return 0
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
