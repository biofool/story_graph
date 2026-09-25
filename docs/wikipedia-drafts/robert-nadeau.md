# Wikipedia — Robert Nadeau

> Status index. Convention per [#73](https://github.com/biofool/story_graph/issues/73):
> 3 maintained files per subject — this index, `-wikimarkup.md`, `-talk.md`.
> Generated artifacts live under `generated/` and are regenerable, not maintained.

## Open action items

- **Live-article defects** — the live article has a "Nadeua" typo
  (Teaching career section), two `sfn error: no target` citations
  (`Moon2026`, `Pranin1999`), and a teaching-certificate sentence split
  mid-clause by image markup. A repair proposal is owed to
  Talk:Robert Nadeau (aikidoka); see compare report.
- **Russia section sourcing** — all four Russian sources are
  organizational/archival (dojo and federation sites), not independent
  journalism. The proposed section uses attribution, but editors must
  judge whether WP:PRIMARY sourcing suffices — that question is left
  open in the talk proposal, not resolved by us.
- **Aikido Today Magazine** (1986–2005) — most likely English-language
  publication to have covered the USSR trips; complete e-book available
  (Budovideos). Check for Nadeau/Russia coverage.
- **Nadeau bio book** — *Aikido: The Art of Transformation* (2024),
  co-authored by six students: **Noha, Herr, Teja Bell, Richard Moon,
  Susan Spence, Elaine Yoder** (confirmed via MAYTT interview, #75
  sweep). May contain Russia-trip coverage; check.
- **New sourced material to fold into proposals** — authority sweep
  (#75) added: Nadeau's AJ Encyclopedia entry; **Robert Tann named as
  Nadeau's pre-Japan aikido teacher** (Marine/SSF police officer,
  taught 1960–72); **Aikikai dispatched Nadeau to the Mountain View
  dojo** (~1966, per Noha); AANC encyclopedia entry names Nadeau a
  principal instructor; Human Potential Movement circle corroborated
  (Murphy/Esalen/*Golf in the Kingdom*, Leonard, Frager). Leonard's
  entry confirms "first taught by Robert Nadeau" + Tamalpais chief
  instructor. Reliability report now scores **19 RELIABLE** sources.
- **Aikido Shimbun** — Japanese aikido press, unsearched for
  international seminar coverage.
- **Travel companions** — no source documents who traveled with Nadeau
  to the USSR; negative finding recorded in wikimarkup notes.
- **Graph cleanup** — 8 `MEMBER_OF` edges pointing at Person nodes are
  mis-typed (flagged in compare report §data-quality).
- Nothing is posted to Wikipedia — all proposals await operator review.

## Status

- **Live article**: [Robert Nadeau (aikidoka)](https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka))
  — exists. Snapshot: revid 1375338198, retrieved 2026-09-24
  (`generated/robert-nadeau-live-wikipedia.md`).
- **Mode**: `talk_page` — COI (kkron knows the subject; his
  recollections are first-class graph evidence but not publishable
  sources) + the Russia sources are organizational/archival, both of
  which require uninvolved-editor review.
- **Scope of current work**: a proposed "Seminars in the Soviet Union"
  addition (Oct 27, 1990 Lenkai club training documented by Russian
  organizational sources) plus live-article defect repairs identified by
  the compare report.
- **GNG**: PASS (internal assessment — live article already exists;
  Aikido Journal interview + 2025 feature + Wikipedia article itself
  score RELIABLE).

## Files

- [`robert-nadeau-wikimarkup.md`](robert-nadeau-wikimarkup.md) —
  proposed USSR-seminar section wikitext + per-source analysis +
  talk-page sourcing rationale.
- [`robert-nadeau-talk.md`](robert-nadeau-talk.md) — talk-page proposal
  with COI disclosure, citable/not-citable sort, proposed wording, open
  editor questions.
- `generated/`
  - `robert-nadeau-live-wikipedia.md` — live article snapshot (revid
    1375338198).
  - `robert-nadeau-compare-report.md` — graph↔live comparison: 44
    candidate additions, defect findings, uncited sources.
  - `robert-nadeau-article.md`, `robert-nadeau-report.md`,
    `robert-nadeau-reliability-report.md` — script-32 outputs
    (regenerate via `scripts/32_generate_wikipedia_article.py "robert
    nadeau" ...`).
  - `robert-nadeau-russia-entry.md` — archive-search record and source
    reliability table superseded by the wikimarkup file.
