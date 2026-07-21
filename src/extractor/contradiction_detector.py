"""
Contradiction detection: finds claims with opposite stances targeting the same entity.
Also builds timeline edges (PRECEDES) from event dates.
"""

from __future__ import annotations

import logging
from typing import Optional
from collections import defaultdict

from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
)

_log = logging.getLogger(__name__)

# Stance pairs that are considered contradictory
CONTRADICTORY_STANCE_PAIRS = {
    ("critical", "supportive"),
    ("critical", "self-mythologizing"),
    ("supportive", "critical"),
    ("self-mythologizing", "critical"),
}


class ContradictionDetector:
    """Detects contradictions between claims and builds timeline edges."""

    def __init__(self, db: GraphDB):
        self.db = db

    def detect_contradictions(self) -> list[tuple[str, str]]:
        """Find claims with opposite stances targeting the same node.
        Adds CONTRADICTS edges and returns list of (claim_id_1, claim_id_2) pairs.
        """
        contradictions = []

        # Get all claim nodes
        claims = self.db.get_nodes_by_type(NodeType.CLAIM)
        _log.info(f"Checking {len(claims)} claims for contradictions")

        # Build map: target_node_id -> list of (claim_id, stance)
        target_claims: dict[str, list[tuple[str, str]]] = defaultdict(list)

        for claim in claims:
            edges = self.db.get_edges_from(claim.id)
            stance = claim.metadata.get("stance", "neutral")
            for edge in edges:
                if edge.rel_type == RelationType.ABOUT:
                    target_claims[edge.dst_id].append((claim.id, stance))

        # Check for contradictions within each target
        for target_id, claim_stances in target_claims.items():
            for i, (cid1, stance1) in enumerate(claim_stances):
                for j, (cid2, stance2) in enumerate(claim_stances):
                    if i >= j:
                        continue
                    if (stance1, stance2) in CONTRADICTORY_STANCE_PAIRS:
                        # Add CONTRADICTS edge
                        self.db.add_edge(GraphEdge(
                            src_id=cid1,
                            rel_type=RelationType.CONTRADICTS,
                            dst_id=cid2,
                            metadata={"reason": f"opposite stances: {stance1} vs {stance2}"},
                        ))
                        contradictions.append((cid1, cid2))
                        _log.info(f"Contradiction: {cid1} ({stance1}) vs {cid2} ({stance2})")

        _log.info(f"Found {len(contradictions)} contradictions")
        return contradictions

    def build_timeline_edges(self) -> list[tuple[str, str]]:
        """Build PRECEDES edges between events based on dates.
        Returns list of (event_id_1, event_id_2) pairs where event1 precedes event2.
        """
        events = self.db.get_nodes_by_type(NodeType.EVENT)
        timeline = []

        # Extract dates from event metadata
        dated_events = []
        for event in events:
            start_date = event.metadata.get("start_date")
            if start_date:
                dated_events.append((start_date, event.id))

        # Sort by date
        dated_events.sort(key=lambda x: x[0])

        # Add PRECEDES edges
        for i, (date1, eid1) in enumerate(dated_events):
            for date2, eid2 in dated_events[i + 1:]:
                if date1 < date2:
                    self.db.add_edge(GraphEdge(
                        src_id=eid1,
                        rel_type=RelationType.PRECEDES,
                        dst_id=eid2,
                        metadata={"date1": date1, "date2": date2},
                    ))
                    timeline.append((eid1, eid2))
                else:
                    break  # Sorted, so no later events will have earlier dates

        _log.info(f"Built {len(timeline)} timeline edges")
        return timeline
