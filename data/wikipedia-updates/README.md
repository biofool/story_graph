# Wikipedia update-item stores (issue #80)

One JSON file per subject is the **decision record**; the three Markdown
files under `docs/wikipedia-drafts/rendered/` are **views** rendered from
it by `scripts/61_render_wikipedia_updates.py`. Do not hand-edit the
rendered files — edit the store and re-render. The legacy hand-maintained
`<slug>{,-wikimarkup,-talk}.md` files remain alongside until the rendered
views are reviewed as equivalent, then they become generated-only.

## Schema

```jsonc
{
  "subject": "hiroshi-ikeda",
  "article": {
    "title": "Hiroshi Ikeda (aikidoka)",   // or null (no article)
    "talk": "Talk:Hiroshi Ikeda (aikidoka)",
    "exists": true,
    "mode": "talk_page | afc | none",
    "coi": "disclosure text",
    "live_page": {                          // or null
      "cache_file": "data/cache/wikipedia/hiroshi-ikeda.md",
      "revid": 1376549637
    },
    "draft_wikitext_file": "…",             // AfC subjects: full draft text
    "note": "…"
  },
  "gng": { "status": "pass | borderline | fail", "note": "…" },
  "items": [{
    "id": "upd:ikeda:asu-independence-2015",      // stable, never reused
    "type": "addition | repair | question | excluded",
    "claim": "what is claimed, one sentence",
    "target_section": "Career",
    "evidence": [{                              // evidence, not decision
      "source": "src:asu-letter-2015",           // graph id — must resolve
      "external": {"url": "…", "title": "…"},    // OR: not yet in graph
      "reliability": "reliable | marginal | unreliable | unscored",
      "independence": "primary-org | secondary | self-report",
      "coverage_depth": "significant | incidental | mention",
      "supports": "full | partial",
      "note": "which part it supports"
    }],
    "decision": "citable | citable-attributed | citation-pending | not-citable",
    "rationale": "why this decision",
    "proposal": {                                // wording — revisable without
      "wikitext": "…",                           // touching the decision
      "anchor": {"section": "…", "passage": "exact live text (repairs)"},
      "base_revid": 1376549637                   // revid the proposal was
    },                                           // verified against
    "status": "proposed | posted | accepted | rejected | superseded",
    "history": [{"at": "2026-09-26", "status": "proposed", "note": "…"}]
  }],
  "open_tasks": ["research tasks that are not update items"],
  "rationale_blocks": [{"title": "…", "body": "markdown"}]
}
```

## Rules enforced by the validator

- unique item ids; `history` append-only and `history[-1].status == status`;
  consecutive same-status entries are allowed (re-scoping notes)
- `addition`/`repair` patch requirements apply only when the subject's
  article exists and has no `draft_wikitext_file` — for AfC/draft subjects
  the draft file IS the proposal
- every `evidence[].source` resolves in `graph_snapshot/` (sources or
  nodes); `external` refs are allowed but warned (not yet in graph)
- `not-citable` / `excluded` items never carry `proposal.wikitext` —
  they cannot enter the proposed patch
- `addition`/`repair` with `decision: citable*` on a live-article
  subject need `proposal.base_revid`; a `repair` needs `anchor.passage`
- status transitions: `proposed → posted|superseded`,
  `posted → accepted|rejected|superseded`, `accepted → superseded`,
  `rejected → proposed`, `superseded` terminal

## Freshness (renderer `--live`)

- live revid ≠ `base_revid` → **needs_review**; `anchor.passage`
  missing from live text → **rebase_needed**, else `passage_intact`
- claim signal tokens present in live text → **possible_already_present**
  — never auto-promotes to `accepted` (that needs a recorded diff +
  reviewer confirmation)
