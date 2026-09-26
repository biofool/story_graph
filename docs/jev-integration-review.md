# Jev Integration Review — Story Graph

Date: 2026-09-26 (corrected per issue #82 review)
Scope: `src/llm/jev_client.py`, `src/llm/entity_claim_extractor.py`,
`scripts/53_jev_eval.py`, `scripts/55_jev_moon_analysis.py`,
`tests/unit/test_jev_claim_verifier.py`, `docs/PRD.md`,
`data/audit/jev_eval_2026-09-22.json`, `data/audit/jev_moon_2026-09-22.json`

## What Jev is here

`src/llm/jev_client.py` is a thin client for TypeSafe System One ("Jev")
bounded decisions over the Decisions API. It answers *typed* questions —
choice sets, `noul` scores, yes/no — about a `state` string in ~70–500ms.
It is not a generative LLM and cannot produce text.

Client characteristics:

- Lazy, opt-in, never raises: `decide()` returns `None` on missing key,
  transport, status, JSON, or response-shape failure — callers' existing
  behavior is preserved on any Jev failure.
- Config: `JEV_API_KEY` (fallback `OPENROUTER_API_KEY`), `JEV_MODEL`,
  `JEV_BASE_URL`, `JEV_TIMEOUT_SECONDS`.
- `.env` pins the direct TypeSafe endpoint
  (`JEV_BASE_URL=https://api.typesafe.ai/v1/systemone`,
  `JEV_MODEL=jev-latest`) — the code default is OpenRouter, which returns
  401 against a direct TypeSafe key (PRD warns of this).
- `answer_confidence()` extracts confidence from explicit `confidence`,
  the selected choice's probability, or a `noul` probability transformed
  by distance from 0.5.
- `verify_claim()` sends source text as state and returns
  `{jev_verdict: supported|contradicted|unresolved, jev_confidence,
  jev_truncated}` or `None`. `verify_claims()` batches a page's claims
  into one `decide()` call when the page fits the state window, else
  falls back to per-claim calls with the window centered on each claim.

## How it is actually used today

Three layers; only the eval layer has run in earnest.

### 1. Claim-verification hook (built, dormant)

`GeminiClaimExtractor` in `src/llm/entity_claim_extractor.py` wraps the
Gemini extractor and, when `verify_claims` is on, annotates each
extracted claim with `jev_verdict` + `jev_confidence` + `jev_truncated`.
Verdict semantics:

- absent — verification was never enabled;
- `"unavailable"` — enabled but no Jev key configured;
- `"unverified"` — the call ran but returned no usable answer;
- `supported | contradicted | unresolved` — a real verdict.

Claims are never dropped.

It is instantiated in 7 ingest scripts (`34_enrich_person`,
`03_targeted_entity_research`, `04_cyprus_crtg_research`,
`reingest_aikiclub`, `ingest_a_person`, `02_gemini_search`,
`reingest_mojibake`) — all with defaults, gated on `JEV_CLAIM_VERIFY`,
which is **not set** in `.env`. The production path exists but has never
fired.

### 2. Offline evaluations

- `scripts/53_jev_eval.py` — live eval of `identity_match`,
  `entity_resolution`, `event_dedup` on ~10% labeled samples →
  `data/audit/jev_eval_2026-09-22.json`. Results: entity_resolution ~91%
  (10/11), event_dedup 100% (6/6), identity_match 82% (28/34, or 88%
  after correcting label noise). Errors were mostly conservative
  abstentions on thin/garbled OCR.
- `scripts/55_jev_moon_analysis.py` — Moon-scoped eval (entity
  resolution, identity match, event dedup, claim verification) →
  `data/audit/jev_moon_2026-09-22.json`. Entity resolution 6/6, event
  dedup 4/4.

  **Corrected reading of the identity_match numbers** (issue #82):
  the recorded "110/252 correct" mixed three different things. Rescored
  on the axes that matter for triage:
  - safe exclusion — 237/237 non-subject items kept out (100%; zero
    false inclusions);
  - subject recall — **8/15 (53%)**: of 15 verified-subject articles,
    Jev returned `different_person` for 3 and `insufficient_evidence`
    for 4. Missing a real subject article is the costly error for
    newspaper triage, and it is the weak axis, not exclusion;
  - exact label — much lower, since many `insufficient_evidence`
    expectations came back `different_person`.

  The claim_verification "11/13" in that audit is **not an accuracy
  figure** — the checks had no expected labels; 11 is just the count of
  `supported` verdicts. Script 55 now carries a labeled set (including
  known-contradicted and unresolved claims) so future runs report real
  accuracy.

### 3. Governance

`docs/PRD.md` records the credentials story, a candidate-kinds table
(`identity_match`, `entity_resolution`, `event_dedup`,
`source_relevance`, `disposition_classify`, `review_priority` — all
"unimplemented/shadow-only"), and constraints: fallback to rules, never
destructive, human gate.

Note: `data/wikipedia-updates/richard-moon.json` previously cited "JEV
identity_match verified 73/73 collision labels" — that meant 73/73
*safely excluded* (49 `different_person` + 24 `insufficient_evidence`),
not 73 correct labels. The store wording has been corrected.

## Gaps

- **Verdicts were dropped before persistence** (fixed in #82):
  `process_page` built claim-node metadata from a fixed field list, so
  `jev_verdict`/`jev_confidence` never reached the graph. They now flow
  through, plus `jev_truncated`.
- **Verification is built but off** — `JEV_CLAIM_VERIFY` unset; no caller
  passes `verify_claims=True`.
- **The highest-value use isn't connected** — `identity_match` for
  newspaper-corpus triage remains a manual/eval step; scripts 42–44 and
  48's `--taught-by` screening don't call it. The 53% subject recall
  says it is not ready to act on — shadow only.
- **Truncation bias** — `verify_claim` caps state at 12,000 chars; claims
  extracted from beyond the cutoff would reliably return `unresolved`.
  Fixed in #82 by windowing the state around the claim and flagging
  `jev_truncated` on the verdict.
- **No confidence policy** — `answer_confidence` exists but nothing
  consumes it; the Moon run accepted `supported` at 0.49 confidence flat.
- **Not in the Wikipedia pipeline** — `scripts/61` validates that
  evidence *references* resolve, not that source text *entails* the
  claim.

## Recommended next steps, in order

1. ~~Persist Jev verdicts~~ (done, #82) — then **enable
   `JEV_CLAIM_VERIFY=1` on one bounded real ingest** (a reingest of a
   single subject). Record verdict/confidence/truncation distribution to
   `data/audit/` — real-world false-"contradicted" rates are unknown.
2. **Shadow `identity_match` in newspaper/OCR triage** (scripts 42–44,
   48 `--taught-by`), post-OCR. Log decisions without acting; compare
   against existing dispositions. The 53% subject recall means tuning
   (identity-card wording, OCR quality gate) is needed before this can
   do more than annotate.
3. **Script-61 Jev entailment shadow — needs design first.** `scripts/61`
   is deterministic, offline, and fails closed; its evidence entries are
   graph source IDs / external URLs, not source text. A Jev pass needs
   an evidence→text resolver (graph source id → local article `.txt`;
   external URL → cached fetch) and must live behind a separate flag or
   script writing to `data/audit/` — the fail-closed validator and
   rendered views must never depend on the network or Jev being up.
4. **`entity_resolution` as a ranker for dedup candidates** (script-50
   pattern) — Jev orders the queue, the human still merges.
   `source_relevance` for pre-download screening is furthest out — it
   saves the most quota but needs its own labeled set and false-negative
   analysis.

## Operating pattern to preserve

Bounded decision kinds, annotation-only until a labeled eval +
confidence/disagreement policy exists, human gate for anything
destructive. No silent claim deletion, no automatic graph merges, no
automatic Wikipedia publication. Fail-open: Jev failure must preserve
existing caller behavior — and now records *why* there is no verdict.
