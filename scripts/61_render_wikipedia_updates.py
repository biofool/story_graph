#!/usr/bin/env python3
"""Render Wikipedia update docs from update-item stores (issue #80).

The per-subject store in ``data/wikipedia-updates/<slug>.json`` is the
decision record; the three Markdown files it produces (status index,
wikimarkup proposal, talk-page proposal) are views — generated, never
hand-edited. Validation fails closed: a bad store produces no docs.

One validated IR per subject feeds all three views, so "one citable-sort
table" and "consistent action-item lists across files" are guaranteed by
construction rather than by hand-syncing prose.

Freshness (--live <file>): compares each proposal's base_revid and
anchor passage against a cached live-article fetch (script 57 format).
Signals: needs_review (revid drift), rebase_needed (anchor passage gone),
passage_intact, possible_already_present (claim signal tokens in the live
text — never auto-accepted; that needs a recorded diff + reviewer).

Usage:
    python scripts/61_render_wikipedia_updates.py hiroshi-ikeda
    python scripts/61_render_wikipedia_updates.py --all --out-dir docs/wikipedia-drafts/rendered
    python scripts/61_render_wikipedia_updates.py hiroshi-ikeda --validate-only
"""

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORE_DIR = PROJECT_ROOT / "data" / "wikipedia-updates"
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
OUT_DIR = PROJECT_ROOT / "docs" / "wikipedia-drafts" / "rendered"

ITEM_TYPES = {"addition", "repair", "question", "excluded"}
DECISIONS = {"citable", "citable-attributed", "citation-pending", "not-citable"}
STATUSES = {"proposed", "posted", "accepted", "rejected", "superseded"}
TRANSITIONS = {
    "proposed": {"posted", "rejected", "superseded"},
    "posted": {"accepted", "rejected", "superseded"},
    "accepted": {"superseded"},
    "rejected": {"proposed"},
    "superseded": set(),
}
RELIABILITY = {"reliable", "marginal", "unreliable", "unscored"}
INDEPENDENCE = {"primary-org", "secondary", "self-report"}
COVERAGE = {"significant", "incidental", "mention"}
SUPPORTS = {"full", "partial"}

CITABLE_DECISIONS = {"citable", "citable-attributed", "citation-pending"}
# Decisions that qualify an item for the paste-ready patch. Latent
# "citation-pending" items are held out (issue #81 §2).
PATCH_DECISIONS = {"citable", "citable-attributed"}
# Reliability floor for patch items without an explicit override.
FLOOR_RELIABILITY = {"reliable", "marginal"}

_SENT_START_RE = re.compile(
    r"^(in|on|at|the|a|an|by|from|after|before|during|he|she|it|they)\s+",
    re.I)
_MONTH_WORDS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
_REF_URL_RE = re.compile(r"https?://[^\s\]|}<>]+")

_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20[0-2]\d)\b")
_CAP_RE = re.compile(r"\b[A-Z][A-Za-z'’.\-]+(?:\s+[A-Z][A-Za-z'’.\-]+)+\b")
_REVID_RE = re.compile(r"^revid:\s*(\d+)", re.M)


class ValidationError(Exception):
    """Store failed validation; renders fail closed."""


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_graph_ids() -> set[str]:
    ids = set()
    for name in ("sources.jsonl", "nodes.jsonl"):
        p = SNAPSHOT_DIR / name
        if not p.exists():
            continue
        for line in p.open():
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return ids


def load_source_meta() -> dict:
    meta = {}
    p = SNAPSHOT_DIR / "sources.jsonl"
    if p.exists():
        for line in p.open():
            try:
                s = json.loads(line)
            except json.JSONDecodeError:
                continue
            meta[s.get("id", "")] = s
    return meta


def _evidence_urls(store: dict, src_meta: dict) -> set[str]:
    """URLs carried by evidence on items with a patch-eligible decision."""
    urls = set()
    for it in store.get("items") or []:
        if it.get("decision") not in PATCH_DECISIONS:
            continue
        for ev in it.get("evidence") or []:
            if "source" in ev:
                u = (src_meta.get(ev["source"]) or {}).get("url")
                if u:
                    urls.add(u.rstrip("/"))
            elif "external" in ev:
                urls.add(ev["external"]["url"].rstrip("/"))
    return urls


def _draft_gate_errors(store: dict, src_meta: dict) -> list[str]:
    """Every <ref> URL in an AfC draft must resolve to evidence on a
    patch-eligible item — otherwise draft text bypasses the item gates
    (issue #81 §4).
    """
    rel = store["article"]["draft_wikitext_file"]
    p = PROJECT_ROOT / rel
    if not p.exists():
        return [f"draft_wikitext_file not found: {rel}"]
    urls = _REF_URL_RE.findall(p.read_text())
    allowed = _evidence_urls(store, src_meta)
    errors = []
    for u in sorted(set(urls)):
        u = u.rstrip("/")
        ok = u in allowed
        if not ok:
            # archive.org wrappers: check the wrapped target URL too
            inner = re.search(r"/(https?://.+)$", u)
            if inner and inner.group(1).rstrip("/") in allowed:
                ok = True
        if not ok:
            errors.append(
                f"draft cites {u} — no citable/citable-attributed item "
                "carries it as evidence")
    return errors


def validate(store: dict, graph_ids: set[str],
             src_meta: dict | None = None) -> tuple[list, list]:
    """Return (errors, warnings). Empty errors means the store is renderable."""
    errors, warnings = [], []
    if not store.get("subject"):
        errors.append("missing 'subject'")
    if not isinstance(store.get("article"), dict):
        errors.append("missing 'article' object")
    items = store.get("items")
    if not isinstance(items, list):
        errors.append("missing 'items' list")
        return errors, warnings

    seen = set()
    live_exists = bool(store.get("article", {}).get("exists"))
    has_draft = bool(store.get("article", {}).get("draft_wikitext_file"))
    for i, it in enumerate(items):
        tag = it.get("id") or f"item[{i}]"
        for field in ("id", "type", "claim", "decision", "status", "history"):
            if field not in it:
                errors.append(f"{tag}: missing '{field}'")
        if tag in seen:
            errors.append(f"{tag}: duplicate id")
        seen.add(tag)
        if it.get("type") not in ITEM_TYPES:
            errors.append(f"{tag}: bad type {it.get('type')!r}")
        if it.get("decision") not in DECISIONS:
            errors.append(f"{tag}: bad decision {it.get('decision')!r}")
        if it.get("status") not in STATUSES:
            errors.append(f"{tag}: bad status {it.get('status')!r}")

        # lifecycle: history append-only, legal transitions, agrees w/ status
        hist = it.get("history") or []
        if hist and hist[0].get("status") != "proposed":
            errors.append(f"{tag}: history must start at 'proposed'")
        prev = None
        for h in hist:
            st = h.get("status")
            if st not in STATUSES:
                errors.append(f"{tag}: history entry bad status {st!r}")
            elif (prev is not None and st != prev
                  and st not in TRANSITIONS[prev]):
                errors.append(
                    f"{tag}: illegal transition {prev} -> {st} in history")
            if st == "accepted" and not (
                    (h.get("diff") or h.get("revid"))
                    and h.get("reviewer")):
                errors.append(
                    f"{tag}: 'accepted' entry needs a recorded diff/revid "
                    "and a reviewer")
            prev = st
        if hist and hist[-1].get("status") != it.get("status"):
            errors.append(f"{tag}: status != last history entry")
        if not hist:
            errors.append(f"{tag}: empty history")

        # evidence entries resolve
        for j, ev in enumerate(it.get("evidence") or []):
            has_src = "source" in ev
            has_ext = "external" in ev
            if has_src == has_ext:
                errors.append(
                    f"{tag}: evidence[{j}] needs exactly one of "
                    "'source' or 'external'")
                continue
            if has_src and ev["source"] not in graph_ids:
                errors.append(
                    f"{tag}: evidence[{j}] source {ev['source']!r} "
                    "not found in graph")
            if has_ext:
                ext = ev["external"] or {}
                if not ext.get("url") or not ext.get("title"):
                    errors.append(f"{tag}: evidence[{j}] external needs url+title")
                warnings.append(
                    f"{tag}: evidence[{j}] external {ext.get('url','')[:60]} "
                    "not in graph")
            for k, allowed in (("reliability", RELIABILITY),
                               ("independence", INDEPENDENCE),
                               ("coverage_depth", COVERAGE),
                               ("supports", SUPPORTS)):
                if k in ev and ev[k] not in allowed:
                    errors.append(
                        f"{tag}: evidence[{j}] bad {k} {ev[k]!r}")

        # the not-citable gate: nothing weak may carry paste-ready wording
        proposal = it.get("proposal") or {}
        if (it.get("decision") == "not-citable"
                or it.get("type") == "excluded"):
            if proposal.get("wikitext"):
                errors.append(
                    f"{tag}: {it.get('decision')}/{it.get('type')} item "
                    "must not carry proposal.wikitext")

        # evidence floor (#81 §2): an item eligible for the paste-ready
        # patch needs at least one reliable|marginal piece of evidence,
        # unless an explicit override states why (e.g. mechanical repair).
        patch_eligible = (it.get("type") in {"addition", "repair"}
                          and it.get("decision") in PATCH_DECISIONS
                          and it.get("status") in {"proposed", "posted"})
        evs = it.get("evidence") or []
        if patch_eligible and not it.get("override"):
            if not any(e.get("reliability") in FLOOR_RELIABILITY
                       for e in evs):
                errors.append(
                    f"{tag}: patch item has no reliable|marginal evidence "
                    "and no override")
        # 'citable' (wiki-voice) needs at least one graph-resolved source;
        # outside-only support can at most be 'citable-attributed' (#81 §2)
        if (it.get("decision") == "citable" and evs
                and not it.get("override")
                and not any("source" in e for e in evs)):
            errors.append(
                f"{tag}: 'citable' needs ≥1 graph-resolved evidence "
                "(or 'citable-attributed'/override)")

        # citable additions/repairs that patch a live article need an
        # anchored, revid-stamped proposal. AfC/draft-mode subjects carry
        # the proposed article as article.draft_wikitext_file — the draft
        # IS the proposal, so per-item wikitext is not required.
        patching_live = live_exists and not has_draft
        if (patch_eligible and patching_live):
            if not proposal.get("wikitext"):
                errors.append(f"{tag}: citable item missing proposal.wikitext")
            if not proposal.get("base_revid"):
                errors.append(f"{tag}: citable item missing base_revid")
        if it.get("type") == "repair" and proposal:
            anchor = proposal.get("anchor") or {}
            if not anchor.get("passage"):
                errors.append(f"{tag}: repair missing anchor.passage")
        # optional recorded hash of the reviewed base passage
        if proposal.get("base_passage_hash"):
            passage = (proposal.get("anchor") or {}).get("passage", "")
            digest = "sha1:" + hashlib.sha1(
                " ".join(passage.split()).encode()).hexdigest()
            if proposal["base_passage_hash"] != digest:
                errors.append(
                    f"{tag}: base_passage_hash does not match "
                    "anchor.passage")

    if has_draft:
        errors.extend(_draft_gate_errors(store, src_meta or {}))
    return errors, warnings


def load_live(cache_file: str) -> dict:
    """Parse a script-57 fetch file: returns {revid, text, wikitext}.

    ``text`` is the rendered markdown; ``wikitext`` is the raw-source
    sibling (``<stem>.wikitext``) when the fetch kept it — anchor passages
    are written in live-article wikitext, so passage checks run against
    that first.
    """
    p = PROJECT_ROOT / cache_file
    if not p.exists():
        return {}
    text = p.read_text()
    m = _REVID_RE.search(text)
    wt_path = p.with_suffix(".wikitext")
    return {
        "revid": int(m.group(1)) if m else None,
        "text": text,
        "wikitext": wt_path.read_text() if wt_path.exists() else "",
    }


def claim_signals(claim: str) -> list[str]:
    """Cheap signal tokens: years + capitalized multi-word phrases.

    Sentence-start scaffolding ("In May", "On July") is dropped — a bare
    month or stopword-led fragment carries no identifying power (#81 §5).
    """
    toks = list(_YEAR_RE.findall(claim))
    for ph in _CAP_RE.findall(claim):
        ph = _SENT_START_RE.sub("", ph).strip()
        if not ph or ph.lower() in _MONTH_WORDS:
            continue
        toks.append(ph)
    return toks


def freshness(store: dict) -> dict:
    """Annotate items with freshness flags vs the cached live page.

    never promotes anything to 'accepted' — token matches only yield
    'possible_already_present'.
    """
    live = (store.get("article") or {}).get("live_page")
    if not live:
        return {}
    page = load_live(live["cache_file"])
    if not page:
        return {"error": f"cache file not found: {live['cache_file']}"}
    live_revid, text, wikitext = page["revid"], page["text"], page["wikitext"]
    out = {"live_revid": live_revid, "items": {}}
    for it in store["items"]:
        prop = it.get("proposal") or {}
        base = prop.get("base_revid")
        if not base:
            continue
        flags = []
        if live_revid != base:
            flags.append(f"needs_review (live revid {live_revid} != base {base})")
        passage = (prop.get("anchor") or {}).get("passage")
        if passage:
            intact = (passage in wikitext) or (passage in text)
            flags.append("passage_intact" if intact
                         else "rebase_needed (anchor passage not found)")
        hits = sorted({t for t in claim_signals(it.get("claim", ""))
                       if t in text})
        if len(hits) >= 2:
            flags.append(f"possible_already_present ({', '.join(hits[:5])})")
        out["items"][it["id"]] = flags
    return out


def _evidence_label(ev: dict, src_meta: dict) -> str:
    if "source" in ev:
        meta = src_meta.get(ev["source"], {})
        url = meta.get("url", ev["source"])
        title = meta.get("title") or ev["source"]
    else:
        url = ev["external"]["url"]
        title = ev["external"]["title"]
    bits = [f"{ev.get('reliability','?')}/{ev.get('independence','?')}"
            f"/{ev.get('coverage_depth','?')}"]
    return f"{title} ({url}) — {'/'.join(bits)}"


def _item_sort_key(it: dict):
    order = {"citable": 0, "citable-attributed": 1,
             "citation-pending": 2, "not-citable": 3}
    return (order.get(it.get("decision"), 9), it["id"])


def build_ir(store: dict) -> dict:
    items = sorted(store["items"], key=_item_sort_key)
    decided = [i for i in items if i["type"] in {"addition", "repair"}]
    return {
        "subject": store["subject"],
        "article": store["article"],
        "gng": store.get("gng", {}),
        "items": items,
        "patch_items": [i for i in decided
                        if i["decision"] in PATCH_DECISIONS
                        and i["status"] in {"proposed", "posted"}
                        and (i.get("proposal") or {}).get("wikitext")],
        "questions": [i for i in items if i["type"] == "question"],
        "excluded": [i for i in items if i["type"] == "excluded"],
        "open_tasks": store.get("open_tasks", []),
        "rationale_blocks": store.get("rationale_blocks", []),
    }


def render_index(ir: dict, fresh: dict) -> str:
    art = ir["article"]
    L = [f"# Wikipedia — {ir['subject'].replace('-', ' ').title()}",
         "",
         "> GENERATED from `data/wikipedia-updates/" +
         f"{ir['subject']}.json` by `scripts/61_render_wikipedia_updates.py`"
         " — do not hand-edit; edit the store and re-render.",
         ""]
    L.append("## Status")
    L.append("")
    if art.get("exists"):
        rev = (art.get("live_page") or {}).get("revid")
        L.append(f"- **Article**: {art['title']} — exists"
                 + (f" (snapshot revid {rev})" if rev else ""))
    else:
        L.append(f"- **Article**: none — mode {art.get('mode')}"
                 + (f"; target `{art.get('title')}`" if art.get("title") else ""))
    L.append(f"- **Mode**: {art.get('mode')} — {art.get('coi', '')}")
    L.append(f"- **GNG**: {ir['gng'].get('status', '?')} — "
             f"{ir['gng'].get('note', '')}")
    if art.get("note"):
        L.append(f"- **Note**: {art['note']}")
    L.append("")
    counts = {}
    for it in ir["items"]:
        counts[it["type"]] = counts.get(it["type"], 0) + 1
    L.append("## Item counts")
    L.append("")
    L.append("- " + "; ".join(f"{v} {k}(s)" for k, v in sorted(counts.items())))
    flagged = sum(1 for f in (fresh.get("items") or {}).values() if f)
    if fresh:
        L.append(f"- freshness: {flagged} item(s) flagged against "
                 f"live revid {fresh.get('live_revid')}")
    L.append("")
    L.append("## Open action items")
    L.append("")
    for it in ir["items"]:
        if it["status"] in {"proposed", "posted"} and it["type"] != "excluded":
            mark = " **Q**" if it["type"] == "question" else ""
            L.append(f"-{mark} `{it['id']}` — {it['claim']} "
                     f"({it['decision']})")
    for t in ir["open_tasks"]:
        L.append(f"- [task] {t}")
    L.append("")
    for b in ir["rationale_blocks"]:
        L.append(f"## {b['title']}")
        L.append("")
        L.append(b["body"])
        L.append("")
    return "\n".join(L)


def render_wikimarkup(ir: dict, fresh: dict) -> str:
    art = ir["article"]
    L = [f"# {ir['subject'].replace('-', ' ').title()} — proposed patch "
         "(GENERATED)",
         "",
         "> Rendered from the update-item store. Do NOT edit Wikipedia "
         "directly without operator approval (PRD Appendix C).",
         ""]
    draft_file = art.get("draft_wikitext_file")
    if draft_file:
        draft = (PROJECT_ROOT / draft_file).read_text()
        L += ["## Article draft wikitext", "", "```wikitext",
              draft.strip(), "```", ""]
    if ir["patch_items"]:
        # freshness gates the paste-ready block: items whose anchor or
        # base revid drifted are held, not pasted (issue #81 §2)
        ready, held = [], []
        for it in ir["patch_items"]:
            flags = (fresh.get("items") or {}).get(it["id"], [])
            if any("rebase_needed" in f or "needs_review" in f
                   for f in flags):
                held.append((it, flags))
            else:
                ready.append((it, flags))
        if ready:
            L += ["## Proposed patch (complete, single block)", "",
                  "```wikitext"]
            for it, flags in ready:
                L.append(f"<!-- {it['id']} — {it['decision']}"
                         + (f" | freshness: {'; '.join(flags)}"
                            if flags else "")
                         + " -->")
                L.append(it["proposal"]["wikitext"])
                L.append("")
            L.append("```")
            L.append("")
        if held:
            L += ["## Held — do not paste until re-verified", ""]
            for it, flags in held:
                L.append(f"- `{it['id']}` ({it['decision']}): {it['claim']}"
                         f" — {'; '.join(flags)}")
            L.append("")
    L += ["## Item decisions (evidence → decision → rationale)", ""]
    for it in ir["items"]:
        if it["type"] == "excluded":
            continue
        L.append(f"### `{it['id']}` — {it['type']}, {it['decision']}")
        L.append("")
        L.append(f"**Claim:** {it['claim']}")
        L.append("")
        for ev in it.get("evidence") or []:
            L.append(f"- {_evidence_label(ev, _SRC_META)}"
                     + (f" — {ev.get('note')}" if ev.get("note") else ""))
        if it.get("evidence"):
            L.append("")
        L.append(f"**Rationale:** {it.get('rationale', '')}")
        L.append("")
    if ir["excluded"]:
        L += ["## Explicitly NOT proposed", "",
              "| Item | Claim | Why excluded |", "|---|---|---|"]
        for it in ir["excluded"]:
            L.append(f"| `{it['id']}` | {it['claim']} | {it['rationale']} |")
        L.append("")
    return "\n".join(L)


def render_talk(ir: dict, fresh: dict) -> str:
    art = ir["article"]
    L = [f"# Talk-page update proposal: {ir['subject'].replace('-', ' ').title()}"
         " (GENERATED)",
         "",
         "> Do NOT post or edit Wikipedia without operator approval "
         "(PRD Appendix C).",
         "",
         "## COI disclosure", "", art.get("coi", ""), "",
         "## Citable / not-citable sort", "",
         "| Claim | Source(s) | Verdict |", "|---|---|---|"]
    for it in ir["items"]:
        if it["type"] == "question":
            continue
        # keep the reliability/independence/coverage suffix — the
        # reliable-domain-vs-incidental-coverage distinction is the
        # information editors need (Moon fixture, #80 §6.3)
        srcs = "; ".join(_evidence_label(e, _SRC_META)
                         for e in (it.get("evidence") or [])) or "—"
        flags = (fresh.get("items") or {}).get(it["id"], [])
        verdict = it["decision"].upper()
        if flags:
            verdict += " | " + "; ".join(flags)
        L.append(f"| {it['claim']} | {srcs} | {verdict} |")
    L.append("")
    if ir["patch_items"]:
        L += ["## Proposed wording", ""]
        for it in ir["patch_items"]:
            L.append(f"- `{it['id']}` ({it['type']}, {it['decision']}): "
                     f"{it['claim']}")
        L.append("")
        L.append("Full paste-ready wikitext in "
                 f"`{ir['subject']}-wikimarkup.md`.")
        L.append("")
    if ir["questions"]:
        L += ["## Questions for editors", ""]
        for i, it in enumerate(ir["questions"], 1):
            L.append(f"{i}. {it['claim']}")
        L.append("")
    if ir["excluded"]:
        L += ["## Explicit non-use", "",
              "The following are disclosed and deliberately excluded "
              "as sources:", ""]
        for it in ir["excluded"]:
            L.append(f"- {it['claim']} — {it['rationale']}")
        L.append("")
    L += _policy_checklist(ir)
    return "\n".join(L)


def _policy_checklist(ir: dict) -> list[str]:
    """Compute the policy checklist from the IR — no hardcoded ticks
    (issue #81 §6).
    """
    art = ir["article"]
    patch = ir["patch_items"]

    def ev_urls(it):
        urls = []
        for e in it.get("evidence") or []:
            if "external" in e:
                urls.append(e["external"]["url"])
            else:
                urls.append((_SRC_META.get(e["source"]) or {})
                            .get("url", ""))
        return urls

    no_personal = not any(
        any(u.startswith(("kkron://", "email://")) for u in ev_urls(it))
        for it in patch)
    affiliated_attributed = all(
        it["decision"] != "citable"
        or it.get("override")
        or any(e.get("independence") == "secondary"
               for e in it.get("evidence") or [])
        for it in patch)
    checks = [
        ("COI disclosed; talk_page/AfC mode over direct edit",
         bool(art.get("coi")) and art.get("mode") in {"talk_page", "afc"}),
        ("Affiliated sources attributed, not asserted in wiki-voice",
         affiliated_attributed),
        ("Personal communications and outreach leads excluded",
         no_personal),
        ("Not-citable / excluded items absent from the patch",
         all(it["decision"] in PATCH_DECISIONS for it in patch)),
        ("No posting without operator approval",
         True),  # structural: these files are local artifacts only
    ]
    out = ["## Policy checklist", ""]
    for label, ok in checks:
        out.append(f"- [{'x' if ok else ' '}] {label}")
    out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("subjects", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--validate-only", action="store_true")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    slugs = list(args.subjects)
    if args.all:
        slugs += [p.stem for p in sorted(STORE_DIR.glob("*.json"))]
    if not slugs:
        ap.error("give a subject slug or --all")

    graph_ids = load_graph_ids()
    global _SRC_META
    _SRC_META = load_source_meta()

    rc = 0
    for slug in set(slugs):
        path = STORE_DIR / f"{slug}.json"
        if not path.exists():
            print(f"{slug}: store not found: {path}")
            rc = 1
            continue
        store = json.loads(path.read_text())
        errors, warnings = validate(store, graph_ids, _SRC_META)
        for w in warnings:
            print(f"  WARN {slug}: {w}")
        if errors:
            rc = 1
            for e in errors:
                print(f"  ERROR {slug}: {e}")
            continue
        fresh = freshness(store)
        if fresh.get("error"):
            print(f"  WARN {slug}: {fresh['error']}")
        print(f"{slug}: valid — {len(store['items'])} items; "
              f"live revid {fresh.get('live_revid', 'n/a')}")
        for iid, flags in (fresh.get("items") or {}).items():
            for f in flags:
                print(f"    {iid}: {f}")
        if args.validate_only:
            continue
        ir = build_ir(store)
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{slug}.md").write_text(render_index(ir, fresh))
        (out / f"{slug}-wikimarkup.md").write_text(render_wikimarkup(ir, fresh))
        (out / f"{slug}-talk.md").write_text(render_talk(ir, fresh))
        print(f"    rendered -> {out}/{slug}{{,-wikimarkup,-talk}}.md")
    return rc


_SRC_META: dict = {}

if __name__ == "__main__":
    sys.exit(main())
