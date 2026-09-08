#!/usr/bin/env python3
"""
Ingest Peter Ralston URLs and Bob Noha research into the Story Graph.

Adds:
- Source records for all provided Ralston URLs
- Book nodes for Ralston's published works (from Open Library)
- Podcast/video nodes for YouTube interviews
- Updated Person metadata for Peter Ralston
- Updated Person metadata for Bob Noha (with full biography)
- New source records for Bob Noha URLs
- TEACHER_STUDENT edge: Nadeau → Noha
- HEAD_INSTRUCTOR edge: Noha → Aikido of Petaluma
- Rank history for Bob Noha (5th dan 2000, 6th dan 2013, 7th dan 2025)

Usage:
    python scripts/28_ingest_ralston_noha.py
    python scripts/28_ingest_ralston_noha.py --dry-run
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.lineage_db import LineageDB
from src.storage.models import (
    GraphNode, GraphEdge, NodeType, RelationType,
    SourceRecord, SourceClass,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
_log = logging.getLogger("ingest_ralston_noha")


# ============================================================
# PETER RALSTON — URLs to ingest as source records
# ============================================================

RALSTON_SOURCES = [
    # Official / Cheng Hsin
    {"url": "https://chenghsin.com/who-is-peter-ralston/",
     "title": "Who is Peter Ralston? — Cheng Hsin",
     "platform": "chenghsin.com", "source_class": "official_bio"},
    {"url": "https://chenghsin.com/origins-interview-with-peter-ralston/",
     "title": "Origins Interview with Peter Ralston — Cheng Hsin",
     "platform": "chenghsin.com", "source_class": "interview"},
    {"url": "https://chenghsin.com",
     "title": "Cheng Hsin — Official Site",
     "platform": "chenghsin.com", "source_class": "official_site"},
    # Publisher / author bios
    {"url": "https://www.penguin.co.nz/authors/peter-ralston",
     "title": "Peter Ralston — Penguin Books New Zealand",
     "platform": "penguin.co.nz", "source_class": "publisher_bio"},
    {"url": "https://www.innertraditions.com/author/peter-ralston",
     "title": "Peter Ralston — Inner Traditions",
     "platform": "innertraditions.com", "source_class": "publisher_bio"},
    # Books / bibliographic and reviews
    {"url": "https://www.amazon.com.au/Book-Not-Knowing-Peter-Ralston/dp/1556438575",
     "title": "The Book of Not Knowing — Amazon",
     "platform": "amazon.com.au", "source_class": "book_listing"},
    {"url": "https://www.goodreads.com/en/book/show/9315473-the-book-of-not-knowing",
     "title": "The Book of Not Knowing — Goodreads",
     "platform": "goodreads.com", "source_class": "book_review"},
    {"url": "https://cdn.bookey.app/files/pdf/book/en/the-book-of-not-knowing.pdf",
     "title": "The Book of Not Knowing — Bookey PDF Summary",
     "platform": "bookey.app", "source_class": "book_summary"},
    {"url": "https://openlibrary.org/search.json?author=Peter+Ralston",
     "title": "Open Library: Peter Ralston books",
     "platform": "openlibrary.org", "source_class": "bibliographic_api"},
    # Independent profiles / essays
    {"url": "https://blog.chrisremspecher.de/tag/peter-ralston",
     "title": "Peter Ralston — Chris Remspecher Blog",
     "platform": "blog.chrisremspecher.de", "source_class": "independent_profile"},
    {"url": "https://thebrendanlea.com/radical-relaxation/",
     "title": "Radical Relaxation — The Brendan Lea",
     "platform": "thebrendanlea.com", "source_class": "independent_essay"},
    # Independent secondary sources confirming 1978 World Championship
    {"url": "https://www.simonandschuster.com/authors/Peter-Ralston/199333325",
     "title": "Peter Ralston — Simon & Schuster Author Page",
     "platform": "simonandschuster.com", "source_class": "publisher_bio"},
    {"url": "https://en-academic.com/dic.nsf/enwiki/10270380",
     "title": "Peter Ralston — Academic Dictionaries and Encyclopedias",
     "platform": "en-academic.com", "source_class": "independent_profile"},
    {"url": "https://www.taijiquan.nl/912-2/",
     "title": "History — Taijiquan Association Netherlands (mentions Ralston 1978 World Championship)",
     "platform": "taijiquan.nl", "source_class": "independent_profile"},
    {"url": "https://blog.awma.com/zen-in-the-martial-arts/",
     "title": "Zen in the Martial Arts — AWMA Blog (Peter Ralston feature, 1978 World Championship)",
     "platform": "blog.awma.com", "source_class": "independent_essay"},
    {"url": "https://www.usadojo.com/peter-ralston/",
     "title": "Peter Ralston Cheng Hsin — USAdojo.com Profile",
     "platform": "usadojo.com", "source_class": "independent_profile"},
    # Interviews / media (YouTube)
    {"url": "https://www.youtube.com/watch?v=xZxLygFdW8A",
     "title": "Improving Relationships — Peter Ralston interview",
     "platform": "youtube.com", "source_class": "video_interview"},
    {"url": "https://www.youtube.com/watch?v=GeJIcDLOa8Q",
     "title": "Our Shared Reality is Made Up — Peter Ralston interview",
     "platform": "youtube.com", "source_class": "video_interview"},
    {"url": "https://www.youtube.com/watch?v=xuf8ps0ZsAY",
     "title": "Perception is Based On Survival — Peter Ralston interview",
     "platform": "youtube.com", "source_class": "video_interview"},
    {"url": "https://www.youtube.com/watch?v=pXM4WCLnxS8",
     "title": "Honesty — Peter Ralston interview",
     "platform": "youtube.com", "source_class": "video_interview"},
    {"url": "https://www.youtube.com/watch?v=P_I8GC4e9YY",
     "title": "The Book of Not Knowing review, Part 1 — YouTube",
     "platform": "youtube.com", "source_class": "video_review"},
    # Related martial-arts / book context
    {"url": "https://budovideos.com/products/aikido-the-art-of-transformation-the-life-and-teachings-of-robert-nadeau",
     "title": "Aikido: The Art of Transformation — The Life and Teachings of Robert Nadeau",
     "platform": "budovideos.com", "source_class": "book_context"},
]

# Open Library works for Peter Ralston (author key OL234913A and OL8070830A)
RALSTON_BOOKS = [
    {"ol_key": "OL1957444W", "title": "The Book of Not Knowing",
     "first_publish_year": 2010, "edition_count": 1, "language": "eng"},
    {"ol_key": "OL1957449W", "title": "Cheng Hsin",
     "subtitle": "the principles of effortless power",
     "first_publish_year": 1989, "edition_count": 3, "language": "eng"},
    {"ol_key": "OL14924459W", "title": "Zen Body-Being",
     "subtitle": "An Enlightened Approach to Physical Skill, Grace, and Power",
     "first_publish_year": 2006, "edition_count": 1, "language": "eng"},
    {"ol_key": "OL1957446W", "title": "Cheng Hsin Tui Shou",
     "subtitle": "The Art of Effortless Power",
     "first_publish_year": 1991, "edition_count": 2, "language": "eng"},
    {"ol_key": "OL1957443W", "title": "Ancient Wisdom, New Spirit",
     "subtitle": "investigations into the nature of \"being\"",
     "first_publish_year": 1994, "edition_count": 1, "language": "eng"},
    {"ol_key": "OL1957447W", "title": "Reflections of Being",
     "subtitle": "To `I` or not to `I`",
     "first_publish_year": 1991, "edition_count": 2, "language": "eng"},
    {"ol_key": "OL21092788W", "title": "Pursuing Consciousness",
     "first_publish_year": 2015, "edition_count": 3, "language": "eng"},
    {"ol_key": "OL21159368W", "title": "Consciousness Dialogues",
     "first_publish_year": 2018, "edition_count": 1, "language": "eng"},
    {"ol_key": "OL21131227W", "title": "Genius of Being",
     "first_publish_year": 2017, "edition_count": 1, "language": "eng"},
    {"ol_key": "OL28728342W", "title": "Art of Mastery",
     "first_publish_year": 2023, "edition_count": 2, "language": "eng"},
    {"ol_key": "OL42403134W", "title": "Ending Unnecessary Suffering",
     "first_publish_year": 2025, "edition_count": 2, "language": "eng"},
    {"ol_key": "OL39733123W", "title": "Integrity of Being",
     "first_publish_year": 1977, "edition_count": 1, "language": "eng"},
]

# ============================================================
# BOB NOHA — Research data
# ============================================================

NOHA_SOURCES = [
    {"url": "https://www.aikidopetaluma.com/our-sensei/",
     "title": "Our Sensei — Robert 'Bob' Noha, Aikido of Petaluma",
     "platform": "aikidopetaluma.com", "source_class": "official_bio"},
    {"url": "https://www.aikidopetaluma.com/",
     "title": "Aikido of Petaluma — Official Site",
     "platform": "aikidopetaluma.com", "source_class": "official_site"},
    {"url": "https://www.aikidopetaluma.com/2015/09/20/profile-robert-noha-article-from-the-argus-courier-may-14-2003/",
     "title": "Profile: Robert Noha — Argus Courier, May 14, 2003",
     "platform": "aikidopetaluma.com", "source_class": "news_profile"},
    {"url": "https://aikidojournal.com/2020/06/09/aikido-as-an-art-of-personal-development-and-spiritual-growth-by-bob-noha/",
     "title": "Aikido as an Art of Personal Development and Spiritual Growth, by Bob Noha — Aikido Journal",
     "platform": "aikidojournal.com", "source_class": "contributed_article"},
    {"url": "https://www.simonandschuster.net/authors/Bob-Noha/221805037",
     "title": "Bob Noha — Simon & Schuster",
     "platform": "simonandschuster.net", "source_class": "publisher_bio"},
    {"url": "https://www.nadeaushihan.com/authors",
     "title": "Authors — Robert Nadeau Shihan (Bob Noha bio)",
     "platform": "nadeaushihan.com", "source_class": "publisher_bio"},
    {"url": "https://medium.com/authority-magazine/bob-noha-on-how-martial-arts-helped-teach-self-confidence-bravery-career-success-d92975e5da46",
     "title": "Bob Noha On How Martial Arts Helped Teach Self-Confidence — Authority Magazine",
     "platform": "medium.com", "source_class": "interview"},
    {"url": "https://maytt.home.blog/2021/02/17/interview-with-californian-aikidoka-robert-noha-aikidos-spiritual-aspect/",
     "title": "Interview with Californian Aikidoka Robert Noha: Aikido's Spiritual Aspect — Martial Arts of Yesterday, Today and Tomorrow",
     "platform": "maytt.home.blog", "source_class": "interview"},
]

# Bob Noha rank history
NOHA_RANKS = [
    {"rank_level": "5th dan", "awarded_date": "2000-01-01",
     "awarded_by": "person:robert-nadeau",
     "source_url": "https://www.aikidopetaluma.com/our-sensei/"},
    {"rank_level": "6th dan", "awarded_date": "2013-01-01",
     "awarded_by": None,  # recommended by Robert Frager and Hiroshi Kato Shihan
     "source_url": "https://www.aikidopetaluma.com/our-sensei/"},
    {"rank_level": "7th dan", "awarded_date": "2025-01-01",
     "awarded_by": None,  # recommended by Bill Witt and John Stevens
     "source_url": "https://www.aikidopetaluma.com/our-sensei/"},
]

# Bob Noha dojos founded
NOHA_DOJOS = [
    {"name": "Aikido of College Park", "city": "College Park", "state": "MD",
     "country": "US", "year": 1970, "notes": "First Aikido school in Washington DC area"},
    {"name": "Aikido of Buffalo", "city": "Buffalo", "state": "NY",
     "country": "US", "year": 1975, "notes": "First Aikido school in Buffalo area"},
    {"name": "Aikido of Novato", "city": "Novato", "state": "CA",
     "country": "US", "year": 1982, "notes": ""},
    {"name": "Aikido of Petaluma", "city": "Petaluma", "state": "CA",
     "country": "US", "year": 1983, "notes": "Current chief instructor"},
]


def slugify(text):
    import re
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')


def run_ingestion(gdb: GraphDB, ldb: LineageDB, dry_run: bool = False) -> dict:
    stats = {"sources_added": 0, "books_added": 0, "nodes_updated": 0,
             "edges_added": 0, "ranks_recorded": 0, "dojos_added": 0}

    # ============================================================
    # 1. Add Ralston source records
    # ============================================================
    _log.info("Adding %d Ralston source records", len(RALSTON_SOURCES))
    for src in RALSTON_SOURCES:
        if dry_run:
            stats["sources_added"] += 1
            continue
        existing = gdb.get_source_by_url(src["url"])
        if not existing:
            import hashlib
            src_id = f"src:{hashlib.sha256(src['url'].encode()).hexdigest()[:16]}"
            source_class = None
            # Map source_class string to SourceClass enum
            sc = src["source_class"]
            if sc in ("official_bio", "official_site", "publisher_bio"):
                source_class = SourceClass.DOCUMENTARY_PROMOTIONAL
            elif sc in ("interview",):
                source_class = SourceClass.JOURNALISTIC
            elif sc in ("contributed_article", "independent_profile", "independent_essay"):
                source_class = SourceClass.JOURNALISTIC
            elif sc in ("news_profile",):
                source_class = SourceClass.JOURNALISTIC
            elif sc in ("book_listing", "book_review", "book_summary", "bibliographic_api", "book_context"):
                source_class = SourceClass.DOCUMENTARY_PROMOTIONAL
            elif sc in ("video_interview", "video_review"):
                source_class = SourceClass.JOURNALISTIC
            gdb.add_source(SourceRecord(
                id=src_id,
                url=src["url"],
                title=src["title"],
                platform=src["platform"],
                source_class=source_class,
            ))
            stats["sources_added"] += 1

    # ============================================================
    # 2. Add Ralston book nodes (from Open Library)
    # ============================================================
    _log.info("Adding %d Ralston book nodes", len(RALSTON_BOOKS))
    for book in RALSTON_BOOKS:
        book_id = f"book:{slugify(book['title'])}"
        if dry_run:
            stats["books_added"] += 1
            continue

        # Add to lineage_books
        ldb.upsert_book(
            node_id=book_id,
            title=book["title"],
            subtitle=book.get("subtitle"),
            openlibrary_key=book["ol_key"],
            publish_date=str(book["first_publish_year"]),
            author_ids=["person:peter-ralston"],
            language=book.get("language", "en"),
            metadata={
                "edition_count": book.get("edition_count"),
                "source": "openlibrary_api",
                "ol_url": f"https://openlibrary.org/works/{book['ol_key']}",
            },
        )

        # Add to generic graph as Work node
        existing = gdb.get_node(book_id)
        if not existing:
            node = GraphNode(
                id=book_id,
                type=NodeType.WORK,
                label=book["title"],
                canonical_name=book["title"],
                metadata={
                    "subtitle": book.get("subtitle"),
                    "openlibrary_key": book["ol_key"],
                    "first_publish_year": book["first_publish_year"],
                    "author": "Peter Ralston",
                    "source": "openlibrary_api",
                },
                source_urls=[f"https://openlibrary.org/works/{book['ol_key']}"],
            )
            gdb.add_node(node)

        # CO_AUTHORED edge: Ralston → Book
        gdb.add_edge(GraphEdge(
            src_id="person:peter-ralston",
            rel_type=RelationType.CO_AUTHORED,
            dst_id=book_id,
            metadata={"source": "openlibrary_api"},
        ))
        ldb.insert_lineage_edge(
            "person:peter-ralston", "CO_AUTHORED", book_id,
            confidence=0.95,
            source_url=f"https://openlibrary.org/works/{book['ol_key']}",
            discovered_via="openlibrary_api",
            review_status="auto",
            metadata={"role": "author"},
        )
        stats["books_added"] += 1

    # ============================================================
    # 3. Update Peter Ralston person metadata
    # ============================================================
    if not dry_run:
        ralston_meta = {
            "context": "Martial artist, consciousness teacher, author",
            "birth_place": "San Francisco, California",
            "raised": "Primarily in Asia (Singapore, Japan)",
            "occupation": "Martial arts teacher, consciousness facilitator, author",
            "martial_arts": ["Judo", "Jujitsu", "Karate", "Kempo", "Ch'uan Fa",
                            "Northern Sil Lum Kung Fu", "T'ai Chi Ch'uan",
                            "Hsing I Ch'uan", "Pa Kua Chang", "Aikido",
                            "Japanese fencing", "Chinese fencing",
                            "Western boxing", "Muay Thai"],
            "ranks": ["Black belt in Judo", "Black belt in Jujitsu", "Black belt in Karate"],
            "achievements": [
                "Sumo champion at high school in Japan",
                "Judo and fencing champion at UC Berkeley",
                "First non-Asian to win World Championship full-contact martial arts tournament (1978, Republic of China)",
            ],
            "founded": {
                "name": "Cheng Hsin School",
                "year": 1975,
                "location": "Oakland, California",
                "full_name": "The Cheng Hsin School of Internal Martial Arts and Center for Ontological Research",
            },
            "books": [b["title"] for b in RALSTON_BOOKS],
            "movement": "Consciousness movement (San Francisco Bay Area, late 1960s-1970s)",
            "collaborators": ["Stewart Emery", "Werner Erhard", "Charles Berner"],
            "wikipedia_exists": False,
            "wikipedia_gap": True,
            "official_url": "https://chenghsin.com",
            "youtube_channel": "https://www.youtube.com/peterralston",
            "facebook": "https://www.facebook.com/OfficialRalston/",
            "instagram": "https://www.instagram.com/chenghsinarts/",
        }
        # Update generic graph node metadata
        conn = sqlite3.connect(str(settings.graph_db_abs_path))
        conn.execute(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?",
            (json.dumps(ralston_meta), "person:peter-ralston"),
        )
        conn.commit()
        conn.close()
        # Update lineage_persons
        ldb.upsert_person(
            "person:peter-ralston", "Peter Ralston",
            aliases=["Peter Ralston"],
            birth_place="San Francisco, California",
            primary_art="Cheng Hsin",
            official_url="https://chenghsin.com",
            primary_url="https://chenghsin.com",
            wikipedia_url=None,
            kg_id=None,
            metadata=ralston_meta,
        )
        stats["nodes_updated"] += 1

    # ============================================================
    # 4. Add YouTube interview nodes
    # ============================================================
    youtube_videos = [s for s in RALSTON_SOURCES if s["platform"] == "youtube.com"]
    for vid in youtube_videos:
        vid_id = f"pod:yt-{vid['url'].split('v=')[1]}"
        if dry_run:
            continue
        existing = gdb.get_node(vid_id)
        if not existing:
            node = GraphNode(
                id=vid_id,
                type=NodeType.PODCAST,
                label=vid["title"],
                canonical_name=vid["title"],
                metadata={
                    "url": vid["url"],
                    "platform": "YouTube",
                    "source_class": vid["source_class"],
                    "person": "person:peter-ralston",
                },
                source_urls=[vid["url"]],
            )
            gdb.add_node(node)

        # MENTIONS edge: video → Ralston
        gdb.add_edge(GraphEdge(
            src_id=vid_id,
            rel_type=RelationType.MENTIONS,
            dst_id="person:peter-ralston",
            metadata={"source": "youtube"},
        ))
        stats["edges_added"] += 1

    # ============================================================
    # 5. Add Bob Noha source records
    # ============================================================
    _log.info("Adding %d Noha source records", len(NOHA_SOURCES))
    for src in NOHA_SOURCES:
        if dry_run:
            stats["sources_added"] += 1
            continue
        existing = gdb.get_source_by_url(src["url"])
        if not existing:
            import hashlib
            src_id = f"src:{hashlib.sha256(src['url'].encode()).hexdigest()[:16]}"
            source_class = None
            sc = src["source_class"]
            if sc in ("official_bio", "official_site", "publisher_bio"):
                source_class = SourceClass.DOCUMENTARY_PROMOTIONAL
            elif sc in ("interview", "news_profile", "contributed_article"):
                source_class = SourceClass.JOURNALISTIC
            gdb.add_source(SourceRecord(
                id=src_id,
                url=src["url"],
                title=src["title"],
                platform=src["platform"],
                source_class=source_class,
            ))
            stats["sources_added"] += 1

    # ============================================================
    # 6. Update Bob Noha person metadata
    # ============================================================
    if not dry_run:
        noha_meta = {
            "canonical_name": "Robert Noha",
            "aliases": ["Bob Noha", "Robert 'Bob' Noha", "Sensei Robert Noha"],
            "birth_place": "Chicago, Illinois",
            "ethnicity": "Czechoslovakian-American",
            "rank": "7th dan",
            "rank_system": "Aikido",
            "primary_art": "Aikido",
            "cross_training": ["T'ai Chi Ch'uan", "Judo", "Kenpo Karate",
                              "Pa Kua Chang", "Hsing-I", "Western boxing"],
            "taichi_lineage": "Yang short form (Cheng Man-Ching → Robert W. Smith)",
            "started_aikido": "1966, Mountain View, CA",
            "first_teachers": ["Ed Riggs", "Sig Kufferath"],
            "main_teacher": "Robert Nadeau",
            "teacher_relationship": "Lifelong friendship and training with Robert Nadeau Shihan",
            "education": "University of Maryland, Philosophy",
            "military_service": "U.S. Air Force reserves",
            "military_instruction": "Security Police Tactics instructor, Andrews Air Force Base (1974-1975)",
            "dojos_founded": [
                {"name": "College Park Aikido", "location": "College Park, MD", "year": 1970},
                {"name": "Aikido of Buffalo", "location": "Buffalo, NY", "year": 1975},
                {"name": "Aikido of Novato", "location": "Novato, CA", "year": 1982},
                {"name": "Aikido of Petaluma", "location": "Petaluma, CA", "year": 1983},
            ],
            "current_dojo": "Aikido of Petaluma",
            "current_role": "Chief Instructor",
            "japan_training_trips": [1998, 1999, 2006],
            "co_author_of": "Aikido: The Art of Transformation — The Life and Teachings of Robert Nadeau",
            "business_career": "Insurance industry, retired after 42 years",
            "family": "Married 50 years, two children, four grandchildren",
            "wikipedia_exists": False,
            "official_url": "https://www.aikidopetaluma.com/our-sensei/",
        }
        # Update generic graph node metadata
        conn = sqlite3.connect(str(settings.graph_db_abs_path))
        conn.execute(
            "UPDATE nodes SET metadata_json = ? WHERE id = ?",
            (json.dumps(noha_meta), "person:bob-noha"),
        )
        conn.execute(
            "UPDATE nodes SET canonical_name = 'Robert Noha', label = 'Robert Noha' WHERE id = 'person:bob-noha'"
        )
        conn.commit()
        conn.close()

        # Update lineage_persons
        ldb.upsert_person(
            "person:bob-noha", "Robert Noha",
            aliases=["Bob Noha", "Robert 'Bob' Noha", "Sensei Robert Noha"],
            birth_place="Chicago, Illinois",
            primary_art="Aikido",
            current_rank="7th dan",
            official_url="https://www.aikidopetaluma.com/our-sensei/",
            primary_url="https://www.aikidopetaluma.com",
            metadata=noha_meta,
        )
        stats["nodes_updated"] += 1

    # ============================================================
    # 7. Add TEACHER_STUDENT edge: Nadeau → Noha
    # ============================================================
    if not dry_run:
        gdb.add_edge(GraphEdge(
            src_id="person:robert-nadeau",
            rel_type=RelationType.TEACHER_STUDENT,
            dst_id="person:bob-noha",
            metadata={
                "source": "aikidopetaluma.com",
                "context": "Lifelong friendship and training since 1966",
                "start_year": 1966,
            },
        ))
        ldb.insert_lineage_edge(
            "person:robert-nadeau", "TEACHER_STUDENT", "person:bob-noha",
            confidence=0.95,
            source_url="https://www.aikidopetaluma.com/our-sensei/",
            discovered_via="web_research",
            review_status="approved",
            valid_from="1966-01-01",
            metadata={
                "context": "Lifelong friendship and training since 1966",
                "start_year": 1966,
            },
        )
        stats["edges_added"] += 1

    # ============================================================
    # 8. Record Bob Noha rank history
    # ============================================================
    for rank in NOHA_RANKS:
        if dry_run:
            stats["ranks_recorded"] += 1
            continue
        ldb.record_rank_change(
            person_id="person:bob-noha",
            new_rank=rank["rank_level"],
            awarded_date=rank["awarded_date"],
            awarded_by=rank["awarded_by"],
            source_url=rank["source_url"],
            rank_system="aikikai",
        )
        stats["ranks_recorded"] += 1

    # ============================================================
    # 9. Add Bob Noha dojo nodes + HEAD_INSTRUCTOR edges
    # ============================================================
    for dojo in NOHA_DOJOS:
        dojo_id = f"dojo:{slugify(dojo['name'])}"
        if dry_run:
            stats["dojos_added"] += 1
            continue

        # Check if dojo already exists in lineage_dojos
        existing = ldb.get_dojo(dojo_id)
        if not existing:
            ldb.upsert_dojo(
                node_id=dojo_id,
                name=dojo["name"],
                head_instructor="person:bob-noha",
                city=dojo["city"],
                state=dojo["state"],
                country=dojo["country"],
                lineage="nadeau",
                federation_id="fed:caa",
                metadata={
                    "source": "web_research",
                    "founded_year": dojo["year"],
                    "notes": dojo["notes"],
                },
            )

            # Add to generic graph
            if not gdb.get_node(dojo_id):
                gdb.add_node(GraphNode(
                    id=dojo_id,
                    type=NodeType.DOJO,
                    label=dojo["name"],
                    canonical_name=dojo["name"],
                    metadata={
                        "city": dojo["city"], "state": dojo["state"],
                        "country": dojo["country"], "lineage": "nadeau",
                        "founded_year": dojo["year"],
                    },
                ))

            # HEAD_INSTRUCTOR edge
            ldb.insert_lineage_edge(
                "person:bob-noha", "HEAD_INSTRUCTOR", dojo_id,
                confidence=0.95,
                source_url="https://www.aikidopetaluma.com/our-sensei/",
                discovered_via="web_research",
                review_status="approved",
                valid_from=f"{dojo['year']}-01-01",
                metadata={"is_primary": True, "source": "web_research"},
            )
            gdb.add_edge(GraphEdge(
                src_id="person:bob-noha",
                rel_type=RelationType.HEAD_INSTRUCTOR,
                dst_id=dojo_id,
                metadata={"source": "web_research", "founded_year": dojo["year"]},
            ))

            # FOUNDED edge
            gdb.add_edge(GraphEdge(
                src_id="person:bob-noha",
                rel_type=RelationType.FOUNDED,
                dst_id=dojo_id,
                metadata={"year": dojo["year"], "source": "web_research"},
            ))

            stats["dojos_added"] += 1

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Peter Ralston URLs and Bob Noha research into the Story Graph"
    )
    parser.add_argument("--db", default=None, help="Database path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    db_path = args.db or str(settings.graph_db_abs_path)

    print()
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  INGEST RALSTON + NOHA — Story Graph                               ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    print()
    print(f"Database: {db_path}")
    print(f"Mode:     {'DRY RUN' if args.dry_run else 'EXECUTE'}")
    print()

    gdb = GraphDB(db_path)
    ldb = LineageDB(db_path)

    try:
        stats = run_ingestion(gdb, ldb, dry_run=args.dry_run)

        print()
        print("─── Ingestion Summary ───")
        print(f"  Sources added:       {stats['sources_added']:>4}")
        print(f"  Books added:         {stats['books_added']:>4}")
        print(f"  Nodes updated:       {stats['nodes_updated']:>4}")
        print(f"  Edges added:         {stats['edges_added']:>4}")
        print(f"  Ranks recorded:      {stats['ranks_recorded']:>4}")
        print(f"  Dojos added:         {stats['dojos_added']:>4}")
        print()
        print("Done.")

    finally:
        ldb.close()


if __name__ == "__main__":
    main()
