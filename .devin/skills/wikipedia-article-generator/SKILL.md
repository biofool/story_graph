# Wikipedia Article Generator (from Story Graph nodes about a person)

## When to use

Use when the user asks to "generate a Wikipedia article for X", "write a
Wikipedia page from the graph for X", "draft a Wikipedia biography from
story_graph data", or similar requests to turn the collected graph nodes,
edges, claims, and sources for a person into a Wikipedia-style article draft.

This skill is distinct from the existing `prompts/graph_to_wikipedia_update.md`
flow, which proposes *updates* to an existing Wikipedia article (Talk-page
proposals or direct edits). This skill generates a *full standalone article
draft* from scratch, using only the graph's own sourced data.

## What it does

1. **Collects** all graph data for a person from `graph_snapshot/` JSONL files
   — the canonical Person node, alias/duplicate Person nodes, Claim nodes,
   key relationship edges, and all ingested web sources with their
   `source_class`, `bias_hint`, platform, and URL.
2. **Scores every source** for Wikipedia reliability using a computable
   ranking system (the Source Reliability Score, described below) that
   correlates source trustworthiness to web domain ranking and Wikipedia's
   own perennial-source assessments.
3. **Filters** to only sources that meet Wikipedia's WP:RS (reliable sources)
   threshold — independent, secondary, editorially-overseen publications.
   Primary-first-person claims, comment threads, promotional material, and
   self-published sources are excluded from article text (but listed in the
   reliability report).
4. **Generates** a Wikipedia-style article draft with proper inline citations,
   neutral point of view, no original research, and confidence hedging
   proportional to the graph's own `confidence` / `stance` metadata.
5. **Outputs** the article draft, a reliability report (every source scored
   and classified), a citation list, and an excluded-sources list with
   reasons.

## The core principle: reliable 2nd-party reporting

Wikipedia is very particular about reliable **secondary** (2nd-party)
reporting. A Wikipedia article about a person must be built on:

- **Independent sources** — the source is not written by the subject, a
  family member, a business partner, an employee, or anyone with a
  financial/personal stake in how the subject is portrayed.
- **Secondary sources** — the source analyzes, summarizes, or reports on
  the subject at one remove (a journalist writing about the person, a book
  by a third-party author, an academic paper). A primary source (the
  person's own book, website, interview, or social media post) may
  corroborate a minor factual detail but cannot establish notability or
  carry the article's narrative.
- **Editorial oversight** — the source has a fact-checking / editorial
  process (a newspaper, a peer-reviewed journal, a published book from a
  reputable press). A blog post, a Reddit thread, a YouTube comment, or a
  self-published website does not.

The Source Reliability Score (SRS) below makes these criteria computable.

## Source Reliability Score (SRS) — computable ranking

Every source in the collected subgraph receives a composite score from 0
to 100. The score combines three computable inputs plus the graph's own
`source_class` field. Sources scoring >= 50 are **CITABLE**; sources below
50 are **NOT CITABLE** and may not appear as inline citations in the article.

### Input 1 — Domain rank tier (0–40 points)

A computable proxy for Google web ranking. The primary source is the
**Tranco list** (https://tranco-list.eu/), a free, daily-updated ranking
of the top 1 million web domains by traffic/visibility, built from Cisco
Umbrella and Alexa-style data. It is downloadable as a plain CSV
(`tranco_top_1m.csv`, one `rank,domain` per line) with no API key required.

If Tranco is unavailable, fall back to **Moz Domain Authority** (free API
tier, 0–100 scale) or **Ahrefs Domain Rating** if an API key is available.
If none are available, fall back to the hardcoded tier list in
`data/reference/domain_tiers.json` (see below).

| Tranco rank       | Points | Rationale                                    |
|-------------------|--------|----------------------------------------------|
| Top 1,000         | 40     | Major global destination (BBC, NYT, Wikipedia)|
| Top 10,000        | 30     | Established national/international outlet     |
| Top 100,000       | 20     | Recognized regional or niche-publication site |
| Top 1,000,000     | 10     | Minor site, some web presence                 |
| Not in top 1M     | 0      | No measurable web ranking                     |

The domain is extracted from the source's `url` field (via `urlparse`).
For archive URLs (`web.archive.org`, `archive.org`, `archive.is`), the
**original captured domain** is extracted from the URL path and scored
instead — the archive wrapper itself is transparent.

### Input 2 — WP:RSP status tier (-100 to +30 points)

Wikipedia maintains **Wikipedia:Reliable sources/Perennial sources**
(WP:RSP), a community-maintained list of source reliability assessments.
This is fetched via the Wikipedia API
(`https://en.wikipedia.org/w/api.php?action=parse&page=Wikipedia:Reliable_sources/Perennial_sources&prop=wikitext&format=json`)
and parsed for the source's domain. If the API call fails or the domain is
not listed, the source gets 0 from this input (unknown, not penalized).

A local cached copy is maintained at `data/reference/wikipedia_rsp.json`
(updated periodically by `scripts/32_refresh_wikipedia_rsp.py`) so the
scoring works offline.

| WP:RSP status              | Points | Meaning                                        |
|----------------------------|--------|------------------------------------------------|
| Generally reliable         | +30    | Editorial oversight, independent, accepted     |
| No consensus / varies      | +15    | Case-by-case; usable with justification        |
| Generally unreliable       | -50    | Fails WP:RS; do not cite                       |
| Deprecated / blacklisted   | -100   | Explicitly banned; never cite                  |
| Not listed                 | 0      | Unknown — rely on other inputs                 |

### Input 3 — source_class from the graph (−30 to +25 points)

The graph's own `source_class` field (from `src/storage/models.py:
SourceClass`) encodes the editorial nature of the source:

| source_class                | Points | Rationale                                     |
|-----------------------------|--------|-----------------------------------------------|
| `journalistic`              | +25    | News outlet with editorial oversight           |
| `archival`                  | +20    | Historical record, library/archive holding     |
| `documentary_promotional`  | -10    | Promotional bias; not independent              |
| `comment_thread`            | -30    | No editorial oversight (Reddit, forum, etc.)   |
| `primary_first_person`      | -20    | First-person account; not secondary            |
| (null / unknown)            | 0      | No signal from graph metadata                  |

### Input 4 — Independence adjustment (-20 to +10 points)

A source that is **independent** of the article subject gets +10. A source
affiliated with the subject (the subject's own website, a book by the
subject, a family member's blog, an organization the subject founded) gets
-20. Independence is determined by checking the source URL/domain against
the subject's known affiliations (extracted from the graph's
`MEMBER_OF` / `FOUNDED` / `WORKED_AT` edges and the subject node's
`source_urls`):

- If the source domain matches any domain in the subject's own
  `source_urls`, or matches an organization the subject founded/is a
  member of → **affiliated** (-20).
- Otherwise → **independent** (+10).

### Composite score and tiers

```
SRS = domain_rank_points + wp_rsp_points + source_class_points + independence_points
```

| SRS range  | Tier         | Citable? | Usage                                       |
|------------|--------------|----------|---------------------------------------------|
| >= 70      | RELIABLE     | Yes      | Full citation, normal encyclopedic confidence|
| 50–69      | MARGINAL     | Yes*     | Cite with explicit hedge ("according to…")   |
| 20–49      | WEAK         | No       | Listed in reliability report, not cited      |
| < 20       | UNRELIABLE   | No       | Listed in reliability report, not cited      |
| <= -50     | BLACKLISTED  | No       | Never cite; flagged in report                |

*MARGINAL sources are citable only if (a) the claim is also supported by at
least one RELIABLE source, or (b) the claim is a minor factual detail (a
date, a name spelling) that no RELIABLE source covers, and the marginal
source's WP:RSP status is "no consensus" (not "generally unreliable"). A
MARGINAL source alone can never establish notability or carry a contested
claim.

### Notability check (WP:GNG / WP:BIO)

Before generating the article, the skill checks whether the person meets
Wikipedia's **general notability guideline (WP:GNG)**: at least 2
independent, RELIABLE (SRS >= 70) secondary sources that provide
significant coverage (not just a passing mention). If this threshold is not
met, the skill outputs a **notability failure report** instead of an
article draft, listing what sources exist and what is missing.

### Hardcoded domain tier fallback

If Tranco / Moz / Ahrefs are all unavailable, the skill falls back to
`data/reference/domain_tiers.json`, a curated JSON file mapping known
domains to tier points. This file should be maintained as a simple
`{"domain": points}` lookup. Examples:

```json
{
  "en.wikipedia.org": 40,
  "nytimes.com": 40,
  "bbc.co.uk": 40,
  "latimes.com": 35,
  "proquest.com": 30,
  "laist.com": 30,
  "pbs.org": 35,
  "timesofindia.indiatimes.com": 30,
  "cultnews.com": 15,
  "grokipedia.com": 5,
  "alchetron.com": 0,
  "reddit.com": -30,
  "blogspot.com": -10,
  "wixsite.com": -10,
  "medium.com": 0
}
```

This file is a fallback only — the live Tranco ranking is preferred because
it is computable, objective, and updates automatically.

## Commands

```bash
# Dry run — collect subgraph, score all sources, print reliability report
# (no article generated yet)
python scripts/32_generate_wikipedia_article.py "sig kufferath" --dry-run

# Generate article draft to stdout
python scripts/32_generate_wikipedia_article.py "sig kufferath"

# Write article + reliability report to files
python scripts/32_generate_wikipedia_article.py "sig kufferath" \
    --article /tmp/article.md --report /tmp/reliability_report.md

# Use a specific Tranco list file (downloaded separately)
python scripts/32_generate_wikipedia_article.py "robert nadeau" \
    --tranco data/reference/tranco_top_1m.csv

# Force-refresh the WP:RSP cache before scoring
python scripts/32_generate_wikipedia_article.py "father yod" \
    --refresh-rsp

# Skip notability check (force article generation even if GNG not met)
python scripts/32_generate_wikipedia_article.py "isis aquarian" \
    --skip-notability-check
```

### Refreshing reference data

```bash
# Download the latest Tranco top-1M list (no API key needed)
curl -L -o data/reference/tranco_top_1m.csv \
    https://tranco-list.eu/top-1m.csv.zip && \
    unzip -o data/reference/tranco_top_1m.csv.zip -d data/reference/

# Refresh the WP:RSP cache from Wikipedia
python scripts/32_refresh_wikipedia_rsp.py
```

## Article generation rules

The article draft follows the same rigor as
`prompts/graph_to_wikipedia_update.md` (which this skill complements). Key
rules:

### Structure

A Wikipedia biography article follows this section order (omit sections
that have no citable content):

1. **Lead** — 2–4 sentences summarizing who the person is and why they are
   notable, every claim cited to a RELIABLE source.
2. **Early life and education** — if citable sources exist.
3. **Career** — the core of the article; organized chronologically or by
   major activity.
4. **Personal life** — only if citable and not WP:BLP-sensitive without
   strong sourcing.
5. **Legacy / reception** — how the person has been written about by others.
6. **References** — full citation list, Wikipedia ref-tag format.

### Sourcing rules

- **Every factual sentence carries an inline citation** to a CITABLE source
  (SRS >= 50). No citation, no sentence.
- **Only RELIABLE sources (SRS >= 70) establish notability, contested
  claims, or negative/controversial material.** MARGINAL sources may
  corroborate minor details only.
- **kkron personal-communication claims are NOT CITABLE** for article text.
  Per `AGENTS.md`, they are first-class evidence *in the graph* but they
  are `primary_first_person` sources — Wikipedia requires independent
  secondary reporting. They appear only in the reliability report's
  "Excluded sources" section, with a note that they exist in the graph but
  were deliberately excluded from the Wikipedia draft.
- **No original research (WP:NOR)** — do not synthesize, combine, or
  extrapolate beyond what a cited source states. If two claims don't share
  a source, do not connect them in the article's voice.
- **Neutral point of view (WP:NPOV)** — where `CONTRADICTS` edges or
  opposing claim stances exist, present all sides with attribution
  ("According to X… By contrast, Y's account states…").
- **Confidence hedging** — carry the graph's own `confidence` and `stance`
  into the prose: "suggests," "according to," "reports" for single-source
  or mid-confidence claims; unqualified assertions only for
  multiply-corroborated, high-confidence claims.
- **Never fabricate citations** — if a claim is CITATION PENDING (the graph
  knows a real publication exists but hasn't pinned down the exact
  title/author/URL), write `[citation needed]` and flag it in the
  reliability report. Never invent a plausible-sounding title, author, or
  URL.

### BLP sensitivity

If the person is living (or recently deceased), Wikipedia's
**Biographies of Living Persons (WP:BLP)** policy applies with extra
force:

- Controversial, negative, or potentially defamatory material requires
  **multiple** RELIABLE sources — a single MARGINAL source is never
  sufficient.
- Crime accusations require a source reporting a legal outcome (charge,
  conviction, acquittal) or a direct journalistic investigation — not a
  comment thread or blog post.
- The skill should flag BLP-sensitive claims in the reliability report and
  require explicit human review before including them in the draft.

## Output format

The skill produces two files (or stdout if no `--article` / `--report`
flags are given):

### 1. Article draft (`--article`)

Wikipedia wikitext-style markdown with inline citations:

```markdown
'''Sig Kufferath''' (1916–2007) was a German-born American aikido
teacher, credited as one of the earliest practitioners of aikido in the
United States.<ref name="laist">[url title]</ref>

== Career ==
...

== References ==
<references>
<ref name="laist">[url title, author, date]</ref>
...
</references>
```

### 2. Reliability report (`--report`)

```markdown
# Reliability Report: Sig Kufferath

## Notability check
- RELIABLE independent secondary sources with significant coverage: 3
  (LAist, Los Angeles Times, PBS SoCal)
- WP:GNG status: PASS

## Source scoring (all N sources in subgraph)

| # | Source | Domain | SRS | Tier | Citable? | Reason |
|---|--------|--------|-----|------|----------|--------|
| 1 | LAist  | laist.com | 85 | RELIABLE | Yes | Tranco #45K + WP:RSP reliable + journalistic + independent |
| 2 | Reddit thread | reddit.com | -20 | UNRELIABLE | No | Tranco #N/A + comment_thread + -30 |
| ... |

## Excluded sources (not cited in article)
- kkron personal-communication claims (N claims) — primary_first_person,
  excluded per WP:RS (requires independent secondary reporting). These
  remain first-class evidence in the Story Graph but are not citable in a
  Wikipedia article.
- [list each excluded source with reason]

## Citation-pending claims
- [list claims where the graph knows a publication exists but the exact
  citation hasn't been pinned down]
```

## Relationship to existing project components

- **`scripts/19_generate_data_ticket.py`** — collects the same subgraph
  (nodes, edges, sources, claims) but outputs a raw data dump for a GitHub
  issue. This skill reuses the same collection logic
  (`find_matching_nodes`, `select_canonical_person`, `collect_key_edges`,
  `collect_sources`) and adds the reliability scoring + article generation
  layer on top.
- **`prompts/graph_to_wikipedia_update.md`** — the existing Wikipedia
  prompt for *updating* an existing article (Talk-page proposals). This
  skill is for *generating* a new article from scratch. The two share the
  same sourcing rigor (CITABLE vs NOT CITABLE sort, WP:V/NOR/NPOV/RS
  enforcement, confidence hedging) but differ in output: a full article
  draft vs a Talk-page proposal.
- **`src/storage/models.py`** — the `SourceClass` enum and `SourceRecord`
  model define the `source_class` field used as Input 3 of the SRS.
- **`graph_snapshot/`** — the skill reads from the tracked JSONL snapshot
  (not the live SQLite DB), same as the data ticket generator, so the
  article reflects the committed, reviewable state of the graph.

## Notes

- The SRS is a heuristic, not an oracle. A high score does not guarantee a
  source is reliable for every claim (a tabloid with high traffic still
  fails WP:RS for controversial BLP claims). The WP:RSP input catches
  known-unreliable high-traffic domains (e.g. the Daily Mail, deprecated
  by Wikipedia despite high traffic). When WP:RSP and domain rank
  disagree, **WP:RSP wins** — that is why a "deprecated" status scores
  -100, enough to override any domain-rank bonus.
- The Tranco list is a proxy for Google ranking, not Google ranking itself.
  Google no longer publishes PageRank. Tranco's traffic-based ranking
  correlates strongly with search visibility and is the best free,
  computable, keyless proxy available. If the user has access to a Moz /
  Ahrefs / Similarweb API key, the script should prefer that for a more
  direct authority metric.
- The skill does not post anything to Wikipedia. It produces a draft for
  human review. Posting to Wikipedia requires a registered editor account,
  COI disclosure, and community review — all of which are outside this
  skill's scope.
- The skill reads from `graph_snapshot/` (committed JSONL), not the live
  SQLite DB, so the article reflects the reviewable state of the graph.
- kkron assertions are never used as article sources (they are
  `primary_first_person`), but they are always listed in the reliability
  report's excluded-sources section so the human reviewer knows what graph
  evidence exists but was deliberately excluded from the Wikipedia draft.
