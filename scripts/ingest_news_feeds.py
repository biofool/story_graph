#!/usr/bin/env python3
"""
Poll RSS/Atom news feeds and record items that mention graph entities.

Reads the feed list from data/reference/news_feeds.json. For each feed item,
the title + description are matched (word-boundary, case-insensitive)
against the multi-word labels, canonical names, and aliases of existing
Person / Group / Dojo / Federation nodes. Single-word forms are ignored to
avoid false positives ("Moon", "The Source"). Items whose text trips the
out-of-scope filter (config/out_of_scope.json) are skipped, as are nodes
flagged out_of_scope or not_connected, and any form listed under
``ignore_entities`` in the feeds file (peripheral entities such as
politicians or militaries that appear constantly in general news).

A feed may set ``entity_id`` when its query already pins down one graph
entity (e.g. '"Robert Nadeau" aikido'); every item from that feed then
mentions that node even if the RSS snippet omits the name, since Google
matches against full article text. Only set it on disambiguated queries.

Each matching item becomes:
    - a SourceRecord (source_class=journalistic, platform=<outlet>)
    - a Work node (work_type=news_article) keyed by work_id(url)
    - Work -[MENTIONS]-> entity edges, metadata.via="news_feed"

Re-running is idempotent: sources are keyed by URL and nodes/edges upsert.
Designed to run on a schedule (e.g. daily); items that match nothing are
not written anywhere.

Usage:
    python scripts/ingest_news_feeds.py --dry-run
    python scripts/ingest_news_feeds.py
    python scripts/ingest_news_feeds.py --no-rebuild --no-export
"""

import argparse
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests

from config.settings import settings
from src.extractor.alias_resolver import work_id
from src.extractor.scope_filter import ScopeFilter
from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)
from src.utils.text_utils import hash_url, normalize

DEFAULT_FEEDS_PATH = PROJECT_ROOT / "data" / "reference" / "news_feeds.json"
MATCH_NODE_TYPES = (NodeType.PERSON, NodeType.GROUP, NodeType.DOJO, NodeType.FEDERATION)
MIN_FORM_WORDS = 2
MIN_FORM_CHARS = 6


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse RSS 2.0 or Atom into [{title, url, published, outlet, description}]."""
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        pub = it.findtext("pubDate")
        outlet = (it.findtext("source") or "").strip() or None
        title = (it.findtext("title") or "").strip()
        # Google News appends " - <Outlet>" to every title; drop it so the
        # outlet name ("The Conversation") is not matched as an entity.
        # The description repeats the outlet after the linked title.
        description = _strip_html(it.findtext("description") or "")
        if outlet and title.endswith(f" - {outlet}"):
            title = title[: -len(outlet) - 3].rstrip()
        if outlet and description.endswith(outlet):
            description = description[: -len(outlet)].rstrip()
        items.append({
            "title": title,
            "url": (it.findtext("link") or "").strip(),
            "published": _iso_date(pub),
            "outlet": outlet,
            "description": description,
        })
    atom = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom}entry"):
        link = entry.find(f"{atom}link")
        items.append({
            "title": (entry.findtext(f"{atom}title") or "").strip(),
            "url": (link.get("href") if link is not None else "") or "",
            "published": (entry.findtext(f"{atom}published")
                          or entry.findtext(f"{atom}updated") or "")[:10] or None,
            "outlet": None,
            "description": _strip_html(entry.findtext(f"{atom}summary") or ""),
        })
    return [i for i in items if i["url"] and i["title"]]


def _iso_date(rfc822: str | None) -> str | None:
    if not rfc822:
        return None
    try:
        return parsedate_to_datetime(rfc822).date().isoformat()
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def build_name_index(db: GraphDB, excluded_ids: set[str],
                     ignored_forms: set[str] = frozenset()) -> dict[str, str]:
    """Map normalized multi-word surface form -> node id.

    ``ignored_forms`` (normalized) drops peripheral entities that are in the
    graph but too common in general news to signal relevance.
    """
    index: dict[str, str] = {}
    for node_type in MATCH_NODE_TYPES:
        for node in db.get_nodes_by_type(node_type):
            meta = node.metadata or {}
            if node.id in excluded_ids or meta.get("out_of_scope") or meta.get("not_connected"):
                continue
            forms = [node.label, node.canonical_name, *(meta.get("aliases") or [])]
            for form in forms:
                if not isinstance(form, str):
                    continue
                norm = normalize(form)
                if norm in ignored_forms:
                    continue
                # "The Source" / "the farm" read as ordinary phrases in news
                # text, so a leading article doesn't count toward the words.
                core = norm.removeprefix("the ")
                if len(core.split()) >= MIN_FORM_WORDS and len(core) >= MIN_FORM_CHARS:
                    index.setdefault(norm, node.id)
    return index


def match_item(item: dict, index: dict[str, str]) -> dict[str, str]:
    """Return {node_id: matched_form} for entities named in the item."""
    text = f" {normalize(item['title'] + ' ' + item['description'])} "
    hits: dict[str, str] = {}
    for form, node_id in index.items():
        if f" {form} " in text:
            hits.setdefault(node_id, form)
    return hits


def item_hits(item: dict, feed: dict, index: dict[str, str]) -> dict[str, str]:
    """Name matches plus the feed's pinned ``entity_id``, if any."""
    hits = match_item(item, index)
    if feed.get("entity_id"):
        hits.setdefault(feed["entity_id"], f"feed:{feed['id']}")
    return hits


def records_for_item(item: dict, feed_id: str, hits: dict[str, str]):
    """Build the (source, work node, edges) written for one matched item."""
    url = item["url"]
    wid = work_id(url)
    source = SourceRecord(
        id=f"news:{hash_url(url)}",
        url=url,
        title=item["title"],
        publish_date=item["published"],
        platform=item["outlet"],
        raw_text=item["description"] or None,
        source_class=SourceClass.JOURNALISTIC,
    )
    work = GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=item["title"],
        metadata={
            "work_type": "news_article",
            "publish_date": item["published"],
            "outlet": item["outlet"],
            "feed_id": feed_id,
            "enriched_by": "scripts/ingest_news_feeds.py",
        },
        source_urls=[url],
    )
    edges = [
        GraphEdge(src_id=wid, rel_type=RelationType.MENTIONS, dst_id=node_id,
                  metadata={"via": "news_feed", "feed_id": feed_id, "matched_form": form})
        for node_id, form in sorted(hits.items())
    ]
    return source, work, edges


def fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=settings.crawl_timeout,
                        headers={"User-Agent": settings.crawl_user_agent})
    resp.raise_for_status()
    return resp.content


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--feeds", default=str(DEFAULT_FEEDS_PATH))
    ap.add_argument("--db", default=None)
    ap.add_argument("--snapshot", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch and match, print what would be written, write nothing")
    ap.add_argument("--no-export", action="store_true")
    ap.add_argument("--no-rebuild", action="store_true")
    args = ap.parse_args()

    config = json.loads(Path(args.feeds).read_text(encoding="utf-8"))
    feeds = config["feeds"]
    ignored_forms = {normalize(f) for f in config.get("ignore_entities", [])}
    db_path = args.db or str(settings.graph_db_abs_path)
    snapshot_dir = args.snapshot or str(settings.graph_snapshot_abs_dir)

    print("═══ INGEST news feeds — story_graph ═══\n")
    if args.dry_run:
        # Match against a throwaway rebuild so a dry run leaves data/graph.db alone.
        db_path = str(Path(tempfile.mkdtemp()) / "graph.db")
    rebuild = args.dry_run or not args.no_rebuild
    db = import_from_json(snapshot_dir, db_path) if rebuild else GraphDB(db_path)
    scope = ScopeFilter.from_config()
    index = build_name_index(db, scope.out_of_scope_node_ids(), ignored_forms)
    print(f"  matching against {len(index)} entity surface forms")

    stats = {"items": 0, "matched": 0, "out_of_scope": 0, "edges": 0, "feed_errors": 0}
    for feed in feeds:
        try:
            items = parse_feed(fetch(feed["url"]))
        except (requests.RequestException, ET.ParseError) as e:
            print(f"  feed FAIL {feed['id']}: {e}")
            stats["feed_errors"] += 1
            continue
        print(f"  feed {feed['id']}: {len(items)} items")
        for item in items:
            stats["items"] += 1
            hits = item_hits(item, feed, index)
            if not hits:
                continue
            if scope.is_page_out_of_scope(item["title"], item["description"], item["url"]):
                stats["out_of_scope"] += 1
                continue
            source, work, edges = records_for_item(item, feed["id"], hits)
            stats["matched"] += 1
            stats["edges"] += len(edges)
            print(f"    match {sorted(hits.values())} — {item['title'][:90]}")
            if args.dry_run:
                continue
            existing = db.get_source_by_url(source.url)
            if existing and existing.id != source.id:
                source.id = existing.id
            db.add_source(source)
            db.add_node(work)
            for edge in edges:
                db.add_edge(edge)

    print(f"\n  {'[dry-run] ' if args.dry_run else ''}{stats}")
    if not args.dry_run and not args.no_export and stats["matched"]:
        counts = export_to_json(db, snapshot_dir)
        print(f"  exported: {counts}")
    print("\nDone.")


if __name__ == "__main__":
    main()
