# Sig Kufferath Wikipedia — Notability Megaplan

> Created 2026-09-15. Addresses the notability-gap critique of the live
> article https://en.wikipedia.org/wiki/Siegfried_Kufferath and the open
> issue #45 (source package). The article currently rests entirely on
> affiliated/primary sources (danzan.com, kodenkan.com, usadojo.com,
> kuialuaopuna mirrors, AJJF, kkron personal communication). WP:GNG
> requires **multiple independent, reliable, secondary sources with
> significant coverage**. This plan is the research strategy to find them,
> ingest them, and rebuild the draft so it passes notability.

## The gap, precisely

WP:GNG / WP:BIO for a standalone biography needs ≥2 sources that are
simultaneously:

1. **Independent** — not written by the subject, a student, a family
   member, or an organization that certifies/promotes his lineage
   (AJJF, AJI, Kodenkan, Kilohana, KDRJA all fail this).
2. **Secondary** — analyzes/reports at one remove, not a primary
   first-person account or org bio.
3. **Reliable** — editorial oversight (newspaper, peer-reviewed journal,
   book from an established press). Blogs, dojo pages, Find a Grave,
   Scribd reposts, and Wikipedia cross-refs all fail.
4. **Significant coverage** — more than a passing mention; treats him as
   a subject in his own right.

Current graph sources scored against this: 0 pass. Every ingested source
is affiliated or primary. The critique lists 6 specific claims
(superlative senior student; defeated Army instructor / reassigned to
Special Services; 11 languages; 1953 AJI succession significance; CAA
formation via Nadeau; multiple 10th-dan honours) that each need an
independent source or must be reduced/removed.

## Research targets (ranked by likelihood of yielding GNG-grade sources)

### Tier A — highest yield, prioritize first

1. **Honolulu newspapers, 1937–1960** — Kufferath lived in Honolulu for
   ~50 years, was a 3-time Hawaiian AAU 440-yard champion (late 1920s/early
   30s), an auditor for City & County of Honolulu, instructed Honolulu
   Police and US military during WWII, and ran the Kodenkan after Okazaki.
   Local sports coverage, community-class announcements, exhibition
   notices, and police/military instruction are all plausible newspaper
   hits.
   - Free: **Chronicling America** (LOC, chroniclingamerica.loc.gov) —
     Honolulu papers pre-1963 are in scope.
   - Free: **Hawaii Digital Newspapers** (hawaii.gov/libraries/digital-
     newspapers), Honolulu Star-Bulletin / Honolulu Advertiser archives.
   - Paywalled (request via WP:RELIBRARY or a library card):
     Newspapers.com, ProQuest Historical Newspapers.

2. **Obituaries, May 1999** — died May 7 1999 in Santa Clara. Obituaries
   in *San Jose Mercury News*, *Santa Clara* local paper, *Honolulu
   Star-Bulletin* / *Honolulu Advertiser*. A substantive obituary in a
   major paper is independent secondary coverage and counts toward GNG.
   - Search: Newspapers.com, Legacy.com, Google News archive
     (news.google.com/newspapers), ProQuest obituaries.
   - The *Mercury News* is a major metro paper; a substantive obit there
     alone could carry notability.

3. **Books on Okazaki / Danzan-ryū / Hawaiian jujitsu by independent
   authors** — any published book (university press or established
   commercial press) that covers Okazaki's school and discusses
   Kufferath's role in succession is independent secondary coverage.
   - Search: Google Books API (already specced in PRD), HathiTrust,
     Internet Archive, WorldCat.
   - Candidate authors/histories to check: works by **George Arrington**
     (note: Arrington is a Danzan-ryū practitioner — affiliated, so his
     danzan.com page is primary, but a *published book* by him with a
     press may still count as secondary if editorially overseen), works
     citing Okazaki in martial-arts historiography.
   - Check citations in the *Seishiro Okazaki* Wikipedia article and its
     sources for books that also cover Kufferath.

### Tier B — strong supporting, pursue in parallel

4. **Scholarly theses/dissertations on Japanese martial arts in Hawaiʻi**
   — University of Hawaiʻi theses, or kinesiology/anthropology/history
   dissertations elsewhere, that treat Danzan-ryū or Okazaki's school.
   Peer-reviewed = reliable; independent of the lineage = independent.
   - Search: ProQuest Dissertations & Theses (abstracts free), Google
     Scholar, UH Mānoa ScholarSpace (scholarspace.manoa.hawaii.edu).

5. **Black Belt Magazine / martial-arts press** — Black Belt is a legacy
   edited magazine (per the wikipedia-article-generator skill's
   martial-arts source guidance). Any feature/profile of Kufferath, or
   of Danzan-ryū succession that discusses him in depth, is independent
   secondary.
   - Search: Black Belt archive (blackbeltmag.com), Google Books for
     Black Belt annuals, Internet Archive magazine scans.

6. **Aikido Journal** (aikidojournal.com) — edited, independent of the
   Danzan-ryū lineage. If they covered the Kufferath–Nadeau Bay Area
   connection or Danzan-ryū succession, it's a strong secondary source.
   - Search: aikidojournal.com site search, Stanley Pranin's writings.

### Tier C — lower yield but worth a pass

7. **University of Hawaiʻi archives / Hawaiian Historical Society** —
   archival holdings on the Kodenkan or Okazaki. Primary, but if later
   cited in a published secondary work, that work is the citable source.
   Use archives to *find* the secondary work, not to cite directly.

8. **Mountain View / Sunnyvale community newspapers, 1960–1999** —
   Kufferath taught in Mountain View and Santa Clara for ~40 years.
   Local paper coverage of his classes, demonstrations, or restoration
   therapy practice. Smaller papers are weaker for GNG but can
   corroborate.

9. **California Aikido Association records / CAA history** — the CAA
   formation claim (Kufferath–Nadeau–Bunch nexus) is one of the contested
   claims. An independent CAA history (not on a CAA-affiliated site) or
   Aikido Journal coverage would support it. (See open issue #44.)

## Execution plan

### Phase 1 — Source discovery (research, no graph changes)

Goal: produce a ranked list of candidate independent secondary sources
with URLs, access status (free/paywalled/needs ILL), and a one-line
relevance note. Output to `docs/kufferath-source-search-results.md`.

Searches to run (each logged with query + engine + date + result count):

- **Gemini seed discovery** (`scripts/02_gemini_search.py`) — broad
  queries: "Sig Kufferath", "Siegfried Kufferath", "Kufferath Okazaki
  successor", "Kufferath obituary 1999", "Kufferath Honolulu jujitsu".
- **Brave Search** — once issue #37 is fixed (key is
  `BRAVE_ANSWERS_API_KEY` in Secret Manager). Brave's news/archive
  vertical is good for obituary and old-coverage discovery.
- **Google Books API** — specced in PRD (issue ff7eb18). Queries:
  "Kufferath", "Okazaki Danzan-ryū", "Kodenkan jujitsu Hawaii".
- **Google Scholar** — "Kufferath" + "Okazaki" + "Danzan-ryū" +
  "Hawaiian jujitsu".
- **Chronicling America** direct API — Honolulu papers, 1937–1963,
  queries: "Kufferath", "Kodenkan", "Okazaki jujitsu".
- **Aikido Journal site search** — "Kufferath", "Danzan-ryū",
  "Nadeau Mountain View".
- **Wikipedia adjacent-article source mining** — pull the references
  from Seishiro Okazaki, Danzan-ryū, and Robert Nadeau articles; any
  independent source covering the lineage may also cover Kufferath.

For each candidate source, record:
- title, author, publisher, date, URL
- access (free/paywalled/abstract-only)
- independence assessment (affiliated with lineage? yes/no)
- likely coverage depth (passing mention / substantial)
- SRS pre-score (domain tier + WP:RSP if listed)

### Phase 2 — Access & verification

**Constraint: no local library access.** No ProQuest, no Newspapers.com,
no ILL. Access is limited to free/open channels and on-wiki requests.

For paywalled sources that look strong (substantial Honolulu or Mercury
News coverage, a book chapter, a thesis):

- **WP:RELIBRARY** (Wikipedia editor resource exchange — free, on-wiki)
  and **WP:RX** are the primary paywall-bypass routes. Post a request
  with the citation details; another editor with access may provide a
  scan or transcript.
- **Google Books full-view / preview** — filter to "full view only" or
  "preview" (not snippet). Full-view books are citable directly; preview
  enough to read the relevant pages is citable. Snippet-only is a lead,
  not a citation.
- **HathiTrust full-view** (catalog.hathitrust.org) — public-domain and
  open-access full text. Search the full-text index for "Kufferath".
- **Internet Archive** (archive.org) — scanned books, magazines, and
  community newspapers in the public domain or uploaded by libraries.
  Full-text search via the archive's search.
- **Google Scholar** — abstracts are free; a thesis abstract that
  confirms substantial coverage is enough to request the full text via
  WP:RELIBRARY or contact the author.
- **Free newspaper archives**: Chronicling America (LOC, pre-1963),
  Google News archive (news.google.com/newspapers), state digital
  newspaper programs (Hawaii Digital Newspapers, California Digital
  Newspaper Collection at cdnc.ucr.edu — already ingested via
  `scripts/11_ingest_cdnc.py`).

Do NOT cite a source we cannot read. A Google Books *snippet* that
shows Kufferath's name is a lead, not a citation — we need the
surrounding context to confirm significant coverage. If a strong
paywalled source is found but no free access path works, list it in
the reliability report as "CITATION PENDING — access needed" and flag
for WP:RELIBRARY request rather than citing blind.

### Phase 3 — Ingest verified sources into the graph

For each source that passes (independent + secondary + reliable +
significant coverage):

- Ingest via the existing pipeline (`scripts/ingest_a_person.py` or the
  crawl pipeline) with `source_class: journalistic` / `archival` and
  correct `bias_hint`.
- Add Claim nodes for the facts each source supports, with the source
  URL as evidence.
- Re-run alias dedup (the 8 duplicate Person nodes + the
  `shin-hori-kufferath` mis-extraction noted in the data dump) so the
  new sources attach to `person:sig-kufferath` cleanly.

### Phase 4 — Rebuild the Wikipedia draft

- Run `scripts/32_generate_wikipedia_article.py "sig kufferath" --dry-run`
  to get the updated reliability report. Confirm ≥2 sources now score
  SRS ≥70 and provide significant coverage (GNG pass).
- Generate the full draft with `--article` / `--report`.
- The draft should now lead with the independent sources. Affiliated
  sources (danzan.com, kodenkan.com) drop to corroborating-only for
  minor facts; they no longer carry notability or contested claims.
- Reduce or remove the 6 contested claims that lack independent support
  (per the critique). Keep them only if a Tier A/B source covers them.

### Phase 5 — Update the live article / respond to the critique

- If the article is at AfD or has a notability tag: prepare a
  Talk-page response citing the new independent sources and the
  reliability report.
- Update the live article's references with the verified independent
  sources, replacing bare-domain citations with full paths (issue #45
  already resolved the URLs; now swap in better sources).
- Update issue #45 with the new source package and close the
  notability gap.

## Success criteria

The plan succeeds when the graph contains ≥2 sources that are all four
of {independent, secondary, reliable, significant coverage}, the
`32_generate_wikipedia_article.py` dry-run reports a GNG pass, and the
live article's reference list is rebuilt on those sources with the 6
contested claims either independently supported or removed.

## What this plan does NOT do

- Does not fabricate sources. If Tier A/B yield nothing, the honest
  conclusion is that Kufferath may not meet WP:GNG for a standalone
  article, and the right move is a merge/redirect to Seishiro Okazaki
  or Danzan-ryū (where his role is verifiable from the lineage sources
  in a non-BLP context). We find out before claiming notability.
- Does not rely on kkron personal communication for article text. Per
  AGENTS.md and the skill, kkron assertions stay in the graph as
  first-class evidence but are `primary_first_person` — excluded from
  Wikipedia citation.
- Does not bypass paywalls. Paywalled sources are accessed through
  legitimate free channels (WP:RELIBRARY, WP:RX, open archives) or not
  cited.

## Open questions for kkron

1. Are there any physical artifacts — old Black Belt magazines, a
   Kufferath obituary clipping, a Kodenkan program booklet — that could
   be scanned and cited? (The repo already ingests scanned PDFs, e.g.
   the Aikido in America pp.43-46 in commit ea68034.) With no library
   access, primary-source artifacts you hold are the fastest route to
   verifiable citations.
2. Is the goal to keep the standalone article, or would a
   merge/redirect to Danzan-ryū be acceptable if GNG can't be met?

## Access constraint (confirmed 2026-09-15)

No local library access. No ProQuest, no Newspapers.com, no ILL. The
plan relies on: free/open archives (Chronicling America, CDNC, Google
News archive, Internet Archive, HathiTrust full-view), Google Books
full-view/preview, Google Scholar abstracts, Aikido Journal free
articles, and on-wiki requests (WP:RELIBRARY / WP:RX) for paywalled
sources that can't be reached otherwise. If a strong source is found
behind a paywall with no free path, it's flagged as CITATION PENDING
and requested via WP:RELIBRARY rather than cited blind.
