"""
Facebook Graph API collector for historical and public Page research.
Extracts public posts and comments using Meta Graph API (Page Public Content Access).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional, Any
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.crawler.web_crawler import CrawledPage

_log = logging.getLogger(__name__)


@dataclass
class FacebookProvenanceRecord:
    """Provenance metadata for an ingested Facebook artifact."""
    page_id: str
    page_name: str
    post_id: str
    comment_id: Optional[str] = None
    permalink_url: str = ""
    created_time: str = ""
    author_name: Optional[str] = None
    author_id: Optional[str] = None
    message: str = ""
    topical_tags: list[str] = field(default_factory=list)


class FacebookGraphCollector:
    """
    Collector interfacing with Meta Graph API for research on public Facebook Pages.
    Compatible with Page Public Content Access review requirements.
    """

    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        access_token: str,
        api_version: str = "v21.0",
        timeout: int = 30,
    ):
        self.access_token = access_token.strip()
        self.api_version = api_version
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "StoryGraph-Research/1.0 (+http://storygraph.local)",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=8))
    def _get(self, endpoint: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        url = f"{self.BASE_URL}/{self.api_version}/{endpoint.lstrip('/')}"
        p = params.copy() if params else {}
        # Avoid putting token in query params if possible or pass via param if requested by Graph API
        if "access_token" not in p:
            p["access_token"] = self.access_token

        response = requests.get(url, params=p, timeout=self.timeout)
        if response.status_code != 200:
            try:
                err_data = response.json().get("error", {})
                err_msg = err_data.get("message", response.text)
                err_type = err_data.get("type", "GraphAPIError")
                _log.error(f"Graph API Error [{response.status_code}] ({err_type}): {err_msg}")
            except Exception:
                err_msg = response.text
            response.raise_for_status()

        return response.json()

    def get_page_details(self, page_id: str) -> dict[str, Any]:
        """Fetch basic public metadata for a Page."""
        fields = "id,name,link,about,description,fan_count,verification_status"
        return self._get(f"{page_id}", {"fields": fields})

    def get_page_feed(
        self,
        page_id: str,
        limit: int = 25,
        max_posts: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Fetch public posts from a Page feed.
        Corresponds to: GET /{PAGE_ID}/feed?fields=id,message,created_time,permalink_url,from&limit=25
        """
        fields = "id,message,created_time,permalink_url,from,shares,reactions.summary(true)"
        posts: list[dict[str, Any]] = []
        endpoint = f"{page_id}/feed"
        params: dict[str, Any] = {"fields": fields, "limit": min(limit, 100)}

        while endpoint and len(posts) < max_posts:
            data = self._get(endpoint, params)
            batch = data.get("data", [])
            if not batch:
                break
            posts.extend(batch)
            _log.info(f"Fetched {len(batch)} posts from Page {page_id} (total: {len(posts)})")

            # Check next pagination URL
            paging = data.get("paging", {})
            next_url = paging.get("next")
            if next_url and len(posts) < max_posts:
                # Use raw next endpoint or relative cursor
                cursors = paging.get("cursors", {})
                after = cursors.get("after")
                if after:
                    params["after"] = after
                else:
                    break
            else:
                break

        return posts[:max_posts]

    def get_post_comments(
        self,
        post_id: str,
        limit: int = 100,
        max_comments: int = 200,
    ) -> list[dict[str, Any]]:
        """
        Fetch public comments on a given post.
        Corresponds to: GET /{POST_ID}/comments?fields=id,message,created_time,from,permalink_url&limit=100
        """
        fields = "id,message,created_time,from,permalink_url,like_count"
        comments: list[dict[str, Any]] = []
        endpoint = f"{post_id}/comments"
        params: dict[str, Any] = {"fields": fields, "limit": min(limit, 100)}

        while endpoint and len(comments) < max_comments:
            data = self._get(endpoint, params)
            batch = data.get("data", [])
            if not batch:
                break
            comments.extend(batch)
            _log.info(f"Fetched {len(batch)} comments for Post {post_id} (total: {len(comments)})")

            paging = data.get("paging", {})
            cursors = paging.get("cursors", {})
            after = cursors.get("after")
            if after and len(comments) < max_comments:
                params["after"] = after
            else:
                break

        return comments[:max_comments]

    def collect_page_research(
        self,
        page_id: str,
        include_comments: bool = True,
        max_posts: int = 50,
        max_comments_per_post: int = 50,
    ) -> list[CrawledPage]:
        """
        Collects page posts and comment threads, formatted as CrawledPage objects
        for extraction and graph ingestion.
        """
        page_info = {}
        try:
            page_info = self.get_page_details(page_id)
        except Exception as e:
            _log.warning(f"Could not retrieve full page info for {page_id}: {e}")

        page_name = page_info.get("name", page_id)
        page_url = page_info.get("link", f"https://www.facebook.com/{page_id}")

        posts = self.get_page_feed(page_id, max_posts=max_posts)
        results: list[CrawledPage] = []

        for post in posts:
            post_id = post.get("id", "")
            message = post.get("message", "")
            created_time = post.get("created_time", "")
            permalink = post.get("permalink_url") or f"https://www.facebook.com/{post_id}"
            author_info = post.get("from", {})
            author_name = author_info.get("name", page_name)

            if not message:
                continue

            content_lines = [
                f"Facebook Public Page Post by {author_name}",
                f"Page: {page_name} (ID: {page_id})",
                f"Date: {created_time}",
                f"URL: {permalink}",
                "",
                message,
            ]

            if include_comments:
                try:
                    comments = self.get_post_comments(post_id, max_comments=max_comments_per_post)
                    if comments:
                        content_lines.append("\n--- Public Comments ---")
                        for c in comments:
                            c_author = c.get("from", {}).get("name", "Public User")
                            c_msg = c.get("message", "")
                            c_time = c.get("created_time", "")
                            if c_msg:
                                content_lines.append(f"[{c_time}] {c_author}: {c_msg}")
                except Exception as e:
                    _log.warning(f"Failed to fetch comments for post {post_id}: {e}")

            full_text = "\n".join(content_lines)

            results.append(
                CrawledPage(
                    url=permalink,
                    title=f"{page_name} Post ({created_time[:10] if created_time else 'Public'})",
                    text=full_text,
                    links=[],
                    author=author_name,
                    publish_date=created_time[:10] if created_time else None,
                    status_code=200,
                )
            )

        return results
