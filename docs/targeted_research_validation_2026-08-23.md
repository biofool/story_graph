# Targeted Entity Research — Validation Results

**Date**: 2026-08-23
**MR**: [!3 — Add targeted entity research script](https://gitlab.com/biofool-vig/story_graph/-/merge_requests/3)
**Method**: Independent web searches (Brave/web_search) mirroring the queries
`scripts/03_targeted_entity_research.py` issues via Gemini + Google Search
grounding, plus local execution of the script's `--dry-run` and
`--skip-search` modes and its test suite.

## Script & test validation

| Check | Result |
|---|---|
| `--dry-run` prints leads + queries | Pass |
| `--skip-search` stores kkron's 6 claims in temp SQLite DB | Pass |
| Confidence clamping to <= 0.5 ceiling (raw 0.75->0.5, 0.85->0.5, 0.7->0.5, 0.35->0.35) | Pass |
| Wild Mountain Cafe lead stays below others (0.35 < 0.5) | Pass |
| All claims marked `pending_independent_corroboration=True` | Pass |
| kkron source recorded as `primary_first_person` | Pass |
| Idempotent (2nd run produces identical node/edge counts, no duplicates) | Pass |
| 24 unit + integration tests | All pass |

## Lead-by-lead corroboration

### Strongly corroborated by multiple independent sources

#### Lead 3 — Jim Baker FOUNDED Aware Inn (kkron conf 0.7)

- [Restaurant-ing through history](https://restaurant-ingthroughhistory.com/2011/07/12/famous-in-its-day-the-aware-inn/):
  "When Jim and Elaine Baker opened it [the Aware Inn] in 1957"
- [Wikipedia (Father Yod)](https://en.wikipedia.org/wiki/Father_Yod):
  "Baker had two other successful restaurants on Sunset Strip, the Aware Inn
  and the Old World"
- [LAist](https://laist.com/news/la-history/source-family-restaurant-vegetarian-dinner-gratitude-kitchen-dec-5):
  "Around 1958, Baker and his wife, Elaine, opened the Aware Inn at 8828
  Sunset Blvd."
- [NYT 1976](https://www.nytimes.com/1976/10/23/archives/spirit-of-dashing-founder-guides-commune.html):
  "He started the Aware Inn, which became a hangout for the hip"
- [Hollywood Reporter](https://www.hollywoodreporter.com/news/general-news/the-source-sxsw-cabo-cantina-300212/):
  confirms Baker ran the Aware Inn in the 1950s

**Verdict: Corroborated.** Jim Baker (Father Yod) founded/ran the Aware Inn.

#### Lead 4 — Aware Inn PRECEDES The Source (kkron conf 0.7)

- Restaurant-ing through history: Aware Inn opened 1957 -> The Source
  established 1969 after divorce from Elaine
- Wikipedia: "In 1969, Baker founded the Source Restaurant"
- NYT: "He started the Aware Inn... He had the Old World, and finally he had
  The Source"
- LAist, Eater LA: all confirm the chronological sequence

**Verdict: Corroborated.** The Aware Inn (1957/1958) preceded The Source
(1969).

#### Lead 5 — Jim Baker FOUNDED The Source (kkron conf 0.85)

- Wikipedia: "In 1969, Baker founded the Source Restaurant on the Sunset
  Strip"
- NYT: "Mr. Baker founded The Source about 1969"
- [Eater LA](https://la.eater.com/2013/5/13/6435783/the-source-las-first-spiritual-vegetarian-restaurant),
  LAist, Hollywood Reporter: all confirm

**Verdict: Corroborated.** Jim Baker founded The Source restaurant.

### Not corroborated by independent web sources

#### Lead 1 — Richard Moon WORKED_AT The Source (kkron conf 0.75)

No independent web source connects a "Richard Moon" to The Source restaurant
or the Source Family. Source Family members took spiritual "Aquarian" names
(Isis, Electricity, Djin, Octavius, Sunflower, etc.); none match "Richard
Moon." The one Richard Moon who appears in search results as a cook is an
Australian chef in the Blue Mountains (1990s-2000s), clearly unrelated. Sky
Saxon (nee Richard Marsh) is the only "Richard" associated with the Source
Family, but his surname was Marsh, not Moon.

**Verdict: Not corroborated.** May reflect undocumented restaurant staff
from the 1960s-70s; the script correctly stores this as a pending claim at
capped confidence.

#### Lead 2 — Richard Moon WORKED_AT Aware Inn (kkron conf 0.75)

No independent web source connects "Richard Moon" to the Aware Inn. The
Aware Inn's staff is not documented in any of the sources found.

**Verdict: Not corroborated.** Same reasoning as Lead 1.

#### Lead 6 — Richard Moon WORKED_AT Wild Mountain Cafe (kkron conf 0.35)

No independent web source connects "Richard Moon" to any Wild Mountain Cafe.
The only Wild Mountain Cafe found is in Seattle (Ballard), opened 2002,
owned by Desirae Aylesworth — no Source Family / Father Yod / Jim Baker
connection. This matches kkron's own lower confidence (0.35).

**Verdict: Not corroborated.** Consistent with kkron's stated lower
certainty.

## Summary

| # | Lead | kkron conf | Independent corroboration |
|---|---|---|---|
| 1 | Richard Moon WORKED_AT The Source | 0.75 | None found |
| 2 | Richard Moon WORKED_AT Aware Inn | 0.75 | None found |
| 3 | Jim Baker FOUNDED Aware Inn | 0.7 | Strong (5+ sources) |
| 4 | Aware Inn PRECEDES The Source | 0.7 | Strong (5+ sources) |
| 5 | Jim Baker FOUNDED The Source | 0.85 | Strong (5+ sources) |
| 6 | Richard Moon WORKED_AT Wild Mountain Cafe | 0.35 | None found |

3 of 6 leads are strongly corroborated by multiple independent web sources.
3 of 6 leads (all Richard Moon leads) are not corroborated by any
independent web source found — this may reflect that restaurant staff from
the 1960s-70s are not well-documented online, not necessarily that the
claims are false. The script's design handles this correctly: kkron's claims
are stored at capped confidence (<= 0.5) with
`pending_independent_corroboration=True`, and the script does not fabricate
results.

## Technical notes

- The script's Phase 2 (web search + crawl + extraction via Gemini) was
  attempted with a `GEMINI_API_KEY` pulled from GCP Secret Manager
  (`quantum-aikido-coaching` project, secret `GEMINI_API_KEY`). Two issues
  were hit:
  1. **Model deprecation**: `gemini-2.5-flash` (the `.env` default) returns
     404 — Google requires `gemini-3.6-flash` for new users. Updated
     `GEMINI_MODEL` in `.env` accordingly.
  2. **Quota exhausted**: the key is on the free tier and hit its daily
     quota (429 RESOURCE_EXHAUSTED) on the first lead's search. Phase 1
     (storing kkron's claims) succeeded; Phase 2 could not complete today.
  The corroboration searches above were performed independently via web
  search tools using the same query strings the script would issue, and
  are not dependent on the Gemini quota.
- All 24 unit and integration tests pass.
- The script is idempotent: re-running `--skip-search` produces identical
  node/edge counts with no duplicates.
- The remote branch added 3 new leads (March 1971 meeting of Richard Moon,
  Father Yod, and Yogi Bhajan) since the initial validation; those leads
  are included in the script run but were not part of the original
  independent web search corroboration above.
