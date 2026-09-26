#!/usr/bin/env python3
"""
Compare a graph-derived Wikipedia article draft against the live article.

Inputs:
  - a draft produced by scripts/32_generate_wikipedia_article.py
  - a live-article markdown file produced by
    scripts/57_fetch_wikipedia_article.py (provenance header required)

The comparison is a deterministic mechanical aid — named-entity, date,
and ordinal overlap between the graph subgraph, the draft, and the live
article text. It does NOT understand paraphrase or semantics; see the
"Limitations" section of the generated report.

Classifications emitted:
  - Candidate additions      — draft/graph facts whose signal tokens are
                               absent from the live article
  - Corroborated statements  — live-article sentences whose signals are
                               also present in the graph corpus
  - Possible contradictions  — explicit CONTRADICTS edges touching the
                               person's claims + a heuristic year-mismatch
                               check (flagged as heuristic, needs review)
  - Sources not yet cited    — graph sources whose domains don't appear
                               among the live article's citation URLs

Non-citable material (kkron:// personal communication, primary_first_person,
comment_thread, documentary_promotional sources) is never used to justify
proposed text — it is reported separately as context.

Outputs are local drafts only — never post to or edit Wikipedia
(prompts/graph_to_wikipedia_update.md).

Usage:
    python scripts/58_compare_wikipedia_draft.py "robert nadeau" \
        --draft docs/wikipedia-drafts/robert-nadeau-article.md \
        --live docs/wikipedia-drafts/robert-nadeau-live-wikipedia.md \
        --report docs/wikipedia-drafts/robert-nadeau-compare-report.md
"""

import argparse
import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Reuse the graph collection + scoring logic from the article generator,
# and the fetch-file header parser from the fetch script.
_wp = _load_module(
    "wp_gen", PROJECT_ROOT / "scripts" / "32_generate_wikipedia_article.py",
)
_wp_fetch = _load_module(
    "wp_fetch", PROJECT_ROOT / "scripts" / "57_fetch_wikipedia_article.py",
)

parse_header = _wp_fetch.parse_header
get_domain = _wp.get_domain

# Source classes that must never back proposed article text
NON_CITABLE_CLASSES = {
    "primary_first_person", "comment_thread", "documentary_promotional",
}

# Edge types rendered as candidate "facts" for the comparison
FACT_EDGE_RELS = {
    "FOUNDED", "MEMBER_OF", "WORKED_AT", "WORKED_FOR", "TEACHER_STUDENT",
    "HEAD_INSTRUCTOR", "DOJO_AFFILIATION", "CO_APPEARANCE", "ALIAS_OF",
    "CREATED", "CO_AUTHORED", "PRODUCED",
}

# Node types whose labels are usable as entity vocabulary
ENTITY_NODE_TYPES = {"Person", "Group", "Dojo", "Event", "Place", "Work",
                     "Podcast"}

# Years, excluding decade references like "1990s" / "1990's"
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b(?![\s\-]?(?:s|'s)\b)")
_ORDINAL_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b", re.IGNORECASE)
# Capitalized multi-word phrases (2-5 words) — cheap proper-noun detector
_CAP_PHRASE_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z'’.\-]+(?:\s+of\s+|\s+the\s+|\s+de\s+|\s+)){1,4}"
    r"[A-Z][A-Za-z'’.\-]+"
)
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s)>\]]+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“'(])")

_STOPWORDS = {
    "the", "a", "an", "in", "on", "at", "for", "to", "from", "by", "with",
    "according", "he", "she", "it", "they", "his", "her", "their", "this",
    "that", "these", "those", "when", "while", "after", "before", "during",
    "later", "beyond", "upon", "as", "but", "and", "or", "if", "so", "one",
    "two", "three", "there", "then", "now", "here", "not", "all", "many",
    "some", "most", "other", "each", "both", "we", "you", "i", "of", "is",
    "was", "were", "are", "be", "been", "had", "has", "have", "would",
    "could", "also", "into", "out", "over", "under", "between", "among",
    "who", "whom", "which", "what", "how", "than", "then", "such", "same",
    "north", "south", "east", "west", "northern", "southern", "early",
    "late", "new", "old", "first", "last", "born", "died", "japanese",
}

# Anchors too generic to count as corroboration on their own — the
# subject's own name and ubiquitous domain terms. A shared signal is
# "strong" only if it is not in this set.
_GENERIC_WEAK = {
    "aikido", "japan", "japanese", "america", "american", "california",
    "northern california", "san francisco", "united states", "dojo",
    "dojos", "sensei", "shihan", "hombu", "hombu dojo", "o-sensei",
    "o sensei", "martial arts", "north america", "europe", "tokyo",
    "seminar", "workshop", "aikikai", "ueshiba",
}

# Article sections whose lines are citations/links, not article
# statements — excluded from corroboration and contradiction analysis
# (their URLs are still extracted for the not-yet-cited check).
_NON_STATEMENT_SECTIONS = {
    "references", "sources", "further reading", "external links",
    "see also", "notes", "footnotes", "bibliography",
}

# Hatnote / boilerplate line prefixes that aren't article statements
_HATNOTE_RE = re.compile(
    r"^(not to be confused|for other uses|for the |this article is|"
    r"main article|see also:? )",
    re.IGNORECASE,
)


# --- Text utilities ----------------------------------------------------------


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def strip_markup(text: str) -> str:
    """Remove wiki/markdown markup, keeping the readable text."""
    text = re.sub(r"<ref[^>]*/>", " ", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", " ", text)
    text = re.sub(r"</?references>", " ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = re.sub(r"''+", "", text)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[\d+\]", " ", text)  # footnote markers [1]
    text = text.replace("**", "").replace("*", "")
    return normalize_ws(text)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences/lines. Heuristic — not perfect on
    abbreviations (e.g. 'U.S.'); noted in report limitations."""
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Table rows: turn cells into a flat statement
        if line.startswith("|"):
            line = line.replace("|", " ")
        line = normalize_ws(line)
        if len(line) < 15:
            continue
        for s in _SENT_SPLIT_RE.split(line):
            s = re.sub(r"^[-*]\s+", "", s.strip())
            if len(s) >= 15:
                out.append(s)
    return out


def article_statements(body: str) -> list[str]:
    """Extract statement-like sentences from the article body.

    Skips section headings, hatnotes, citation-list rows, and every line
    inside non-statement sections (References, External links, Further
    reading, ...). Table rows (infobox facts) are kept.
    """
    section = ""
    out = []
    for line in body.split("\n"):
        m = re.match(r"^#{1,6}\s*(.+?)\s*$", line)
        if m:
            section = m.group(1).strip().lower()
            continue
        if section in _NON_STATEMENT_SECTIONS:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("^"):
            continue
        if _HATNOTE_RE.match(stripped):
            continue
        out.extend(split_sentences(line))
    return out


def extract_cap_phrases(text: str) -> set[str]:
    """Extract capitalized multi-word phrases (cheap proper-noun proxy)."""
    phrases = set()
    for m in _CAP_PHRASE_RE.finditer(text):
        phrase = normalize_ws(m.group(0))
        words = phrase.split()
        # Drop leading stopwords ("In 1962, Nadeau..." → keep "Nadeau ...")
        while words and words[0].lower() in _STOPWORDS:
            words = words[1:]
        while words and words[-1].lower() in _STOPWORDS:
            words = words[:-1]
        phrase = " ".join(words)
        if len(phrase) < 5 or len(words) < 2:
            continue
        if all(w.lower() in _STOPWORDS for w in words):
            continue
        phrases.add(phrase)
    return phrases


def extract_signals(text: str, vocab_re: re.Pattern | None) -> dict:
    """Extract comparison signals from a text unit.

    Returns {"entities": set, "caps": set, "years": set, "ordinals": set}.
    'entities' are graph-vocabulary node labels found in the text;
    'caps' are capitalized multi-word phrases (possible entities the
    graph doesn't know); 'years' are year tokens; 'ordinals' are things
    like "8th".
    """
    entities = set()
    if vocab_re:
        for m in vocab_re.finditer(text):
            entities.add(normalize_ws(m.group(0)))
    return {
        "entities": entities,
        "caps": extract_cap_phrases(text),
        "years": set(_YEAR_RE.findall(text)),
        "ordinals": {o.lower() for o in _ORDINAL_RE.findall(text)},
    }


def signals_present(sig_values: set[str], live_blob: str) -> set[str]:
    """Return the subset of signal strings present (word-boundary,
    case-insensitive) in the normalized live-article blob."""
    found = set()
    for s in sig_values:
        s = s.strip()
        if not s:
            continue
        if re.search(r"\b" + re.escape(s.lower()) + r"\b", live_blob):
            found.add(s)
    return found


def dedupe_signals(signals: list[str]) -> list[str]:
    """Dedupe signal strings case-insensitively, preserving order."""
    seen = set()
    out = []
    for s in signals:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def weak_anchor_set(canonical: dict) -> set[str]:
    """Anchors too weak to corroborate on their own: generic domain terms
    plus the subject's own name and surname (every sentence shares those)."""
    weak = set(_GENERIC_WEAK)
    label = (canonical or {}).get("label", "")
    if label:
        weak.add(label.lower())
        parts = label.split()
        if parts:
            weak.add(parts[-1].lower())
    return weak


def build_entity_vocab(sub: dict) -> re.Pattern | None:
    """Build a combined regex matching any subgraph entity label.

    Vocabulary = labels of non-Claim nodes that are endpoints of edges
    touching the matched nodes, plus CO_APPEARANCE metadata places
    (city/country) — e.g. 'Leningrad', 'Lenkai Aikido Club'.
    """
    nodes = sub["nodes"]
    edges = sub["edges"]
    matches = sub["matches"]
    node_map = {n["id"]: n for n in nodes}
    match_ids = {n["id"] for n in matches}

    vocab_ids = set(match_ids)
    for e in edges:
        if e.get("src_id") in match_ids:
            vocab_ids.add(e.get("dst_id", ""))
        if e.get("dst_id") in match_ids:
            vocab_ids.add(e.get("src_id", ""))

    terms = set()
    for nid in vocab_ids:
        n = node_map.get(nid)
        if not n or n.get("type") not in ENTITY_NODE_TYPES:
            continue
        label = normalize_ws(n.get("label", ""))
        # Skip long/truncated labels and all-stopword labels
        if not (3 <= len(label) <= 60):
            continue
        if all(w.lower() in _STOPWORDS for w in label.split()):
            continue
        terms.add(label)

    # CO_APPEARANCE metadata places (city/country)
    for e in edges:
        if e.get("rel_type") != "CO_APPEARANCE":
            continue
        if e.get("src_id") not in match_ids and e.get("dst_id") not in match_ids:
            continue
        for key in ("city", "country"):
            v = (e.get("metadata") or {}).get(key)
            if v and 3 <= len(v) <= 40:
                terms.add(v)

    if not terms:
        return None
    # Longest first so multi-word labels win over substrings
    alternatives = sorted(terms, key=len, reverse=True)
    return re.compile(
        r"\b(" + "|".join(re.escape(t) for t in alternatives) + r")\b",
        re.IGNORECASE,
    )


# --- Draft / graph fact extraction -------------------------------------------


def draft_fact_lines(draft_text: str) -> list[dict]:
    """Extract candidate fact lines from a generated article draft.

    Skips section headers and the <references> block; records which
    ref names each line cited. Returns [{"text": ..., "refs": [...]}].
    """
    facts = []
    in_refs = False
    for raw in draft_text.split("\n"):
        line = raw.strip()
        if "<references>" in line:
            in_refs = True
        if "</references>" in line:
            in_refs = False
            continue
        if in_refs or not line:
            continue
        if line.startswith("==") or line.startswith("#"):
            continue
        refs = re.findall(r'<ref name="([^"]+)"\s*/?>', line)
        text = strip_markup(line)
        if len(text) < 25:
            continue
        facts.append({"text": text, "refs": refs})
    # Dedupe identical lines
    seen = set()
    unique = []
    for f in facts:
        if f["text"] not in seen:
            seen.add(f["text"])
            unique.append(f)
    return unique


def classify_edge_priority(rel: str, dst_type: str, meta: dict,
                           dst_id: str) -> str:
    """Bucket a candidate-fact edge BEFORE ranking (issue #80 §5).

    'lead'      — DOJO_AFFILIATION edges that are visit/outreach leads.
                  The Varjan guard, enforced in code: a visit is not an
                  affiliation and must never surface as a candidate fact.
    'noncitable'— edges sourced to personal communication (email://,
                  kkron://) — context only, never candidates.
    'routine'   — bulk seminar/calendar CO_APPEARANCE listings.
    'suspect'   — organizational relations pointing at Person nodes
                  (mis-typed graph data; reported as data-quality flags).
    'normal'    — everything else.
    """
    ctx = str(meta.get("context") or "").lower()
    assoc = str(meta.get("association") or "").lower()
    ev_status = str(meta.get("evidence_status") or "").lower()
    src = f"{meta.get('source') or ''} {meta.get('source_url') or ''}".lower()
    if rel == "DOJO_AFFILIATION" and (
        "unverified" in ev_status
        or "frequent_visited" in assoc or "visit" in assoc
        or "visited frequently" in ctx or "outreach" in ctx
        or "lead" in ctx
    ):
        return "lead"
    if src.startswith("email://") or src.startswith("kkron://"):
        return "noncitable"
    if rel == "CO_APPEARANCE" and (
        meta.get("source") == "aikiweb_seminars_db"
        or "calendar" in src
        or src.rstrip("/").endswith("/events")
    ):
        return "routine"
    if (rel in {"MEMBER_OF", "WORKED_AT", "WORKED_FOR", "HEAD_INSTRUCTOR",
                "DOJO_AFFILIATION", "CO_APPEARANCE"}
            and dst_type == "Person"):
        return "suspect"
    return "normal"


def edge_facts(sub: dict) -> list[dict]:
    """Render key graph edges as candidate fact statements.

    Returns [{"text", "kind", "date", "source_url", "priority"}]; the
    priority bucket comes from classify_edge_priority and controls
    whether a fact is ranked, collapsed, or filtered out entirely.
    """
    node_map = {n["id"]: n for n in sub["nodes"]}
    canonical = sub["canonical"]
    cid = canonical["id"]
    person = canonical.get("label", cid)

    rel_templates = {
        "FOUNDED": "founded",
        "MEMBER_OF": "was a member of",
        "WORKED_AT": "worked at",
        "WORKED_FOR": "worked for",
        "TEACHER_STUDENT": "has a teacher/student relationship with",
        "HEAD_INSTRUCTOR": "is head instructor of",
        "DOJO_AFFILIATION": "is affiliated with",
        "CO_APPEARANCE": "made an appearance at",
        "ALIAS_OF": "is also known as",
        "CREATED": "created",
        "CO_AUTHORED": "co-authored",
        "PRODUCED": "produced",
    }

    facts = []
    for e in sub["edges"]:
        rel = e.get("rel_type", "")
        if rel not in FACT_EDGE_RELS:
            continue
        if e.get("src_id") != cid:
            continue
        dst = node_map.get(e.get("dst_id", ""), {})
        dst_label = normalize_ws(dst.get("label", e.get("dst_id", "")))
        if not dst_label:
            continue
        meta = e.get("metadata") or {}
        dst_type = dst.get("type", "")
        priority = classify_edge_priority(rel, dst_type, meta,
                                          e.get("dst_id", ""))
        suspect = priority == "suspect"
        verb = rel_templates.get(rel, rel.lower().replace("_", " "))
        text = f"{person} {verb} {dst_label}"
        extras = []
        date_val = meta.get("date") or meta.get("dates") or ""
        if meta.get("city"):
            extras.append(f"in {meta['city']}")
        if meta.get("country") and meta["country"] != meta.get("city"):
            extras.append(f"({meta['country']})")
        if date_val:
            extras.append(f"on {date_val}" if "-" in str(date_val)
                          else f"dated {date_val}")
        if meta.get("role"):
            extras.append(f"as {meta['role']}")
        if extras:
            text += " " + " ".join(extras)
        if meta.get("context"):
            text += f" — {meta['context']}"
        facts.append({
            "text": text + ".",
            "kind": rel,
            "date": str(date_val),
            "source_url": meta.get("source_url") or "",
            "priority": priority,
            "dst_type": dst_type,
            "edge_id": f"{e.get('src_id')} -[{rel}]-> {e.get('dst_id')}",
        })
    return facts


def claim_is_citable(claim: dict, citable_source_ids: set[str]) -> bool:
    return any(sid in citable_source_ids for sid in claim.get("_source_ids", []))


def build_corpus(sub: dict, draft_facts: list[dict],
                 citable_source_ids: set[str]) -> list[dict]:
    """Build the graph corpus used for corroboration checks.

    Each item: {"kind", "text", "attribution", "citable"}.
    """
    items = []
    source_map = {s["id"]: s for s in sub["sources"] if "id" in s}

    for f in draft_facts:
        items.append({
            "kind": "draft", "text": f["text"],
            "attribution": "generated draft", "citable": True,
        })

    for c in sub["claims"]:
        text = c.get("label", "") or c.get("metadata", {}).get("claim_text", "")
        text = normalize_ws(text)
        if len(text) < 15:
            continue
        sids = c.get("_source_ids", [])
        urls = [source_map[s].get("url", "") for s in sids if s in source_map]
        items.append({
            "kind": "claim",
            "text": text,
            "attribution": urls[0] if urls else "(no linked source)",
            "citable": claim_is_citable(c, citable_source_ids),
            "claim_id": c["id"],
        })

    # Source raw_text sentences — ponytail: capped at 8000 chars/source
    # to bound runtime on long crawls; lift the cap if recall matters
    # more than speed.
    for s in sub["matched_sources"]:
        raw = s.get("raw_text") or ""
        if not raw:
            continue
        url = s.get("url", "")
        citable = s.get("source_class", "") not in NON_CITABLE_CLASSES
        for sent in split_sentences(raw[:8000]):
            items.append({
                "kind": "source text", "text": sent,
                "attribution": url, "citable": citable,
            })
    return items


# --- Live article parsing ------------------------------------------------------


def live_body(markdown_text: str) -> str:
    """Strip the provenance header + title/fetch-note from a fetched file."""
    # Remove the leading <!-- wikipedia-fetch ... --> block, if present
    body = re.sub(r"^<!--.*?-->\s*", "", markdown_text,
                  count=1, flags=re.DOTALL)
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if s.startswith("# ") or s.startswith("*Fetched"):
            continue
        lines.append(ln)
    return "\n".join(lines)


def live_cited_urls(markdown_text: str) -> set[str]:
    """All URLs cited anywhere in the fetched article markdown."""
    urls = {u for _, u in _MD_LINK_RE.findall(markdown_text)}
    urls |= set(_BARE_URL_RE.findall(markdown_text))
    return {u.rstrip("/.,;") for u in urls if u.startswith("http")}


def normalize_live_blob(body: str) -> str:
    """Normalize the live article body into a lowercase match blob."""
    text = _MD_LINK_RE.sub(r"\1", body)
    text = text.replace("**", "").replace("*", "")
    text = re.sub(r"\[\d+\]", " ", text)
    return " " + normalize_ws(text).lower() + " "


# --- Classification ------------------------------------------------------------


def classify_fact(fact_text: str, sig: dict, live_blob: str) -> dict:
    """Classify one fact's signals against the live article blob.

    Returns {"present": [...], "missing": [...]}.
    """
    all_signals = sig["entities"] | sig["caps"] | sig["years"] | sig["ordinals"]
    present = signals_present(all_signals, live_blob)
    return {
        "present": sorted(present),
        "missing": sorted(all_signals - present),
    }


def corroborate(sentence: str, sig: dict, corpus: list[dict],
                corpus_sigs: list[dict], weak: set[str]) -> dict | None:
    """Find the best-matching graph corpus item for a live sentence.

    Score = 3*shared anchors + shared years + shared ordinals, with a
    small bonus for citable items. A sentence is only "corroborated" if
    the match includes at least one STRONG anchor (not the subject's own
    name or a generic domain term) plus a second corroborating signal —
    a bare shared name is never enough.
    """
    anchors = sig["entities"] | sig["caps"]
    if not anchors:
        return None
    best = None
    best_parts = (set(), set(), set())
    for item, isig in zip(corpus, corpus_sigs):
        shared_anchors = anchors & (isig["entities"] | isig["caps"])
        shared_years = sig["years"] & isig["years"]
        shared_ords = sig["ordinals"] & isig["ordinals"]
        if not (shared_anchors or shared_years):
            continue
        score = (3 * len(shared_anchors) + len(shared_years)
                 + len(shared_ords) + (0.5 if item.get("citable") else 0))
        if best is None or score > best[0]:
            best = (score, item)
            best_parts = (shared_anchors, shared_years, shared_ords)
    if best is None:
        return {"verdict": "no graph evidence", "shared": [], "item": None}
    score, item = best
    shared_anchors, shared_years, shared_ords = best_parts
    strong = {a for a in shared_anchors if a.lower() not in weak}
    n_signals = len(shared_anchors) + len(shared_years) + len(shared_ords)
    if strong and n_signals >= 2:
        verdict = "corroborated"
    else:
        verdict = "partially corroborated"
    if item and not item.get("citable", True):
        verdict += " (non-citable material only)"
    return {
        "verdict": verdict,
        "shared": sorted(shared_anchors | shared_years | shared_ords),
        "item": item,
        "score": score,
    }


def find_contradictions(sub: dict) -> list[dict]:
    """Collect CONTRADICTS edges touching the person's claims."""
    claim_ids = {c["id"] for c in sub["claims"]}
    node_map = {n["id"]: n for n in sub["nodes"]}
    out = []
    for e in sub["edges"]:
        if e.get("rel_type") != "CONTRADICTS":
            continue
        if e.get("src_id") not in claim_ids and e.get("dst_id") not in claim_ids:
            continue
        src = node_map.get(e["src_id"], {})
        dst = node_map.get(e["dst_id"], {})
        out.append({
            "src": normalize_ws(src.get("label", e["src_id"]))[:160],
            "dst": normalize_ws(dst.get("label", e["dst_id"]))[:160],
            "reason": (e.get("metadata") or {}).get("reason", ""),
            "src_id": e["src_id"], "dst_id": e["dst_id"],
        })
    return out


def year_mismatches(live_sentences: list[tuple[str, dict]],
                    corpus: list[dict], corpus_sigs: list[dict],
                    weak: set[str], limit: int = 10) -> list[dict]:
    """Heuristic: live sentence has exactly one year Y, and some corpus
    item sharing a STRONG entity anchor with it uses only different
    years. Flagged as a possible discrepancy for human review — NOT
    asserted."""
    out = []
    for sent, sig in live_sentences:
        if len(sig["years"]) != 1:
            continue
        year = next(iter(sig["years"]))
        anchors = sig["entities"] | sig["caps"]
        strong_anchors = {a for a in anchors if a.lower() not in weak}
        if not strong_anchors:
            continue
        for item, isig in zip(corpus, corpus_sigs):
            shared = strong_anchors & (isig["entities"] | isig["caps"])
            if not shared or not isig["years"]:
                continue
            if year not in isig["years"]:
                other_years = sorted(isig["years"])[:4]
                out.append({
                    "live": sent[:200], "live_year": year,
                    "graph": item["text"][:200],
                    "graph_years": other_years,
                    "shared": sorted(shared)[:6],
                    "attribution": item.get("attribution", ""),
                    "citable": item.get("citable", True),
                })
                break  # one example per live sentence is enough
        if len(out) >= limit:
            break
    return out


# --- Report -------------------------------------------------------------------


def fmt_source_line(s: dict) -> str:
    title = normalize_ws(s.get("title", "") or s.get("url", "")[:60])
    url = s.get("url", "")
    return (
        f"- [{title[:70]}]({url}) — SRS={s['_srs']} ({s['_tier']}), "
        f"class={s.get('source_class') or 'unclassified'}"
    )


def generate_compare_report(
    search_term: str,
    sub: dict,
    draft_path: Path,
    live_path: Path,
    live_meta: dict,
    missing_edge: list[dict],
    missing_draft: list[dict],
    suspect_edge: list[dict],
    covered_draft_count: int,
    corroborated: list[dict],
    no_evidence: list[dict],
    contradicts: list[dict],
    contradicted_live: list[dict],
    mismatches: list[dict],
    not_cited_citable: list[dict],
    not_cited_other: list[dict],
    cited_sources: list[dict],
    non_citable_material: dict,
    live_sentence_count: int,
    filtered_facts: dict | None = None,
) -> str:
    label = sub["canonical"].get("label", search_term)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = []
    lines.append(f"# Wikipedia compare report: {label}")
    lines.append("")
    lines.append(
        "Mechanical comparison of the graph-derived draft against the live "
        "Wikipedia article. Generated by "
        "`scripts/58_compare_wikipedia_draft.py` — **local working document "
        "only; never post to or edit Wikipedia from it** "
        "(`prompts/graph_to_wikipedia_update.md`)."
    )
    lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Subject: `{sub['canonical']['id']}` — {label}")
    lines.append(f"- Draft: `{draft_path}` (scripts/32_generate_wikipedia_article.py)")
    lines.append(f"- Live article: `{live_path}`")
    lines.append(
        f"  - title: {live_meta.get('title', '?')} | "
        f"revid: {live_meta.get('revid', '?')} | "
        f"retrieved: {live_meta.get('retrieved', '?')}"
    )
    if live_meta.get("redirected_from"):
        lines.append(f"  - redirected from: {live_meta['redirected_from']}")
    if live_meta.get("oldid_url"):
        lines.append(f"  - permalink: {live_meta['oldid_url']}")
    lines.append(f"- Snapshot: `graph_snapshot/` | compare run: {now}")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    n_full = sum(1 for c in corroborated
                 if c["verdict"].startswith("corroborated"))
    lines.append(
        f"- Candidate additions: **{len(missing_edge) + len(missing_draft)}** "
        f"fact(s) with signal tokens absent from the live article"
    )
    if suspect_edge:
        lines.append(
            f"- Graph data-quality flags: **{len(suspect_edge)}** edge(s) "
            f"with suspect relation/target typing"
        )
    lines.append(
        f"- Draft lines already fully covered by the live article: "
        f"**{covered_draft_count}**"
    )
    lines.append(
        f"- Live statements with graph corroboration: **{n_full}** "
        f"corroborated + **{len(corroborated) - n_full}** partially "
        f"corroborated of {live_sentence_count} analyzed sentences"
    )
    lines.append(
        f"- Explicit CONTRADICTS edges on this subject's claims: "
        f"**{len(contradicts)}**; heuristic date mismatches: "
        f"**{len(mismatches)}**"
    )
    lines.append(
        f"- Citable graph sources not cited in the live article: "
        f"**{len(not_cited_citable)}**"
    )
    lines.append(
        f"- Non-citable graph material held as context only: "
        f"**{non_citable_material['claim_count']}** claim(s), "
        f"**{non_citable_material['source_count']}** source(s)"
    )
    if filtered_facts:
        parts = [f"**{len(v)}** {name}" for name, v in (
            ("affiliation-lead edge(s)", filtered_facts.get("lead", [])),
            ("personal-communication edge(s)",
             filtered_facts.get("noncitable", [])),
            ("routine seminar/calendar edge(s)",
             filtered_facts.get("routine", [])),
        ) if v]
        if parts:
            lines.append(
                "- Filtered before ranking (issue #80 §5): "
                + ", ".join(parts)
                + " — see Filtered facts (diagnostics)"
            )
    lines.append("")

    # --- Candidate additions ---
    lines.append("## Candidate additions (in graph/draft, missing from live article)")
    lines.append("")
    lines.append(
        "A fact is listed when at least one of its signal tokens (graph "
        "entity label, capitalized phrase, year, or ordinal) does not appear "
        "anywhere in the live article. Absence of a token ≠ absence of the "
        "fact — the article may state it in different words. Triage needed."
    )
    lines.append("")

    notable_edge = missing_edge

    if notable_edge:
        lines.append("### From graph edges")
        lines.append("")
        for f in notable_edge:
            fx = f["_fact"]
            lines.append(f"- **{fx['text']}**")
            lines.append(
                f"  - edge `{fx['edge_id']}`; missing signals: "
                f"{', '.join(dedupe_signals(f['missing'])[:8])}"
            )
            if fx.get("source_url"):
                lines.append(f"  - source: {fx['source_url']}")
        lines.append("")

    if missing_draft:
        lines.append("### From the generated draft")
        lines.append("")
        for f in missing_draft[:25]:
            lines.append(f"- {f['_fact']['text'][:220]}")
            lines.append(
                f"  - missing signals: "
                f"{', '.join(dedupe_signals(f['missing'])[:8])}"
            )
        if len(missing_draft) > 25:
            lines.append(f"- … plus {len(missing_draft) - 25} more draft lines")
        lines.append("")

    if not (notable_edge or missing_draft):
        lines.append("- None detected.")
        lines.append("")

    if suspect_edge:
        lines.append(
            f"### Graph data-quality flags ({len(suspect_edge)} edge(s))"
        )
        lines.append("")
        lines.append(
            "These edges use an organizational relation "
            "(MEMBER_OF/WORKED_AT/CO_APPEARANCE/…) pointing at a **Person** "
            "node — almost certainly mis-typed graph data rather than real "
            "facts. Not proposed as additions; flagged for graph cleanup:"
        )
        lines.append("")
        for fx in suspect_edge:
            lines.append(
                f"- `{fx['edge_id']}` — dst is a {fx.get('dst_type', '?')} "
                f"node"
            )
        lines.append("")

    if filtered_facts and any(filtered_facts.values()):
        lines.append("### Filtered facts (diagnostics)")
        lines.append("")
        lines.append(
            "Edges excluded BEFORE candidate ranking — visit/outreach "
            "affiliation leads (Varjan guard) and personal-communication-"
            "sourced edges. Counts are kept visible so an overbroad filter "
            "can be audited:"
        )
        lines.append("")
        labels = {"lead": "Affiliation leads (visit ≠ affiliation)",
                  "noncitable": "Personal-communication-sourced",
                  "routine": "Bulk seminar/calendar listings"}
        for key in ("lead", "noncitable", "routine"):
            bucket = filtered_facts.get(key) or []
            if not bucket:
                continue
            lines.append(f"**{labels[key]}** — {len(bucket)} edge(s):")
            for fx in bucket[:15]:
                lines.append(f"- {fx['text'][:140]}")
            if len(bucket) > 15:
                lines.append(f"- … plus {len(bucket) - 15} more")
            lines.append("")

    # --- Corroborated ---
    lines.append("## Live-article statements corroborated by the graph")
    lines.append("")
    lines.append(
        "A live sentence is 'corroborated' when a graph claim, draft line, "
        "or source-text sentence shares at least one entity/capitalized "
        "phrase plus additional signals (year/ordinal/more entities). "
        "Shared-token overlap is not semantic verification."
    )
    lines.append("")
    if corroborated:
        # Full corroborations first, then partials
        corroborated_sorted = sorted(
            corroborated,
            key=lambda c: (not c["verdict"].startswith("corroborated"),
                           -c.get("score", 0)),
        )
        for c in corroborated_sorted:
            item = c["item"] or {}
            lines.append(f"- {c['sentence'][:220]}")
            lines.append(
                f"  - {c['verdict']} via {item.get('kind', '?')} "
                f"({item.get('attribution', '')[:80]})"
            )
            lines.append(f"  - shared: {', '.join(c['shared'][:8])}")
        lines.append("")

    if no_evidence:
        lines.append(
            f"### Live statements with no graph evidence ({len(no_evidence)})"
        )
        lines.append("")
        lines.append(
            "Signals in these sentences matched nothing in the graph "
            "corpus — either genuinely uncovered by the research or a "
            "tokenization miss:"
        )
        lines.append("")
        for c in no_evidence[:15]:
            lines.append(f"- {c['sentence'][:180]}")
        if len(no_evidence) > 15:
            lines.append(f"- … plus {len(no_evidence) - 15} more")
        lines.append("")

    # --- Contradictions ---
    lines.append("## Possible contradictions / discrepancies")
    lines.append("")
    if contradicts:
        lines.append("### Explicit CONTRADICTS edges in the graph")
        lines.append("")
        for c in contradicts:
            lines.append(f"- `{c['src_id']}` ⇄ `{c['dst_id']}`")
            lines.append(f"  - A: {c['src']}")
            lines.append(f"  - B: {c['dst']}")
            if c["reason"]:
                lines.append(f"  - reason: {c['reason']}")
        lines.append("")
        if contradicted_live:
            lines.append(
                "Live-article sentences sharing signals with the disputed "
                "claims (present with attribution per WP:NPOV — do not "
                "resolve a live dispute in the article's voice):"
            )
            lines.append("")
            for s in contradicted_live:
                lines.append(f"- {s[:200]}")
            lines.append("")
    else:
        lines.append(
            "No `CONTRADICTS` edges touch this subject's claims in the "
            "current snapshot."
        )
        lines.append("")

    if mismatches:
        lines.append("### Heuristic date mismatches (review required)")
        lines.append("")
        lines.append(
            "Each row: a live sentence with a single year, and a graph item "
            "sharing an entity that records only different year(s). This is "
            "a weak signal — different events legitimately have different "
            "dates — but worth an editor's eye."
        )
        lines.append("")
        for m in mismatches:
            lines.append(f"- Live: \"{m['live']}\" ({m['live_year']})")
            lines.append(
                f"  - Graph ({'citable' if m['citable'] else 'non-citable'}): "
                f"\"{m['graph']}\" — year(s) {', '.join(m['graph_years'])}"
            )
            lines.append(
                f"  - shared: {', '.join(m['shared'])} | "
                f"attribution: {m['attribution'][:80]}"
            )
        lines.append("")

    # --- Sources not yet cited ---
    lines.append("## Graph sources not yet cited in the live article")
    lines.append("")
    if not_cited_citable:
        lines.append("### Citable (SRS ≥ 50) — candidates for new citations")
        lines.append("")
        for s in not_cited_citable:
            lines.append(fmt_source_line(s))
        lines.append("")
    if not_cited_other:
        lines.append(
            "### Below citation threshold (SRS < 50) — context only"
        )
        lines.append("")
        for s in not_cited_other:
            lines.append(fmt_source_line(s))
        lines.append("")
    if cited_sources:
        lines.append("### Already cited in the live article")
        lines.append("")
        for s in cited_sources:
            lines.append(fmt_source_line(s))
        lines.append("")

    # --- Non-citable context ---
    lines.append("## Non-citable graph material (context only — NOT proposed)")
    lines.append("")
    lines.append(
        "The following are first-class graph evidence but must not appear "
        "as proposed article text (WP:RS): `kkron://` personal-communication "
        "assertions and `primary_first_person` / `comment_thread` / "
        "`documentary_promotional` sources."
    )
    lines.append("")
    for label_, items_ in non_citable_material["claims_by_reason"]:
        lines.append(f"- {label_} ({len(items_)}):")
        for c in items_[:5]:
            lines.append(f"  - {c[:140]}")
    for s in non_citable_material["sources"]:
        lines.append(
            f"- source: {s.get('url', '')[:80]} "
            f"(class={s.get('source_class') or 'unclassified'})"
        )
    lines.append("")

    # --- Limitations ---
    lines.append("## Limitations — read before acting on this report")
    lines.append("")
    lines.append(
        "- **Token matching, not semantics.** 'Missing' means a signal "
        "token was not found verbatim in the live article; paraphrased "
        "coverage is missed both ways. Every candidate addition needs a "
        "human to check whether the article already says it differently."
    )
    lines.append(
        "- **Corroboration is co-occurrence.** Shared entity + year in two "
        "texts does not prove they assert the same fact."
    )
    lines.append(
        "- **Contradiction detection is narrow.** Only explicit "
        "`CONTRADICTS` edges plus a single-year mismatch heuristic are "
        "checked. Semantic conflicts (nationality, rank, roles) are not "
        "detected unless they share this shape."
    )
    lines.append(
        "- **Draft quality caveat.** The generated draft (script 32) "
        "includes first-person interview-quote claims that are not "
        "encyclopedic facts; 'candidate additions' from draft lines need "
        "editorial triage before any use."
    )
    lines.append(
        "- **Sentence splitting is heuristic** and may mis-split "
        "abbreviations; capitalized-phrase extraction is a cheap proxy for "
        "NER."
    )
    lines.append(
        "- **Non-citable material was excluded** from corroboration "
        "credit and proposed text, but is listed above for transparency."
    )
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Compare a graph-derived Wikipedia draft against the "
                    "live article (deterministic, local-only)."
    )
    parser.add_argument(
        "search_term",
        help="Person name to search for (e.g. 'robert nadeau')",
    )
    parser.add_argument(
        "--draft", type=Path, required=True,
        help="Generated draft (scripts/32_generate_wikipedia_article.py)",
    )
    parser.add_argument(
        "--live", type=Path, required=True,
        help="Fetched live article (scripts/57_fetch_wikipedia_article.py)",
    )
    parser.add_argument(
        "--report", type=Path, default=None,
        help="Write comparison report to this file",
    )
    parser.add_argument(
        "--snapshot-dir", type=Path, default=SNAPSHOT_DIR,
        help=f"Path to graph_snapshot/ dir (default: {SNAPSHOT_DIR})",
    )
    parser.add_argument(
        "--tranco", type=Path, default=None,
        help="Path to Tranco top-1M CSV file",
    )

    args = parser.parse_args()

    if not args.draft.exists():
        print(f"ERROR: draft file not found: {args.draft}", file=sys.stderr)
        sys.exit(1)
    if not args.live.exists():
        print(f"ERROR: live file not found: {args.live}", file=sys.stderr)
        sys.exit(1)

    draft_text = args.draft.read_text(encoding="utf-8")
    live_text = args.live.read_text(encoding="utf-8")

    live_meta = parse_header(live_text)
    if not live_meta:
        print(
            f"WARNING: no provenance header in {args.live} — was it "
            f"fetched with scripts/57_fetch_wikipedia_article.py?",
            file=sys.stderr,
        )

    # Collect the person's subgraph
    tranco = _wp.load_tranco(args.tranco) if args.tranco else {}
    sub = _wp.collect_subgraph(
        args.search_term, args.snapshot_dir, tranco=tranco, rsp_cache={},
    )
    if not sub:
        sys.exit(1)

    citable_source_ids = {
        s["id"] for s in sub["scored_sources"] if s["_srs"] >= 50
    }

    # Build entity vocabulary + normalized live blob
    vocab_re = build_entity_vocab(sub)
    body = live_body(live_text)
    live_blob = normalize_live_blob(body)
    cited_urls = live_cited_urls(live_text)
    cited_domains = {get_domain(u) for u in cited_urls}
    weak = weak_anchor_set(sub["canonical"])

    # Facts: draft lines + graph edges
    dfacts = draft_fact_lines(draft_text)
    efacts = edge_facts(sub)
    suspect_facts = [f for f in efacts if f["priority"] == "suspect"]

    missing_draft, covered_draft = [], []
    for f in dfacts:
        sig = extract_signals(f["text"], vocab_re)
        res = classify_fact(f["text"], sig, live_blob)
        if res["missing"]:
            res["_fact"] = f
            missing_draft.append(res)
        else:
            covered_draft.append(f)

    missing_edge = []
    filtered_facts = {"lead": [], "noncitable": [], "routine": []}
    for f in efacts:
        if f["priority"] == "suspect":
            continue  # reported as data-quality flags, not additions
        if f["priority"] in filtered_facts:
            filtered_facts[f["priority"]].append(f)
            continue  # filtered before ranking — reported in diagnostics
        sig = extract_signals(f["text"], vocab_re)
        res = classify_fact(f["text"], sig, live_blob)
        if res["missing"]:
            res["_fact"] = f
            missing_edge.append(res)
    # Sort: facts with missing dates/entities first
    missing_edge.sort(key=lambda r: -len(dedupe_signals(r["missing"])))
    missing_draft.sort(key=lambda r: -len(dedupe_signals(r["missing"])))

    # Corpus for corroboration
    corpus = build_corpus(sub, dfacts, citable_source_ids)
    corpus_sigs = [extract_signals(it["text"], vocab_re) for it in corpus]

    # Live article statements → corroboration (citation lists, hatnotes,
    # and reference sections excluded)
    corroborated, no_evidence = [], []
    live_sig_pairs = []
    for sent in article_statements(body):
        clean = strip_markup(sent)
        sig = extract_signals(clean, vocab_re)
        live_sig_pairs.append((clean, sig))
        res = corroborate(clean, sig, corpus, corpus_sigs, weak)
        if res is None:
            continue
        res["sentence"] = clean
        if res["verdict"] == "no graph evidence":
            no_evidence.append(res)
        else:
            corroborated.append(res)

    # Contradictions
    contra = find_contradictions(sub)
    # Live sentences sharing signals with disputed claims
    disputed_texts = " ".join(c["src"] + " " + c["dst"] for c in contra)
    disputed_sig = extract_signals(disputed_texts, vocab_re)
    disputed_anchors = disputed_sig["entities"] | disputed_sig["caps"]
    contradicted_live = []
    if disputed_anchors:
        for sent, sig in live_sig_pairs:
            if (sig["entities"] | sig["caps"]) & disputed_anchors:
                contradicted_live.append(sent)

    mismatches = year_mismatches(live_sig_pairs, corpus, corpus_sigs, weak)

    # Sources not yet cited
    not_cited_citable, not_cited_other, cited_sources = [], [], []
    for s in sub["scored_sources"]:
        url = s.get("url", "")
        if "kkron://" in url:
            continue
        if get_domain(url) in cited_domains:
            cited_sources.append(s)
        elif s["_srs"] >= 50:
            not_cited_citable.append(s)
        else:
            not_cited_other.append(s)

    # Non-citable material — context only
    source_map = {s["id"]: s for s in sub["sources"] if "id" in s}
    nc_claims = {"kkron:// personal communication": [],
                 "only non-citable sources": []}
    nc_claim_count = 0
    for c in sub["claims"]:
        sids = c.get("_source_ids", [])
        urls = [source_map[s].get("url", "") for s in sids if s in source_map]
        text = normalize_ws(
            c.get("label", "") or c.get("metadata", {}).get("claim_text", "")
        )
        if any("kkron://" in u for u in urls):
            nc_claims["kkron:// personal communication"].append(text)
            nc_claim_count += 1
        elif sids and not claim_is_citable(c, citable_source_ids):
            nc_claims["only non-citable sources"].append(text)
            nc_claim_count += 1
    nc_sources = [
        s for s in sub["matched_sources"]
        if s.get("source_class") in NON_CITABLE_CLASSES
        or "kkron://" in (s.get("url") or "")
    ]
    non_citable_material = {
        "claims_by_reason": [
            (k, v) for k, v in nc_claims.items() if v
        ],
        "sources": nc_sources,
        "claim_count": nc_claim_count,
        "source_count": len(nc_sources),
    }

    report = generate_compare_report(
        args.search_term, sub, args.draft, args.live, live_meta,
        missing_edge, missing_draft, suspect_facts, len(covered_draft),
        corroborated, no_evidence, contra, contradicted_live, mismatches,
        not_cited_citable, not_cited_other, cited_sources,
        non_citable_material, len(live_sig_pairs), filtered_facts,
    )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"Comparison report written to {args.report}", file=sys.stderr)
    else:
        print(report)

    print(
        f"Summary: {len(missing_edge) + len(missing_draft)} candidate "
        f"additions, {len(corroborated)} corroborated, "
        f"{len(contra)} CONTRADICTS edges, "
        f"{len(not_cited_citable)} uncited citable sources",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
