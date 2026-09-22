#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

WADA_ID = "person:jack-wada"
FRAGER_ID = "person:robert-frager"
DOJO_ID = "dojo:aikido-of-san-jose"
CURRENT_URL = "https://aikidosj.com/"
INSTRUCTORS_URL = "https://aikidosj.com/ref/instructors/"
CITY_AIKIDO_URL = "https://www.cityaikido.com/jack-wada"


def source_id(url: str) -> str:
    return f"src:{hashlib.sha256(url.encode()).hexdigest()[:16]}"


def ingest(gdb: GraphDB, dry_run: bool = False) -> dict[str, int]:
    stats = {"sources": 0, "persons": 0, "dojos": 0, "edges": 0}
    if dry_run:
        return {"sources": 3, "persons": 2, "dojos": 1, "edges": 3}

    sources = [
        SourceRecord(
            id=source_id(CURRENT_URL),
            url=CURRENT_URL,
            title="Aikido of San Jose",
            platform="Aikido of San Jose",
            raw_text=(
                "Classes taught by Jack Wada. He is also a 7th degree black belt in Aikido, "
                "and has been granted the shihan title by World Aikido Headquarters."
            ),
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        ),
        SourceRecord(
            id=source_id(INSTRUCTORS_URL),
            url=INSTRUCTORS_URL,
            title="Instructors - Aikido of San Jose",
            platform="Aikido of San Jose",
            raw_text=(
                "Jack Wada Shihan is currently both chief instructor (dojo-cho) and the "
                "supervisor (kan-cho). He started in 1969 under Robert Frager and Robert Nadeau "
                "senseis. Teaching since 1974, Wada-Shihan holds a 7th-degree black belt. He "
                "also has taught Aikido for the Human Performance department at San Jose State "
                "University, UC Santa Cruz, and West Valley Community College. He is a "
                "kinesiologist and healer with his own Kalos Healing Ministry."
            ),
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        ),
        SourceRecord(
            id=source_id(CITY_AIKIDO_URL),
            url=CITY_AIKIDO_URL,
            title="Jack Wada — City Aikido",
            platform="City Aikido",
            raw_text=(
                "Jack Wada began Aikido in 1969. In 1976 Jack was invited by Nadeau Sensei to "
                "be one of the original faculty of Aikido of San Jose. In 1980 he became chief "
                "instructor of that dojo, a role he continues to fill."
            ),
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        ),
    ]
    for source in sources:
        if not gdb.get_source_by_url(source.url):
            gdb.add_source(source)
            stats["sources"] += 1

    gdb.add_node(
        GraphNode(
            id=WADA_ID,
            type=NodeType.PERSON,
            label="Jack Wada",
            canonical_name="Jack Wada",
            metadata={
                "art": "Aikido",
                "rank": "7th dan",
                "title": "Shihan",
                "role": "Chief instructor (dojo-cho) and supervisor (kan-cho)",
                "started_martial_arts": 1968,
                "started_aikido": 1969,
                "started_teaching": 1974,
                "original_faculty_aikido_of_san_jose": 1976,
                "chief_instructor_since": 1980,
                "teachers": ["Robert Nadeau", "Robert Frager"],
                "institutions_taught": [
                    "San Jose State University",
                    "University of California, Santa Cruz",
                    "West Valley Community College",
                ],
                "occupations": ["Aikido instructor", "kinesiologist", "healer"],
                "healing_ministry": "Kalos Healing Ministry",
            },
            source_urls=[CURRENT_URL, INSTRUCTORS_URL, CITY_AIKIDO_URL],
        )
    )
    gdb.add_node(
        GraphNode(
            id=FRAGER_ID,
            type=NodeType.PERSON,
            label="Robert Frager",
            canonical_name="Robert Frager",
            metadata={"relationship_to_jack_wada": "Early Aikido instructor, beginning in 1969"},
            source_urls=[INSTRUCTORS_URL],
        )
    )
    stats["persons"] += 2

    gdb.add_node(
        GraphNode(
            id=DOJO_ID,
            type=NodeType.DOJO,
            label="Aikido of San Jose",
            canonical_name="Aikido of San Jose",
            metadata={
                "website": CURRENT_URL,
                "city": "San Jose",
                "state": "California",
                "country": "United States",
                "lineage": "Nadeau",
                "address": "510 N 3rd Street #10, San Jose, CA 95112",
                "opened": 1976,
                "phone": "+1 408-294-3049",
                "audiences": ["children", "teens", "young adults", "adults", "seniors"],
                "training_goals": [
                    "self-protection",
                    "personal growth",
                    "focus",
                    "relaxation under pressure",
                    "communication",
                    "teamwork",
                ],
                "environment": "Supportive and non-competitive",
            },
            source_urls=[CURRENT_URL, INSTRUCTORS_URL, CITY_AIKIDO_URL],
        )
    )
    stats["dojos"] += 1

    edges = [
        GraphEdge(
            src_id=WADA_ID,
            rel_type=RelationType.HEAD_INSTRUCTOR,
            dst_id=DOJO_ID,
            metadata={
                "roles": ["dojo-cho", "kan-cho"],
                "teaching_since": 1974,
                "original_faculty_since": 1976,
                "chief_instructor_since": 1980,
                "source_urls": [INSTRUCTORS_URL, CITY_AIKIDO_URL],
            },
        ),
        GraphEdge(
            src_id="person:robert-nadeau",
            rel_type=RelationType.TEACHER_STUDENT,
            dst_id=WADA_ID,
            metadata={"student_started": 1969, "source_urls": [INSTRUCTORS_URL, CITY_AIKIDO_URL]},
        ),
        GraphEdge(
            src_id=FRAGER_ID,
            rel_type=RelationType.TEACHER_STUDENT,
            dst_id=WADA_ID,
            metadata={"student_started": 1969, "source_url": INSTRUCTORS_URL},
        ),
    ]
    for edge in edges:
        gdb.add_edge(edge)
        stats["edges"] += 1
    return stats


def merge_snapshot(gdb: GraphDB, snapshot_dir: Path) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = snapshot_dir / "nodes.jsonl"
    edges_path = snapshot_dir / "edges.jsonl"
    sources_path = snapshot_dir / "sources.jsonl"

    node_rows = [json.loads(line) for line in nodes_path.read_text().splitlines()]
    wanted_node_ids = {WADA_ID, FRAGER_ID, DOJO_ID}
    node_rows = [row for row in node_rows if row["id"] not in wanted_node_ids]
    for node_id in (WADA_ID, FRAGER_ID, DOJO_ID):
        node_rows.append(gdb.get_node(node_id).model_dump(mode="json"))

    edge_rows = [json.loads(line) for line in edges_path.read_text().splitlines()]
    edge_keys = {(row["src_id"], row["rel_type"], row["dst_id"]) for row in edge_rows}
    wanted_edges = {
        (WADA_ID, RelationType.HEAD_INSTRUCTOR.value, DOJO_ID),
        ("person:robert-nadeau", RelationType.TEACHER_STUDENT.value, WADA_ID),
        (FRAGER_ID, RelationType.TEACHER_STUDENT.value, WADA_ID),
    }
    for edge in gdb.get_all_edges():
        key = (edge.src_id, edge.rel_type.value, edge.dst_id)
        if key in wanted_edges and key not in edge_keys:
            edge_rows.append(edge.model_dump(mode="json"))

    source_rows = [json.loads(line) for line in sources_path.read_text().splitlines()]
    source_ids = {row["id"] for row in source_rows}
    for url in (CURRENT_URL, INSTRUCTORS_URL, CITY_AIKIDO_URL):
        source = gdb.get_source_by_url(url)
        if source.id not in source_ids:
            source_rows.append(source.model_dump(mode="json"))

    nodes_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in node_rows),
        encoding="utf-8",
    )
    edges_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in edge_rows),
        encoding="utf-8",
    )
    sources_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in source_rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Jack Wada and Aikido of San Jose")
    parser.add_argument("--db", type=Path, default=settings.graph_db_abs_path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--snapshot-dir", type=Path, default=PROJECT_ROOT / "graph_snapshot")
    args = parser.parse_args()

    gdb = GraphDB(args.db)
    try:
        stats = ingest(gdb, args.dry_run)
        if not args.dry_run:
            merge_snapshot(gdb, args.snapshot_dir)
    finally:
        gdb.close()
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
