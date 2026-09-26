# Wikipedia — Peter Ralston

> Status index. Convention per [#73](https://github.com/biofool/story_graph/issues/73):
> 3 maintained files per subject — this index, `-wikimarkup.md`, `-talk.md`.
> Generated artifacts live under `generated/` and are regenerable, not maintained.
> Pipeline v2 (#80): `data/wikipedia-updates/<slug>.json` is now the
> decision record; `rendered/<slug>{,-wikimarkup,-talk}.md` are the generated
> views (scripts/61_render_wikipedia_updates.py). This file is frozen pending
> review that the rendered views cover it.

## Open action items

- Identify the 1978 tournament's **organizer / governing body**
  (checklist F — the one real factual gap).
- Black Belt page-image pass: **byline spelling** (OCR "Cressey" vs
  "Cressy") + paragraph-level coverage map (A).
- **Full read of the Blitz piece** — edited vs. promotional; does it
  rely on Ralston's own account for the 1978 result? (B)
- **Nov 1979 *East West Journal* interview** — library/microfilm lookup;
  "Karate Illustrated 1981" citation also unverified (D).
- **WorldCat / books pass** for substantial coverage + academic-source
  check (D).
- Birth year: contemporaneous "28" → ~1949–50; kept `Year of birth
  missing` pending an exact-year source.
- Tournament **ruleset** unrecorded (F — light-heavyweight confirmed).
- **Authority sweep (#75)**: no new Ralston-specific citable sources —
  the only substantive hit is Patrick Cassidy's AJ contributor bio
  ("continued his training with Peter Ralston, Robert Nadeau Shihan
  and Richard Moon Sensei"), ingested as a RELIABLE-class mention tying
  a common student to all three subjects. MayTT "peter ralston" hits
  were incidental name matches, not ingested.
- Submission wording asks reviewers to **assess** GNG; the draft does
  not claim it (G — talk §4 "Request for assessment").
- Nothing is posted to Wikipedia — drafts await operator review.

## Status

- **Live article**: none. `Peter Ralston` deleted at AfD twice — 2010 and
  **2026-09-15** ([2nd nomination](https://en.wikipedia.org/wiki/Wikipedia:Articles_for_deletion/Peter_Ralston_(2nd_nomination))).
- **Target title**: `Peter Ralston (martial artist)` (AfD nominator's
  suggestion; a same-named photographer exists).
- **Mode**: **AfC + talk page** — AfD history makes mainspace recreation
  G4-eligible; COI (requester authored the deleted article) requires
  uninvolved-editor review. `direct_edit` unavailable.
- **GNG**: PASS (internal assessment — submission wording asks reviewers
  to judge, does not claim it) — 5 independent sources cover the 1978
  championship:
  *Oakland Tribune* Apr 1978 + *Black Belt* Dec 1978 (both contemporaneous),
  *SF Chronicle* Sep 1979, *Parade* Mar 1982, *Blitz* Aug 2011.
- **Source verification (2026-09-25)**: Black Belt verified in the Google
  Books scan (p.46 byline OCRs "Cressey"); Parade syndication confirmed
  (~60 papers carried the identical page on 1982-03-07); Blitz verified via
  Wayback captures of the official blitzmag.net article + doczz issue scan.
  **Unverified**: Nov 1979 *East West Journal* interview — library/microfilm
  lookup needed.
- **Last reviewed**: 2026-09-25 (post-AfD draft + source-verification pass).
- **Tracking**: [#53](https://github.com/biofool/story_graph/issues/53) —
  Peter Ralston Wikipedia open items.

## Files

- [`peter-ralston-wikimarkup.md`](peter-ralston-wikimarkup.md) — article
  draft (wikitext) + editorial notes on what was dropped and why
- [`peter-ralston-talk.md`](peter-ralston-talk.md) — talk-page/AfC proposal:
  mode rationale, AfD objection→response table, citable/not-citable sort,
  COI disclosure
- [`generated/peter-ralston-reliability-report.md`](generated/peter-ralston-reliability-report.md)
  — source scoring; regenerate via
  `scripts/32_generate_wikipedia_article.py "peter ralston" --report <path>`

Full per-item status (verified / partial / open with evidence) is in
`peter-ralston-talk.md` §5 "Sourcing checklist — status".
