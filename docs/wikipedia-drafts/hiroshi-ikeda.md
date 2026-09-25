# Wikipedia — Hiroshi Ikeda

> Status index. Convention per [#73](https://github.com/biofool/story_graph/issues/73):
> 3 maintained files per subject — this index, `-wikimarkup.md`, `-talk.md`.
> Generated artifacts live under `generated/` and are regenerable, not maintained.

## Open action items

- **Hometown: Hachijō-jima** — born January 1950 on Hachijō Island
  (八丈島), ~290 km south of Tokyo, administered as Tokyo Metropolis.
  Confirmed independently by **Aikido Journal #104 (1995)** — proposed
  birthplace refinement in the wikimarkup.
- **Citable martial-arts sources — now 5 RELIABLE** — full
  aikidojournal.com sweep ingested (2026-09-25): AJ #104 interview,
  Encyclopedia entry, Aloia interview 2020, "Aikido for Tomorrow"
  feature, Kayla Feder interview — all SRS 70 RELIABLE. MARGINAL:
  Bernews 2011 (65), elephant journal 2009 (60), MAYTT 2023 (50).
- **MAYTT 2019 demoted — verbatim reprint** — the MAYTT "Aikido's
  Current State" post (2020-07-01) is word-for-word the AJ March 2020
  Aloia interview (MAYTT is Aloia's own blog, says so on the page).
  Reclassed `documentary_promotional` so it doesn't double-count.
- **MAYTT 2023 = distinct, fact-rich** — "A Journey with Mitsugi
  Saotome" adds: ASU Vice-Presidency, early-2015 independence from ASU,
  2016 Aikido Shimbokukai VP under Lisa Tomoleoni, 3 yrs high-school
  judo, Bill McIntyre's 1976 Florida invitation, Sarasota "12th Street
  Dojo", and Aikido Bridge captions (10th Anniv. San Diego ~2015,
  Turkey 2018). NOTE: this interview's intro dates aikido start 1969
  and Reimei Juku 1971 — **conflicts with 1968/1970** elsewhere;
  recorded as `claim:ikeda:aikido-start-year-discrepancy`, unresolved.
- **Aikido Bridge corroborated beyond affiliated sites** — MAYTT 2023
  captions + AJ "Aikido for Tomorrow" (Feb 2020, Boulder Aikikai,
  conceived as a youth offshoot of a Bridge seminar). Still
  interview/caption-level — strengthens existence/reach, not formal-org
  claims.
- **Kona seminars corroborated** — Aiki Kai o Kona (Kailua-Kona)
  published its 31st Anniversary Seminar with Ikeda (Jan 2019); host-
  dojo record, independent of Ikeda's own properties. FB page
  facebook.com/AikiKaiOKona. NOTE: this is the Kona side — distinct
  from the Ka'u claim below.
- **Ka'u / Floating Bridge still uncorroborated** — zero web/FB
  presence for "Floating Bridge Aikido" / "Ka'u Aikikai" (searched
  2026-09-25). Remains Klein personal-communication only; path = the
  2024/2025 flyers or Gary Reiss (`greissoffice@gmail.com`).
- **Black Belt coverage unverified** — Google Books rate-limited the
  check; no Ikeda coverage confirmed. Other martial-arts press: Aikido
  Journal found; Aikido Today unsearched; Bu Jin Newsletter is his own
  company (affiliated).
- **Live-article repairs** — empty `[[ ]]` link text in the "In 1980,
  Ikeda moved to Boulder" sentence (renders as `established [ ]`), and
  "based in the Boulder, CO" grammar. Small repair proposal in the
  wikimarkup.
- **"Scheduled seminars" goes stale** — the live section is dated "As
  of 17 September 2026" and will rot; propose a dated-update convention
  or trimming on the talk page.
- **Aikido Bridge addition** — proposed sentence (2005 founding, "Un
  Pont" seminar, Jiai Aikido San Diego); sources are affiliated
  (aikidobridge.com, hiroshi-ikeda.com) — attribution used, editors
  judge acceptability.
- **"Visited frequently" edges ≠ affiliations** — Harmonie Club 87,
  Instituto Takemussu, Two Cranes etc. are outreach leads ("schools he
  visited frequently"), NOT to be asserted as `DOJO_AFFILIATION` in the
  article (the Varjan-incident discipline; Kohala denial preserved in
  graph).
- **Graph gap to ingest** — the live article cites three
  Newspapers.com seminar items the graph lacks: Missoulian 1982-04-13,
  Bradenton Herald 1991-09-29, Pensacola News Journal 2000-09-30.
- Nothing is posted to Wikipedia — all proposals await operator review.

## Status

- **Live article**: [Hiroshi Ikeda (aikidoka)](https://en.wikipedia.org/wiki/Hiroshi_Ikeda_(aikidoka))
  — exists. Snapshot: revid 1376549637, retrieved 2026-09-25
  (`generated/hiroshi-ikeda-live-wikipedia.md` + `.wikitext`).
- **Mode**: `talk_page` — COI (project runs outreach to dojos about
  Ikeda; kkron's correspondences are graph evidence, not publishable
  sources) and the only new sourced material rests on affiliated
  organizations.
- **GNG**: the article exists; notability itself isn't the issue —
  **citable new material is**. After the 2026-09-25 source hunt the
  subgraph holds **1 RELIABLE + 4 MARGINAL** independent sources
  (Aikido Journal interview; Bernews, elephant journal, MAYTT×2) —
  enough for an attributed birthplace refinement and one or two
  seminar additions, not for bulk new content.
- **Compare verdict**: live article is reasonably complete for what
  independent sources cover; the graph's research frontier (Ka'u
  seminars, visited-dojos list, seminar calendar) is mostly personal
  communication + organizational records — preserved in the graph,
  excluded from Wikipedia until independently published.

## Files

- [`hiroshi-ikeda-wikimarkup.md`](hiroshi-ikeda-wikimarkup.md) —
  proposed update: Aikido Bridge sentence, minor repairs, and the
  explicit not-proposed list.
- [`hiroshi-ikeda-talk.md`](hiroshi-ikeda-talk.md) — talk-page
  proposal: COI, citable/not-citable sort, editor questions.
- `generated/`
  - `hiroshi-ikeda-live-wikipedia.md` / `.wikitext` — live snapshot
    (revid 1376549637).
  - `hiroshi-ikeda-compare-report.md` — graph↔live comparison.
  - `hiroshi-ikeda-article.md`,
    `hiroshi-ikeda-reliability-report.md` — script-32 outputs
    (regenerate via `scripts/32_generate_wikipedia_article.py "hiroshi
    ikeda" --skip-notability-check ...`).
