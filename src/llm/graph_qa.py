"""Natural-language Q&A over the SQLite graph, backed by Gemini.

Retrieval-augmented: pulls relevant nodes, claims, and sources from the
graph by keyword-matching the question, then asks Gemini to synthesize
an answer that cites the stored claims and their stances.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from src.llm.gemini_client import GeminiClient, GeminiError
from src.storage.graph_db import GraphDB
from src.storage.models import NodeType, RelationType

_log = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION = (
    "You answer questions about The Source Family / Father Yod property "
    "graph. You are given retrieved entities, claims, and sources as JSON "
    "context. Answer using ONLY the provided context. When claims "
    "conflict, present each side and attribute it to its source. Quote "
    "claim text verbatim when it directly answers the question. If the "
    "context is insufficient, say so explicitly. Do not fabricate sources."
)


@dataclass
class QAResponse:
    """Answer to a graph question with provenance."""

    answer: str
    context: dict
    """The retrieved subgraph that was fed to the model."""


class GraphQA:
    """Answers natural-language questions over the graph via Gemini."""

    def __init__(self, db: GraphDB, client: GeminiClient | None = None):
        self._db = db
        self._client = client or GeminiClient()

    def answer(self, question: str, *, max_nodes: int = 25, max_claims: int = 15) -> QAResponse:
        """Answer a question by retrieving graph context and asking Gemini."""
        context = self._retrieve(question, max_nodes=max_nodes, max_claims=max_claims)

        if not self._client.is_available():
            return QAResponse(
                answer="Gemini is not configured (GEMINI_API_KEY unset); "
                       "cannot answer. Retrieved context is attached.",
                context=context,
            )

        prompt = (
            f"QUESTION:\n{question}\n\n"
            f"RETRIEVED GRAPH CONTEXT (JSON):\n{json.dumps(context, indent=2)}\n\n"
            "Answer the question using only the context above."
        )
        try:
            text = self._client.generate_text(
                prompt, system_instruction=_SYSTEM_INSTRUCTION
            )
        except GeminiError as e:
            _log.error("Graph Q&A failed: %s", e)
            text = f"(Gemini call failed: {e})"

        return QAResponse(answer=text, context=context)

    # --- retrieval ---

    def _retrieve(self, question: str, *, max_nodes: int, max_claims: int) -> dict:
        """Keyword-match the question against node labels/claim text."""
        # Strip punctuation so "Baker?" -> "baker" matches claim text.
        terms = [
            re.sub(r"[^\w]", "", t).lower()
            for t in question.split()
        ]
        terms = [t for t in terms if len(t) > 2]
        if not terms:
            terms = [re.sub(r"[^\w]", "", question).lower()]

        # Persons / groups / places whose label matches any term.
        matched_nodes = []
        for nt in (NodeType.PERSON, NodeType.GROUP, NodeType.PLACE):
            for node in self._db.get_nodes_by_type(nt):
                label = (node.label or "").lower()
                canonical = (node.canonical_name or "").lower()
                if any(term in label or term in canonical for term in terms):
                    matched_nodes.append({
                        "id": node.id,
                        "type": node.type.value,
                        "label": node.label,
                        "canonical_name": node.canonical_name,
                        "source_urls": node.source_urls,
                    })
        matched_nodes = matched_nodes[:max_nodes]
        matched_ids = {n["id"] for n in matched_nodes}

        # Claims: those ABOUT a matched node, plus any whose text matches.
        claims_out = []
        seen_claim_ids: set[str] = set()
        for claim in self._db.get_nodes_by_type(NodeType.CLAIM):
            text = claim.metadata.get("claim_text", "") or claim.label
            text_lower = text.lower()
            matched = any(term in text_lower for term in terms)
            if not matched:
                # Include if this claim is ABOUT one of the matched nodes.
                for e in self._db.get_edges_from(claim.id):
                    if e.rel_type == RelationType.ABOUT and e.dst_id in matched_ids:
                        matched = True
                        break
            if matched and claim.id not in seen_claim_ids:
                seen_claim_ids.add(claim.id)
                # Resolve ABOUT targets and the asserting speaker.
                about_ids, speaker_id = [], None
                for e in self._db.get_edges_from(claim.id):
                    if e.rel_type == RelationType.ABOUT:
                        about_ids.append(e.dst_id)
                    elif e.rel_type == RelationType.ASSERTED_BY:
                        speaker_id = e.dst_id
                # Resolve source works (CONTAINS edges point work -> claim).
                source_ids = [
                    e.src_id for e in self._db.get_edges_to(claim.id)
                    if e.rel_type == RelationType.CONTAINS
                ]
                claims_out.append({
                    "id": claim.id,
                    "text": text,
                    "stance": claim.metadata.get("stance", "neutral"),
                    "claim_type": claim.metadata.get("claim_type", ""),
                    "evidence_mode": claim.metadata.get("evidence_mode", ""),
                    "about": about_ids,
                    "speaker": speaker_id,
                    "sources": source_ids,
                })
        claims_out = claims_out[:max_claims]

        # Sources referenced by the retrieved claims.
        source_ids = {sid for c in claims_out for sid in c["sources"]}
        sources_out = []
        for sid in source_ids:
            src = self._db.get_source(sid)
            if src is None:
                continue
            sources_out.append({
                "id": src.id,
                "url": src.url,
                "title": src.title,
                "platform": src.platform,
                "source_class": src.source_class.value if src.source_class else None,
                "bias_hint": src.bias_hint.value if src.bias_hint else None,
            })

        return {
            "question": question,
            "matched_nodes": matched_nodes,
            "claims": claims_out,
            "sources": sources_out,
        }
