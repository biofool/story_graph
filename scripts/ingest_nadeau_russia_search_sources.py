#!/usr/bin/env python3
"""Ingest new sources found during the Aikido Journal / Black Belt Magazine /
Soviet sports newspaper search for Nadeau's Russia trip coverage.

New sources:
1. lenkai.spb.ru — Lenkai club history page, written by Sergey Kiselev,
   founder of Lenkai and first President of the USSR Aikido Federation.
   First-person account of aikido development in the USSR, including the
   first All-Union Seminar (Jan 1990) and Nadeau's visit (Oct 27, 1990).
2. kannagara-aikido.ru — Koichi Barrish sensei bio, confirms Barrish was
   first American aikido instructor to visit Moscow (1987), providing
   timeline context for Nadeau's 1990 visit.
3. BigRock Aikikai — Jamie Zimron interview, confirms she helped bring
   aikido to the Soviet Union (1987-1991) with Barrish.
4. cityaikido.com — Nadeau Shihan page, confirms Russia in list of
   countries where he influenced teachers.
5. en.aikido.ru — English-language USSR Aikido Federation history,
   documents the founding of the USSR Aikido Federation and seminars.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"


def get_domain(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


NEW_SOURCES = [
    {
        "url": "https://lenkai.spb.ru/ajkido-v-sssr/",
        "title": "Айкидо в СССР (Aikido in the USSR) — Lenkai Club History",
        "platform": "lenkai.spb.ru",
        "source_class": "archival",
        "bias_hint": "neutral_ish",
        "publisher": "Клуб айкидо Ленкай (Lenkai Aikido Club, St. Petersburg)",
        "note": (
            "First-person history of aikido in the USSR by Sergey Kiselev, "
            "founder of the Lenkai club and first/only President of the "
            "USSR Aikido Federation. Documents the first All-Union Aikido "
            "Seminar (January 1990, Moscow) and the founding of the USSR "
            "Aikido Federation. Independent archival source — written by "
            "a direct participant in the events."
        ),
    },
    {
        "url": "http://www.kannagara-aikido.ru/mentors/KoichiBarrish/",
        "title": "Коити Бэрриш-сэнсэй (Koichi Barrish) — Kannagara Aikido Moscow",
        "platform": "kannagara-aikido.ru",
        "source_class": "archival",
        "bias_hint": "neutral_ish",
        "publisher": "Moscow Aikido Kannagara Dojo",
        "note": (
            "Bio of Koichi Barrish sensei on the Moscow Kannagara Dojo site. "
            "Confirms Barrish first visited Moscow in 1987 and conducted "
            "annual seminars through the mid-1990s. Provides timeline context "
            "for Nadeau's October 1990 visit."
        ),
    },
    {
        "url": "https://www.bigrock-aikikai.com/ferocious-and-female/interview-jamie-zimron-sensei-(6th-dan).html",
        "title": "Interview with Jamie Zimron Sensei — BigRock Aikikai (Jan 2022)",
        "platform": "bigrock-aikikai.com",
        "source_class": "journalistic",
        "bias_hint": "neutral_ish",
        "publisher": "BigRock Aikikai",
        "note": (
            "Interview with Jamie Zimron (7th dan), who helped bring aikido "
            "to the former Soviet Union starting in 1987 with Koichi Barrish. "
            "Confirms American aikido instructors were visiting the USSR "
            "from 1987-1991, providing context for Nadeau's 1990 visit."
        ),
    },
    {
        "url": "https://www.cityaikido.com/nadeau-shihan",
        "title": "Nadeau Shihan — City Aikido of San Francisco",
        "platform": "cityaikido.com",
        "source_class": "documentary_promotional",
        "bias_hint": "defensive",
        "publisher": "City Aikido of San Francisco",
        "note": (
            "Nadeau's own dojo's page about him. Confirms he 'profoundly "
            "influenced generations of Aikido teachers in America, Europe, "
            "Russia, Israel, and New Zealand.' Affiliated source (ABOUTSELF)."
        ),
    },
    {
        "url": "http://en.aikido.ru/p/content/content.php?content.22.=",
        "title": "Kitaura sensei practice in Russia — Aikido.ru (IEAAF)",
        "platform": "aikido.ru",
        "source_class": "archival",
        "bias_hint": "neutral_ish",
        "publisher": "International Euro-Asian Aikido Federation (IEAAF)",
        "note": (
            "English-language history of aikido in Russia on the IEAAF site. "
            "Documents the USSR Aikido Federation, the first All-Union seminar, "
            "and international instructor visits to Leningrad. Provides "
            "context for Nadeau's visit within the broader timeline of "
            "foreign aikido instructors teaching in the USSR."
        ),
    },
]


def main() -> int:
    print("=" * 70)
    print("  Ingest new Russia-trip sources from archive search")
    print("=" * 70)

    # Read existing sources
    sources = []
    with open(SNAPSHOT_DIR / "sources.jsonl") as f:
        for line in f:
            sources.append(json.loads(line))

    existing_urls = {s.get("url", "") for s in sources}
    added = 0

    for src in NEW_SOURCES:
        url = src["url"]
        if url in existing_urls:
            print(f"  Already in graph: {url[:70]}")
            continue

        # Create source record
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        source_id = f"work:{url_hash}"

        record = {
            "id": source_id,
            "url": url,
            "title": src["title"],
            "platform": src["platform"],
            "source_class": src["source_class"],
            "bias_hint": src["bias_hint"],
            "raw_text": "",  # Will be filled by crawler if needed
        }
        sources.append(record)
        added += 1
        print(f"  Added: {url[:70]}")
        print(f"    source_class: {src['source_class']}")
        print(f"    publisher: {src['publisher']}")

    # Write back
    with open(SNAPSHOT_DIR / "sources.jsonl", "w") as f:
        for s in sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"\nAdded {added} new sources. Total: {len(sources)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
