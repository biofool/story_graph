"""Unit tests for scripts/ingest_news_feeds.py (feed parsing + entity matching)."""

import tempfile

import pytest

from scripts.ingest_news_feeds import (
    build_name_index,
    item_hits,
    match_item,
    parse_feed,
    records_for_item,
)
from src.storage.graph_db import GraphDB
from src.storage.models import GraphNode, NodeType, RelationType

RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Robert Nadeau honored by Mountain View dojo - Local Paper</title>
    <link>https://news.example.com/a</link>
    <pubDate>Tue, 22 Sep 2026 17:57:22 GMT</pubDate>
    <source url="https://local.example.com">Local Paper</source>
    <description>&lt;a href="x"&gt;Aikido teacher&lt;/a&gt; celebrated Local Paper</description>
  </item>
  <item><title>No link item</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom story</title>
    <link href="https://news.example.com/b"/>
    <published>2026-09-20T10:00:00Z</published>
    <summary>Summary text</summary>
  </entry>
</feed>"""


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    db = GraphDB(path)
    db.add_node(GraphNode(id="person:robert-nadeau", type=NodeType.PERSON,
                          label="Robert Nadeau", metadata={"aliases": ["Bob Nadeau", "Nadeau"]}))
    db.add_node(GraphNode(id="person:moon", type=NodeType.PERSON, label="Moon"))
    db.add_node(GraphNode(id="place:the-source", type=NodeType.GROUP, label="The Source",
                          metadata={"aliases": ["The Source Family"]}))
    db.add_node(GraphNode(id="person:hidden", type=NodeType.PERSON, label="Hidden Person",
                          metadata={"not_connected": True}))
    db.add_node(GraphNode(id="work:x", type=NodeType.WORK, label="Robert Nadeau biography"))
    yield db
    db.close()


def test_parse_rss_and_atom():
    rss = parse_feed(RSS)
    assert len(rss) == 1  # item without link dropped
    assert rss[0]["title"] == "Robert Nadeau honored by Mountain View dojo"  # outlet suffix stripped
    assert rss[0]["published"] == "2026-09-22"
    assert rss[0]["outlet"] == "Local Paper"
    assert rss[0]["description"] == "Aikido teacher celebrated"
    atom = parse_feed(ATOM)
    assert atom[0]["url"] == "https://news.example.com/b"
    assert atom[0]["published"] == "2026-09-20"


def test_index_skips_single_word_flagged_and_non_entity_nodes(db):
    index = build_name_index(db, excluded_ids=set())
    assert index["robert nadeau"] == "person:robert-nadeau"
    assert index["bob nadeau"] == "person:robert-nadeau"
    assert "nadeau" not in index and "moon" not in index
    assert "the source" not in index  # leading article doesn't count as a word
    assert index["the source family"] == "place:the-source"
    assert "hidden person" not in index
    assert "robert nadeau biography" not in index


def test_index_honors_excluded_ids_and_ignored_forms(db):
    assert "robert nadeau" not in build_name_index(db, excluded_ids={"person:robert-nadeau"})
    index = build_name_index(db, excluded_ids=set(), ignored_forms={"bob nadeau"})
    assert "bob nadeau" not in index and "robert nadeau" in index


def test_match_is_word_bounded(db):
    index = build_name_index(db, excluded_ids=set())
    hit = {"title": "Robert Nadeau, teacher", "description": ""}
    miss = {"title": "Robert Nadeaux opens studio", "description": ""}
    assert match_item(hit, index) == {"person:robert-nadeau": "robert nadeau"}
    assert match_item(miss, index) == {}


def test_records_for_item():
    item = parse_feed(RSS)[0]
    source, work, edges = records_for_item(item, "feed-a", {"person:robert-nadeau": "robert nadeau"})
    assert source.url == work.source_urls[0] == "https://news.example.com/a"
    assert source.source_class.value == "journalistic"
    assert work.metadata["work_type"] == "news_article"
    assert [(e.src_id, e.rel_type, e.dst_id) for e in edges] == [
        (work.id, RelationType.MENTIONS, "person:robert-nadeau")]


def test_item_hits_adds_pinned_entity(db):
    index = build_name_index(db, excluded_ids=set())
    item = {"title": "Aikido school opens", "description": ""}
    assert item_hits(item, {"id": "generic"}, index) == {}
    pinned = {"id": "gnews-nadeau", "entity_id": "person:robert-nadeau"}
    assert item_hits(item, pinned, index) == {"person:robert-nadeau": "feed:gnews-nadeau"}
    named = {"title": "Robert Nadeau teaches", "description": ""}
    assert item_hits(named, pinned, index) == {"person:robert-nadeau": "robert nadeau"}
