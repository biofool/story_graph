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

# Node types that a claim can legitimately be "about". We inherit MENTIONS
# targets of these types when inferring implicit claim targets from a source
# work (avoids tagging every claim as being about every place mentioned).
_INHERITABLE_TARGET_TYPES = {NodeType.PERSON, NodeType.GROUP}


class ContradictionDetector:
    """Detects contradictions between claims and builds timeline edges."""

    def __init__(self, db: GraphDB):
        self.db = db

    def infer_implicit_targets(self) -> int:
        """Add ABOUT edges to claims that have none, by inheriting the
        person/group targets mentioned by their source work.

        A claim with no explicit ABOUT targets is implicitly about the
        entities its source page describes. This is a heuristic but
        materially improves contradiction recall on real crawled data
        where claim sentences often refer to subjects by pronoun or
        omit them entirely (e.g. "What a mockery the catchphrase 'Just
        Be Kind' is when babies were denied medical treatment...").

        Returns the number of ABOUT edges added.
        """
        added = 0
        claims = self.db.get_nodes_by_type(NodeType.CLAIM)

        for claim in claims:
            existing = self.db.get_edges_from(claim.id)
            has_about = any(e.rel_type == RelationType.ABOUT for e in existing)
            if has_about:
                continue

            # Find the source work that contains this claim
            # (edge: work -[CONTAINS]-> claim, so the work is the src).
            work_ids = [
                e.src_id for e in self.db.get_edges_to(claim.id)
                if e.rel_type == RelationType.CONTAINS
            ]
            if not work_ids:
                continue

            for work_id in work_ids:
                for mention_edge in self.db.get_edges_from(work_id):
                    if mention_edge.rel_type != RelationType.MENTIONS:
                        continue
                    target = self.db.get_node(mention_edge.dst_id)
                    if target is None or target.type not in _INHERITABLE_TARGET_TYPES:
                        continue
                    self.db.add_edge(GraphEdge(
                        src_id=claim.id,
                        rel_type=RelationType.ABOUT,
                        dst_id=target.id,
                        metadata={"inferred": True, "via_work": work_id},
                    ))
                    added += 1

        _log.info(f"Inferred {added} implicit ABOUT edges for targetless claims")
        return added

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
        seen_pairs: set[frozenset[str]] = set()
        for target_id, claim_stances in target_claims.items():
            for i, (cid1, stance1) in enumerate(claim_stances):
                for j, (cid2, stance2) in enumerate(claim_stances):
                    if i >= j:
                        continue
                    if (stance1, stance2) in CONTRADICTORY_STANCE_PAIRS:
                        # Dedup across targets: the same claim pair may share
                        # multiple targets, but we only want one edge.
                        pair_key = frozenset((cid1, cid2))
                        if pair_key in seen_pairs:
                            continue
                        seen_pairs.add(pair_key)
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
