#!/usr/bin/env python3
"""
Integrate the Peterson interview (Cyprus peace-building trainers) into the graph.

Adds:
- Source record for the Peterson interview
- Cyprus Peace Training Team group node
- Links Richard Moon, Doug Stone, Chris Thorsten to the team
- Edges showing their collaboration and roles
"""

import sys
from pathlib import Path
from datetime import datetime

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
)


def main():
    db_path = Path(__file__).parent.parent / "data" / "graph.db"
    interview_path = Path(__file__).parent.parent / "data" / "interviews" / "20260205_Peterson_Cyprus_Interview.json"

    with GraphDB(db_path) as db:
        # 1. Add source record for the Peterson interview
        print("Adding source record for Peterson interview...")
        source = SourceRecord(
            id="peterson-interview-20260205",
            url=f"file://{interview_path}",
            title="Keith Peterson Interview: Cyprus Fulbright Commission & Conflict Resolution (Feb 5, 2026)",
            author="Keith Peterson",
            publish_date="2026-02-05",
            platform="recorded_interview",
            source_class=SourceClass.PRIMARY_FIRST_PERSON,
        )
        db.add_source(source)
        print(f"  ✓ Source added: {source.id}")

        # 2. Create Cyprus Peace Training Team group node
        print("\nAdding Cyprus Peace Training Team group node...")
        team_node = GraphNode(
            id="group-cyprus-peace-training-team",
            type=NodeType.GROUP,
            label="Cyprus Peace Training Team",
            canonical_name="Cyprus Peace Training Team",
            metadata={
                "group_type": "conflict_resolution_training",
                "focus": "track_two_diplomacy",
                "training_method": "aikido_based_dialogue",
                "primary_architect": "Louise Diamond",
                "period": "1990s-2000s",
                "context": "Fulbright Commission conflict resolution initiative in Cyprus",
            },
            source_urls=[str(interview_path)],
        )
        db.add_node(team_node)
        print(f"  ✓ Group node added: {team_node.id}")

        # 3. Add/update the three trainers
        print("\nAdding/updating trainer nodes...")

        # Richard Moon
        moon_node = GraphNode(
            id="person-richard-moon",
            type=NodeType.PERSON,
            label="Richard Moon",
            canonical_name="Richard Moon",
            metadata={
                "roles": ["aikido_instructor", "conflict_resolution_trainer", "founder_of_peace_training_team"],
                "training_focus": "embodied_presence_dialogue",
                "bio": "Aikido instructor and peace builder who developed somatic/embodied approaches to conflict resolution",
            },
            source_urls=[str(interview_path)],
        )
        db.add_node(moon_node)
        print(f"  ✓ Person added: {moon_node.id}")

        # Doug Stone
        stone_node = GraphNode(
            id="person-doug-stone",
            type=NodeType.PERSON,
            label="Doug Stone",
            canonical_name="Doug Stone",
            metadata={
                "roles": ["conflict_resolution_trainer"],
                "training_with": "Cyprus Fulbright Commission programs",
            },
            source_urls=[str(interview_path)],
        )
        db.add_node(stone_node)
        print(f"  ✓ Person added: {stone_node.id}")

        # Chris Thorsten (note: "Thorsten" is the corrected spelling from the interview)
        thorsten_node = GraphNode(
            id="person-chris-thorsten",
            type=NodeType.PERSON,
            label="Chris Thorsten",
            canonical_name="Chris Thorsten",
            metadata={
                "roles": ["aikido_student", "conflict_resolution_trainer"],
                "bio": "One of the earliest students who worked with Richard Moon; brought aikido principles into corporate and conflict contexts",
                "collaboration": "Co-trainer with Richard Moon and Doug Stone in Cyprus peace training programs",
            },
            source_urls=[str(interview_path)],
        )
        db.add_node(thorsten_node)
        print(f"  ✓ Person added: {thorsten_node.id}")

        # 4. Create edges showing relationships and collaboration
        print("\nAdding collaboration edges...")

        edges = [
            # Moon, Stone, Thorsten all members of the team
            GraphEdge(
                src_id="person-richard-moon",
                rel_type=RelationType.MEMBER_OF,
                dst_id="group-cyprus-peace-training-team",
                metadata={"role": "co-founder", "training_focus": "somatic embodiment and dialogue"},
            ),
            GraphEdge(
                src_id="person-doug-stone",
                rel_type=RelationType.MEMBER_OF,
                dst_id="group-cyprus-peace-training-team",
                metadata={"role": "trainer"},
            ),
            GraphEdge(
                src_id="person-chris-thorsten",
                rel_type=RelationType.MEMBER_OF,
                dst_id="group-cyprus-peace-training-team",
                metadata={"role": "co-trainer", "training_focus": "physical metaphor for dialogue"},
            ),
            # Thorsten learned from Moon
            GraphEdge(
                src_id="person-chris-thorsten",
                rel_type=RelationType.MENTIONS,
                dst_id="person-richard-moon",
                metadata={"relationship": "early student who worked with", "context": "aikido and conflict resolution"},
            ),
        ]

        for edge in edges:
            db.add_edge(edge)
            print(f"  ✓ Edge added: {edge.src_id} -{edge.rel_type}-> {edge.dst_id}")

        print("\n✅ Integration complete!")
        print(f"\nSummary:")
        print(f"  - Peterson interview source registered")
        print(f"  - Cyprus Peace Training Team group created")
        print(f"  - 3 trainers linked: Richard Moon, Doug Stone, Chris Thorsten")
        print(f"  - Collaboration edges established")


if __name__ == "__main__":
    main()
