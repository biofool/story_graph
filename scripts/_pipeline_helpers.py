"""
Pipeline helper functions — importable from tests and other scripts.
Contains the process_page function that extracts entities/claims from a
crawled page and stores them in the graph database.
"""

from __future__ import annotations

from src.crawler.web_crawler import CrawledPage
from src.extractor.entity_extractor import EntityExtractor
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.alias_resolver import (
    person_id,
    group_id,
    place_id,
    event_id,
    work_id,
    resolve_target_id,
    canonical_person,
    get_aliases_for_canonical,
)
from src.storage.graph_db import GraphDB
from src.storage.models import (
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
    SourceRecord,
    ClaimSourceLink,
    SourceClass,
    BiasHint,
)
from src.utils.text_utils import get_domain

# Maps relation type strings from the extractor output to the
# RelationType enum. Used by process_page to add typed edges.
_REL_TYPE_MAP: dict[str, RelationType] = {
    "FOUNDED": RelationType.FOUNDED,
    "MEMBER_OF": RelationType.MEMBER_OF,
    "WORKED_AT": RelationType.WORKED_AT,
    "LIVED_AT": RelationType.LIVED_AT,
    "LOCATED_IN": RelationType.LOCATED_IN,
    "CREATED": RelationType.CREATED,
}


def classify_source(url: str, title: str, text: str) -> tuple[SourceClass, BiasHint]:
    """Heuristically classify a source page."""
    domain = get_domain(url)
    text_lower = text[:5000].lower() if text else ""

    if "blogspot" in domain or "wordpress" in domain:
        source_class = SourceClass.PRIMARY_FIRST_PERSON
    elif "wikipedia" in domain:
        source_class = SourceClass.JOURNALISTIC
    elif "cultnews" in domain or "latimes" in domain:
        source_class = SourceClass.JOURNALISTIC
    elif "youtube" in domain:
        source_class = SourceClass.DOCUMENTARY_PROMOTIONAL
    else:
        source_class = SourceClass.JOURNALISTIC

    critical_words = ["abuse", "cult", "manipulated", "suffered", "harmful"]
    supportive_words = ["beautiful", "loving", "spiritual", "wonderful"]
    nostalgic_words = ["remember", "memories", "those days", "back then"]

    if any(w in text_lower for w in critical_words):
        bias = BiasHint.HOSTILE
    elif any(w in text_lower for w in supportive_words):
        bias = BiasHint.DEFENSIVE
    elif any(w in text_lower for w in nostalgic_words):
        bias = BiasHint.NOSTALGIC
    else:
        bias = BiasHint.NEUTRAL_ISH

    return source_class, bias


def process_page(
    page: CrawledPage,
    extractor: EntityExtractor,
    claim_extractor: ClaimExtractor,
    db: GraphDB,
):
    """Process a single crawled page: extract entities, claims, and store in graph."""
    if page.error or not page.text:
        return

    url = page.url
    source_class, bias_hint = classify_source(url, page.title, page.text)

    # Create Work node + Source record
    wid = work_id(url)
    work_node = GraphNode(
        id=wid,
        type=NodeType.WORK,
        label=page.title or url,
        canonical_name=page.title,
        metadata={
            "url": url,
            "publish_date": page.publish_date,
            "author": page.author,
            "platform": get_domain(url),
            "work_type": "web_page",
        },
        source_urls=[url],
    )
    db.add_node(work_node)

    source_record = SourceRecord(
        id=wid,
        url=url,
        title=page.title,
        author=page.author,
        publish_date=page.publish_date,
        platform=get_domain(url),
        raw_text=page.text[:50000],
        source_class=source_class,
        bias_hint=bias_hint,
    )
    db.add_source(source_record)

    # Extract entities
    entities = extractor.extract(page.text)

    # Process persons
    for person in entities["persons"]:
        pid = person_id(person["name"])
        canonical = canonical_person(person["name"])
        aliases = get_aliases_for_canonical(canonical)
        node = GraphNode(
            id=pid,
            type=NodeType.PERSON,
            label=person["raw_name"] or canonical,
            canonical_name=canonical,
            metadata={
                "aliases": aliases,
                "extraction_source": person.get("source", "unknown"),
            },
            source_urls=[url],
        )
        db.add_node(node)
        db.add_edge(GraphEdge(
            src_id=wid,
            rel_type=RelationType.MENTIONS,
            dst_id=pid,
            metadata={"evidence": url},
        ))

    # Process groups
    for group in entities["groups"]:
        gid = group_id(group["name"])
        node = GraphNode(
            id=gid,
            type=NodeType.GROUP,
            label=group["name"],
            canonical_name=group["name"],
            metadata={},
            source_urls=[url],
        )
        db.add_node(node)
        db.add_edge(GraphEdge(
            src_id=wid,
            rel_type=RelationType.MENTIONS,
            dst_id=gid,
            metadata={"evidence": url},
        ))

    # Process places
    for place in entities["places"]:
        plid = place_id(place["name"])
        node = GraphNode(
            id=plid,
            type=NodeType.PLACE,
            label=place["name"],
            canonical_name=place["name"],
            metadata={},
            source_urls=[url],
        )
        db.add_node(node)
        db.add_edge(GraphEdge(
            src_id=wid,
            rel_type=RelationType.MENTIONS,
            dst_id=plid,
            metadata={"evidence": url},
        ))

    # Process events
    for event in entities["events"]:
        eid = event_id(event["label"])
        node = GraphNode(
            id=eid,
            type=NodeType.EVENT,
            label=event["label"],
            canonical_name=event["label"],
            metadata={
                "event_type": event.get("event_type", "unknown"),
                "start_date": event.get("start_date"),
                "end_date": event.get("end_date"),
                "description": event.get("description", ""),
            },
            source_urls=[url],
        )
        db.add_node(node)
        db.add_edge(GraphEdge(
            src_id=wid,
            rel_type=RelationType.DESCRIBES,
            dst_id=eid,
            metadata={"evidence": url},
        ))

    # Process claims
    claims = claim_extractor.extract_claims(page.text, source_url=url)
    for claim in claims:
        cid = claim["id"]
        node = GraphNode(
            id=cid,
            type=NodeType.CLAIM,
            label=claim["claim_text"][:200],
            canonical_name=None,
            metadata={
                "claim_text": claim["claim_text"],
                "claim_type": claim["claim_type"],
                "stance": claim["stance"],
                "confidence": claim["confidence"],
                "evidence_mode": claim["evidence_mode"],
            },
            source_urls=[url],
        )
        db.add_node(node)
        db.add_edge(GraphEdge(
            src_id=wid,
            rel_type=RelationType.CONTAINS,
            dst_id=cid,
            metadata={"evidence": url},
        ))

        db.add_claim_source_link(ClaimSourceLink(
            claim_id=cid,
            source_id=wid,
        ))

        if claim.get("speaker_id"):
            db.add_node(GraphNode(
                id=claim["speaker_id"],
                type=NodeType.PERSON,
                label=claim["speaker"],
                canonical_name=canonical_person(claim["speaker"]),
                metadata={},
                source_urls=[url],
            ))
            db.add_edge(GraphEdge(
                src_id=cid,
                rel_type=RelationType.ASSERTED_BY,
                dst_id=claim["speaker_id"],
                metadata={"evidence": url},
            ))

        for target in claim.get("targets", []):
            tid = resolve_target_id(target)
            target_type = target.get("type", "person")
            if target_type == "person":
                tnode = GraphNode(
                    id=tid,
                    type=NodeType.PERSON,
                    label=target.get("name", ""),
                    canonical_name=canonical_person(target.get("name", "")),
                    metadata={},
                    source_urls=[url],
                )
            elif target_type == "group":
                tnode = GraphNode(
                    id=tid,
                    type=NodeType.GROUP,
                    label=target.get("name", ""),
                    canonical_name=target.get("name", ""),
                    metadata={},
                    source_urls=[url],
                )
            else:
                tnode = GraphNode(
                    id=tid,
                    type=NodeType.PLACE,
                    label=target.get("name", ""),
                    canonical_name=target.get("name", ""),
                    metadata={},
                    source_urls=[url],
                )
            db.add_node(tnode)
            db.add_edge(GraphEdge(
                src_id=cid,
                rel_type=RelationType.ABOUT,
                dst_id=tid,
                metadata={"evidence": url},
            ))

    # Process typed relations (FOUNDED, MEMBER_OF, WORKED_AT, LIVED_AT,
    # LOCATED_IN). The src/dst nodes were created above; here we only add
    # the typed edge between them.
    for rel in entities.get("relations", []):
        rel_type_str = rel.get("rel_type", "")
        rel_enum = _REL_TYPE_MAP.get(rel_type_str)
        if rel_enum is None:
            continue
        src = rel.get("src", {})
        dst = rel.get("dst", {})
        src_id = resolve_target_id(src)
        dst_id = resolve_target_id(dst)
        db.add_edge(GraphEdge(
            src_id=src_id,
            rel_type=rel_enum,
            dst_id=dst_id,
            metadata={"evidence": url, "trigger": rel_type_str},
        ))
