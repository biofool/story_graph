"""
Pipeline helper functions — importable from tests and other scripts.
Contains the process_page function that extracts entities/claims from a
crawled page and stores them in the graph database.
"""

from __future__ import annotations

import logging

from src.crawler.image_capture import capture_image
from src.crawler.web_crawler import CrawledPage
from src.extractor.alias_resolver import (
    canonical_person,
    event_id,
    get_aliases_for_canonical,
    group_id,
    person_id,
    place_id,
    resolve_target_id,
    work_id,
)
from src.extractor.claim_extractor import ClaimExtractor
from src.extractor.entity_extractor import EntityExtractor
from src.extractor.scope_filter import ScopeFilter
from src.storage.graph_db import GraphDB
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)
from src.utils.text_utils import get_domain

_log = logging.getLogger(__name__)

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
    elif "wikipedia" in domain or "cultnews" in domain or "latimes" in domain:
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
    scope_filter: ScopeFilter | None = None,
):
    """Process a single crawled page: extract entities, claims, and store in graph.

    If ``scope_filter`` is provided and the page is primarily about an
    out-of-scope entity (a namesake not part of the story), extraction is
    skipped entirely — no Work node, no entities, no edges. The page is
    effectively invisible to the graph. See
    :class:`~src.extractor.scope_filter.ScopeFilter`.
    """
    if page.error or not page.text:
        return

    url = page.url

    # Scope filter: skip pages primarily about out-of-scope entities.
    if scope_filter is not None and not scope_filter.is_empty:
        if scope_filter.is_page_out_of_scope(page.title, page.text, url):
            return
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

    capture_page_images(page, wid, db)

    # Extract entities
    entities = extractor.extract(page.text, source_url=url)

    # Process persons
    for person in entities["persons"]:
        pid = person_id(person["name"], url)
        canonical = canonical_person(person["name"], url)
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
                canonical_name=canonical_person(claim["speaker"], url),
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
            tid = resolve_target_id(target, url)
            target_type = target.get("type", "person")
            if target_type == "person":
                tnode = GraphNode(
                    id=tid,
                    type=NodeType.PERSON,
                    label=target.get("name", ""),
                    canonical_name=canonical_person(target.get("name", ""), url),
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


def capture_page_images(page: CrawledPage, work_id_: str, db: GraphDB, max_images: int = 20):
    """Download image candidates found on a page and attach them to its Work node.

    Best-effort: a failed/filtered-out image candidate is skipped, never
    raises. Capped at max_images per page — pages can list dozens of
    thumbnails/icons in their markup and this is meant to capture a page's
    illustrative photos, not scrape every asset it references.
    """
    for candidate in page.images[:max_images]:
        captured = capture_image(candidate.url, alt=candidate.alt)
        if captured is None:
            continue
        image_node = GraphNode(
            id=f"image:{captured.content_hash}",
            type=NodeType.IMAGE,
            label=captured.alt[:100] or captured.original_url[:100],
            metadata={
                "original_url": captured.original_url,
                "content_hash": captured.content_hash,
                "mime": captured.mime,
                "width": captured.width,
                "height": captured.height,
                "alt": captured.alt,
            },
            source_urls=[page.url],
        )
        db.add_node(image_node)
        db.add_edge(GraphEdge(
            src_id=work_id_,
            rel_type=RelationType.DEPICTS,
            dst_id=image_node.id,
            metadata={"evidence": page.url},
        ))


def record_out_of_scope_nodes(db: GraphDB, scope_filter: ScopeFilter):
    """Record out-of-scope entity nodes in the graph with ``out_of_scope=true`` metadata.

    Each out-of-scope entity (from ``config/out_of_scope.json``) is upserted
    as a Person or Event node with ``out_of_scope: true`` in its metadata.
    This makes the namesake visible in the graph viewer as a disambiguation
    marker — "this is a different Richard Moon, not the one the story is
    about" — without creating any edges or triggering extraction from pages
    about it.

    Safe to call on every pipeline run: upsert semantics mean re-running
    is a no-op for already-recorded nodes.
    """
    for entity in scope_filter.entities:
        if entity.entity_type == "event":
            nid = event_id(entity.canonical_name)
            ntype = NodeType.EVENT
            label = entity.canonical_name
        else:
            nid = entity.node_id
            ntype = NodeType.PERSON
            # Display label: title-case the name, keep the parenthetical
            # disambiguator as-is (e.g. "Richard Moon (law professor)").
            label = _display_label(entity.canonical_name)

        node = GraphNode(
            id=nid,
            type=ntype,
            label=label,
            canonical_name=entity.canonical_name,
            metadata={
                "out_of_scope": True,
                "note": entity.note,
                "surface_forms": entity.surface_forms,
            },
            source_urls=[],
        )
        db.add_node(node)
        _log.info(
            "Recorded out-of-scope node: %s (%s)",
            nid,
            entity.canonical_name,
        )


def _display_label(canonical: str) -> str:
    """Human-readable label for a disambiguated canonical name.

    ``"richard moon (law professor)"`` -> ``"Richard Moon (law professor)"``:
    the name is title-cased, the parenthetical disambiguator left as written.
    Mirrors :func:`src.extractor.alias_resolver._display_label` but is kept
    here to avoid importing a private function.
    """
    name, _, qualifier = canonical.partition(" (")
    return f"{name.title()} ({qualifier}" if qualifier else name.title()
