#!/usr/bin/env python3
"""
Reddit Source Family/Father Yod Discussion Extractor

This script searches Reddit for discussions about the Source Family, Father Yod,
Jim Baker, and related topics, then integrates findings into the story_graph.

SETUP INSTRUCTIONS:
1. Create a Reddit app at https://www.reddit.com/prefs/apps
   - Click "Create app" at the bottom
   - Type: "script"
   - Name: "StorygraphSourceFamilyResearch"
   - Redirect URI: http://localhost:8080
   - Click "Create app"

2. Copy your credentials:
   - Client ID (below app name)
   - Client Secret (click "show")
   - User Agent: "StorygraphSourceFamily/1.0 by YourUsername"

3. Add to .env file:
   REDDIT_CLIENT_ID=your_client_id
   REDDIT_CLIENT_SECRET=your_client_secret
   REDDIT_USER_AGENT=StorygraphSourceFamily/1.0 by YourUsername
   REDDIT_USERNAME=your_reddit_username
   REDDIT_PASSWORD=your_reddit_password

4. Run: python scripts/06_reddit_integration.py
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

try:
    import praw
except ImportError:
    print("ERROR: praw not installed. Run: pip install praw")
    sys.exit(1)

from dotenv import load_dotenv

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
    SourceRecord,
    SourceClass,
    BiasHint,
    ClaimType,
    ClaimStance,
)


class RedditSourceFamilyExtractor:
    """Extract Source Family discussions from Reddit."""

    def __init__(self):
        load_dotenv()
        self.client_id = os.environ.get("REDDIT_CLIENT_ID")
        self.client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
        self.user_agent = os.environ.get("REDDIT_USER_AGENT")
        self.username = os.environ.get("REDDIT_USERNAME")
        self.password = os.environ.get("REDDIT_PASSWORD")

        if not all([self.client_id, self.client_secret, self.user_agent]):
            raise ValueError(
                "Missing Reddit credentials in .env file. See script header for setup."
            )

        self.reddit = praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
            username=self.username,
            password=self.password,
        )

        # Search terms and subreddits
        self.search_terms = [
            "Source Family",
            "Father Yod",
            "Jim Baker cult",
            "Ya Ho Wa",
            "YaHoWha",
        ]

        self.subreddits = [
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

        self.submissions = {}
        self.comments = {}

    def search_reddit(self, limit: int = 50) -> None:
        """Search Reddit for Source Family discussions."""
        print("\n" + "=" * 70)
        print("SEARCHING REDDIT FOR SOURCE FAMILY DISCUSSIONS")
        print("=" * 70)

        # Search each subreddit
        for subreddit_name in self.subreddits:
            print(f"\n[Searching r/{subreddit_name}]")
            try:
                subreddit = self.reddit.subreddit(subreddit_name)
                for term in self.search_terms:
                    print(f"  Searching for: '{term}'")
                    try:
                        for submission in subreddit.search(term, limit=limit // len(self.search_terms)):
                            self._process_submission(submission)
                    except Exception as e:
                        print(f"    Error searching '{term}': {e}")
            except Exception as e:
                print(f"  Error accessing r/{subreddit_name}: {e}")

        print(f"\n✓ Found {len(self.submissions)} submissions")
        print(f"✓ Found {len(self.comments)} comments")

    def _process_submission(self, submission) -> None:
        """Extract submission data."""
        try:
            submission_data = {
                "id": submission.id,
                "title": submission.title,
                "selftext": submission.selftext,
                "author": str(submission.author) if submission.author else "[deleted]",
                "created_utc": submission.created_utc,
                "subreddit": submission.subreddit.display_name,
                "url": submission.url,
                "permalink": f"https://www.reddit.com{submission.permalink}",
                "score": submission.score,
                "num_comments": submission.num_comments,
            }

            # Extract top comments
            submission.comments.replace_more(limit=5)
            comments = []
            for comment in submission.comments[:10]:
                if isinstance(comment, praw.models.Comment):
                    comments.append({
                        "id": comment.id,
                        "author": str(comment.author) if comment.author else "[deleted]",
                        "body": comment.body,
                        "score": comment.score,
                    })

            submission_data["comments"] = comments
            self.submissions[submission.id] = submission_data

        except Exception as e:
            print(f"    Error processing submission: {e}")

    def integrate_into_graph(self, db_path: Path = None) -> None:
        """Add Reddit discussions to story_graph."""
        if not db_path:
            db_path = Path(__file__).parent.parent / "data" / "graph.db"

        print("\n" + "=" * 70)
        print("INTEGRATING REDDIT DATA INTO STORY_GRAPH")
        print("=" * 70)

        with GraphDB(db_path) as db:
            sources_added = 0
            claims_added = 0

            for submission_id, submission in self.submissions.items():
                try:
                    # Add submission as a source
                    source = SourceRecord(
                        id=f"reddit-{submission['subreddit']}-{submission_id}",
                        url=submission["permalink"],
                        title=submission["title"],
                        author=submission["author"],
                        publish_date=datetime.fromtimestamp(submission["created_utc"]).isoformat(),
                        platform="reddit",
                        source_class=SourceClass.COMMENT_THREAD,
                        bias_hint=BiasHint.NEUTRAL_ISH,
                    )
                    db.add_source(source)
                    sources_added += 1

                    # Extract potential claims from post and comments
                    text_to_analyze = f"{submission['title']}\n{submission['selftext']}"
                    for comment in submission.get("comments", []):
                        text_to_analyze += f"\n{comment['body']}"

                    # Add submission node
                    work_node = GraphNode(
                        id=f"work-reddit-{submission_id}",
                        type=NodeType.WORK,
                        label=submission["title"][:100],
                        metadata={
                            "work_type": "reddit_discussion",
                            "subreddit": submission["subreddit"],
                            "author": submission["author"],
                            "score": submission["score"],
                            "num_comments": submission["num_comments"],
                            "text_preview": submission["selftext"][:500],
                        },
                        source_urls=[submission["permalink"]],
                    )
                    db.add_node(work_node)

                    print(f"  ✓ Added: {submission['title'][:60]}...")

                except Exception as e:
                    print(f"  Error processing submission {submission_id}: {e}")

            print(f"\n✓ Sources added: {sources_added}")
            print(f"✓ Discussion nodes added: {len(self.submissions)}")

    def export_json(self, output_path: Path = None) -> None:
        """Export submissions as JSON for manual review."""
        if not output_path:
            output_path = Path("data/reddit_extracts.json")

        with open(output_path, "w") as f:
            json.dump(self.submissions, f, indent=2, default=str)

        print(f"\n✓ Exported to {output_path}")


def main():
    print("""
╔════════════════════════════════════════════════════════════════════╗
║                 REDDIT SOURCE FAMILY EXTRACTOR                     ║
║              Extract discussions about Father Yod, etc.            ║
╚════════════════════════════════════════════════════════════════════╝
    """)

    # Check for credentials
    if not os.environ.get("REDDIT_CLIENT_ID"):
        print("""
⚠️  SETUP REQUIRED

Create a Reddit app to get API credentials:

1. Go to: https://www.reddit.com/prefs/apps
2. Click "Create app" (bottom of page)
3. Fill in:
   - Name: "StorygraphSourceFamilyResearch"
   - Type: "script"
   - Redirect URI: http://localhost:8080
4. Click "Create app"

5. Copy your credentials:
   - Client ID (under app name)
   - Client Secret (click "show")

6. Create/update .env with:
   REDDIT_CLIENT_ID=your_id_here
   REDDIT_CLIENT_SECRET=your_secret_here
   REDDIT_USER_AGENT=StorygraphSourceFamily/1.0 by YourUsername
   REDDIT_USERNAME=your_username
   REDDIT_PASSWORD=your_password

Then run this script again.
        """)
        sys.exit(1)

    try:
        extractor = RedditSourceFamilyExtractor()
        extractor.search_reddit(limit=50)
        extractor.export_json()
        extractor.integrate_into_graph()

        print("\n" + "=" * 70)
        print("✅ REDDIT INTEGRATION COMPLETE")
        print("=" * 70)
        print(f"\nFound discussions across r/cults, r/communes, r/spirituality, etc.")
        print(f"Review data/reddit_extracts.json for full details")
        print(f"All discussions linked to story_graph with source attribution\n")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
