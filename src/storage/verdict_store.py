"""
Reviewer verdict overlay store.

The verdict overlay is a human-judgment layer that sits *on top of* the
machine-extracted property graph. It is deliberately kept separate from
``graph_snapshot/{nodes,edges,sources,claim_sources}.jsonl`` so that
re-running the crawl/extraction pipeline (which rewrites those four files
from scratch) never clobbers a reviewer's verdicts. Verdicts persist across
graph re-runs and are version-controlled in their own file:
``graph_snapshot/verdicts.jsonl``.

Format mirrors the other snapshot files: one JSON object per line, sorted
deterministically (by ``claim_id`` then ``reviewer`` then ``id``) so an MR
diff only ever shows verdicts that actually changed. Each line is the JSON
shape of :class:`src.storage.models.Verdict` via
``.model_dump(mode="json")``.

This module is the only place that knows how to read/write the verdict
overlay; the Flask investigation API (and any other consumer) goes through
it, the same way all other code goes through ``json_export`` for the graph.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.storage.models import Verdict, VerdictValue

VERDICTS_FILENAME = "verdicts.jsonl"


def _write_jsonl(path: Path, rows: list[Verdict]) -> None:
    """Write one Verdict per line, sorted by (claim_id, reviewer, id) with
    sorted object keys — same determinism convention as json_export._write_jsonl."""
    ordered = sorted(rows, key=lambda v: (v.claim_id, v.reviewer, v.id))
    with open(path, "w", encoding="utf-8") as f:
        for row in ordered:
            f.write(json.dumps(row.model_dump(mode="json"), sort_keys=True))
            f.write("\n")


def _read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                # A corrupt line should not break the whole overlay; the
                # deterministic sort makes manual recovery easy.
                continue


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string with seconds precision and no
    microsecond noise, so timestamps are stable and diff-friendly."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def gen_verdict_id(claim_id: str, reviewer: str, created_at: str) -> str:
    """Deterministic-ish id for a verdict: ``verdict:<sha8>`` of
    (claim_id, reviewer, created_at). Collisions are harmless because upsert
    is keyed on (claim_id, reviewer), not on id."""
    h = hashlib.sha256(f"{claim_id}|{reviewer}|{created_at}".encode()).hexdigest()[:16]
    return f"verdict:{h}"


def verdicts_file(snapshot_dir: str | Path) -> Path:
    return Path(snapshot_dir) / VERDICTS_FILENAME


def load_verdicts(snapshot_dir: str | Path) -> list[Verdict]:
    """Read all verdicts from ``graph_snapshot/verdicts.jsonl``.

    Returns an empty list if the file does not exist yet (e.g. first run,
    before any verdict has been saved). Rows that fail pydantic validation
    are skipped with no error — a corrupt line should not break the whole
    overlay, and the deterministic sort makes manual recovery easy.
    """
    verdicts: list[Verdict] = []
    for row in _read_jsonl(verdicts_file(snapshot_dir)):
        try:
            verdicts.append(Verdict(**row))
        except Exception:
            continue
    return verdicts


def get_verdict(
    snapshot_dir: str | Path, claim_id: str, reviewer: str
) -> Verdict | None:
    """Return the verdict for (claim_id, reviewer), or None if absent."""
    for v in load_verdicts(snapshot_dir):
        if v.claim_id == claim_id and v.reviewer == reviewer:
            return v
    return None


def get_verdicts_for_claim(snapshot_dir: str | Path, claim_id: str) -> list[Verdict]:
    """All verdicts on a claim, across reviewers (for the multi-reviewer
    future; currently one reviewer, so 0 or 1)."""
    return [v for v in load_verdicts(snapshot_dir) if v.claim_id == claim_id]


def save_verdict(
    snapshot_dir: str | Path,
    *,
    claim_id: str,
    verdict: VerdictValue | str,
    reviewer: str = "reviewer",
    confidence: float = 0.5,
    reasoning: str = "",
    evidence_urls: list[str] | None = None,
    corroborating_claim_ids: list[str] | None = None,
    contradicting_claim_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> Verdict:
    """Upsert a verdict for (claim_id, reviewer).

    If a verdict already exists for this claim+reviewer, it is updated in
    place (``created_at`` preserved, ``updated_at`` bumped, all other fields
    replaced with the new values). Otherwise a new verdict is created.

    Returns the saved :class:`Verdict`. Does NOT write to disk — call
    :func:`export_verdicts` afterwards to persist, mirroring how the graph
    pipeline accumulates changes in SQLite and only writes the snapshot on
    :func:`json_export.export_to_json`.
    """
    verdict_value = VerdictValue(verdict) if isinstance(verdict, str) else verdict
    now = _now_iso()

    existing = get_verdict(snapshot_dir, claim_id, reviewer)
    all_verdicts = load_verdicts(snapshot_dir)

    if existing is not None:
        updated = existing.model_copy(update={
            "verdict": verdict_value,
            "confidence": confidence,
            "reasoning": reasoning,
            "evidence_urls": evidence_urls or [],
            "corroborating_claim_ids": corroborating_claim_ids or [],
            "contradicting_claim_ids": contradicting_claim_ids or [],
            "tags": tags or [],
            "updated_at": now,
        })
        all_verdicts = [updated if v.id == existing.id else v for v in all_verdicts]
        result = updated
    else:
        new = Verdict(
            id=gen_verdict_id(claim_id, reviewer, now),
            claim_id=claim_id,
            verdict=verdict_value,
            confidence=confidence,
            reasoning=reasoning,
            evidence_urls=evidence_urls or [],
            corroborating_claim_ids=corroborating_claim_ids or [],
            contradicting_claim_ids=contradicting_claim_ids or [],
            reviewer=reviewer,
            created_at=now,
            updated_at=now,
            tags=tags or [],
        )
        all_verdicts.append(new)
        result = new

    export_verdicts(snapshot_dir, all_verdicts)
    return result


def export_verdicts(
    snapshot_dir: str | Path, verdicts: list[Verdict] | None = None
) -> int:
    """Write the verdict overlay to ``graph_snapshot/verdicts.jsonl``.

    If ``verdicts`` is None, the currently-loaded verdicts are re-exported
    (useful for re-sorting after manual edits). Returns the number of rows
    written. The directory is created if needed.
    """
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    if verdicts is None:
        verdicts = load_verdicts(snapshot_dir)
    _write_jsonl(verdicts_file(snapshot_dir), verdicts)
    return len(verdicts)


def delete_verdict(
    snapshot_dir: str | Path, claim_id: str, reviewer: str
) -> bool:
    """Remove the verdict for (claim_id, reviewer). Returns True if a
    verdict was removed, False if none existed. Persists immediately."""
    all_verdicts = load_verdicts(snapshot_dir)
    before = len(all_verdicts)
    remaining = [
        v for v in all_verdicts
        if not (v.claim_id == claim_id and v.reviewer == reviewer)
    ]
    if len(remaining) == before:
        return False
    export_verdicts(snapshot_dir, remaining)
    return True
