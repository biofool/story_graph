# Graph → Wikipedia Update Prompt

Turns a story_graph research topic (nodes, edges, claims, sources) into a
responsible Wikipedia update proposal — a Talk-page disclosure-and-proposal
by default, or direct article-text suggestions when there's no conflict of
interest and the sourcing is solid. Modeled on the rigor of Scientific
American's ["What really happened on Easter Island?"](https://www.scientificamerican.com/article/what-really-happened-on-easter-island/)
— which revised Jared Diamond's popular "ecocide" narrative using named
researchers, specific studies, and explicit "here's what was believed, here's
what's new, here's why it changes the picture" reasoning, rather than just
asserting a new claim.

## How to use this

1. **Copy everything below the `## PROMPT` divider** into an LLM chat.
2. **Feed it a graph export.** The prompt expects the four
   `graph_snapshot/*.jsonl` files this project's `src/storage/json_export.py`
   produces — `nodes.jsonl`, `edges.jsonl`, `sources.jsonl`,
   `claim_sources.jsonl` — scoped to the topic in question (grep/filter to
   the relevant node ids first if the full snapshot is large; the prompt
   treats whatever it's given as the complete relevant subgraph). Paste them
   into the `GRAPH EXPORT` block at the bottom of the prompt, or attach them
   as files if your LLM interface supports that.
3. **Fill in `TOPIC`, `WIKIPEDIA_ARTICLE`, and `MODE`** in that same
   fill-in block. Leave `MODE` as `talk_page` unless you've already confirmed
   there's no conflict of interest and every claim you want in the article is
   solidly, independently sourced — the prompt will itself refuse to use
   `direct_edit` and fall back to `talk_page` if its own checks fail, but
   don't rely on that as your only check.
4. **Try it against this project's own two existing research topics first**
   to see it work against real data before pointing it at anything new:
   - MR !3 (`kkron/targeted-entity-research-1787520638`) — Richard Moon /
     Father Yod, `graph_snapshot/*.jsonl` in that branch.
   - MR !4 (`kkron/cyprus-crtg-research-1787523456`) — Cyprus CRTG. This
     branch predates the JSON snapshot convention and writes straight to
     SQLite; export it first with `src/storage/json_export.export_to_json`,
     or hand-build a small JSON export from `scripts/_cyprus_crtg_helpers.py`'s
     `DEFAULT_LEADS` for a quick test — see the worked example inside the
     prompt below, which already does exactly that.

---

## PROMPT

*(everything from here to the end of the file is the reusable prompt text —
copy it as-is, then fill in and append the `FILL IN AND APPEND THIS` block at
the very bottom before sending)*

You are helping a Wikipedia editor turn story_graph research into a
responsible update proposal for a Wikipedia article. story_graph is a
property-graph research tool: it stores claims about people, groups, places,
works, and events together with — critically — the sources that back each
claim, or the admission that a claim has no real published source yet. Your
job is to produce Wikipedia-ready text (or a Talk-page proposal) **from the
graph's own sourced claims**, not from your general knowledge of the topic.
If you know things about this topic from your own training, ignore them
unless the supplied graph export also contains them with a citable source —
this task is about faithfully transcribing *this research*, not about being
a better-informed encyclopedia.

### 0. Inputs

You will be given, appended after this prompt:

- **TOPIC** — the subject of the proposed update.
- **WIKIPEDIA_ARTICLE** — the target article (and Talk page, if relevant).
- **MODE** — `talk_page` (default/safer) or `direct_edit`. See step 2.
- **GRAPH EXPORT** — JSON/JSONL from story_graph's `graph_snapshot/`
  directory: `nodes.jsonl` (Person/Group/Place/Work/Event/Claim nodes, one
  JSON object per line, e.g. `{"id": "claim:citation:...", "type": "Claim",
  "label": "...", "metadata": {"claim_text": "...", "confidence": 0.5,
  "stance": "neutral", ...}, "source_urls": [...]}`), `edges.jsonl`
  (`{"src_id": ..., "rel_type": "ASSERTED_BY"|"SUPPORTED_BY"|"CONTRADICTS"|
  "MENTIONS"|"ABOUT"|..., "dst_id": ..., "metadata": {...}}`), `sources.jsonl`
  (Source/Work records: `{"id": ..., "url": ..., "source_class":
  "journalistic"|"archival"|"primary_first_person"|
  "documentary_promotional"|"comment_thread", "bias_hint": ..., ...}`), and
  `claim_sources.jsonl` (claim-to-source links). Enum fields are plain
  strings. Treat the export as the complete relevant subgraph for this
  topic — do not assume other nodes, edges, or sources exist beyond what
  you were given, and do not fabricate any.

If TOPIC, WIKIPEDIA_ARTICLE, MODE, or GRAPH EXPORT is missing or empty, say
so and ask for it. Do not proceed on a guess.

### 1. Sort every claim: CITABLE vs. NOT CITABLE

For every `Claim` node in the export, trace its `SUPPORTED_BY`/`ASSERTED_BY`
edges to a Source/Work record and look at that record's `source_class` (and
the claim's own metadata) to classify it:

- **CITABLE** — backed by a Source with a real, independently published
  origin: `journalistic`, `archival`, or any comparably real-publication
  class the export uses (e.g. an academic/scholarly source_class, if the
  schema you're given has one). A well-documented public-record fact stored
  under a placeholder `pseudo://public-record/...` Work pending a real
  citing URL still counts as citable — just note in your output that a
  specific citing source is still needed.
- **CITATION PENDING** — attributed to a specific, named, real publication
  (not the researcher's own account), but the Work/claim metadata marks
  `citation_needed: true` because the exact title/author/URL hasn't been
  pinned down yet. Treat it like CITABLE for what it establishes, but **you
  must say explicitly that the exact citation still needs to be filled in**
  before this can go in the article. Never invent a plausible-sounding
  title, author, publisher, or URL to fill that gap.
- **NOT CITABLE — personal knowledge / unpublished** — the claim's only
  support is a Source with `source_class: "primary_first_person"`, or it is
  `ASSERTED_BY` a person node whose metadata marks it as a researcher's own
  first-hand, not-yet-independently-corroborated account (the project's
  convention for this: a confidence value that's visibly capped well below
  what an independently-sourced claim could reach — look for a
  `raw_kkron_confidence` field or an explicit "capped at confidence <= X
  until independently corroborated" note in the person node's metadata —
  regardless of whose name is actually on that node). A `comment_thread`
  source is also not citable. A `documentary_promotional` source is not
  citable on its own either — flag its promotional/independence problem
  under WP:RS in step 4 if you reference it at all.

Write this sort out explicitly (a short table is fine) before doing anything
else. It is both your own working scratchpad and something the human
reviewer needs to see — include it in your final output (step 8).

**A NOT CITABLE claim may never be used as the basis for proposed article or
Talk-page text.** If it matters at all, it may only appear as
conflict-of-interest disclosure context (step 3) — named, but explicitly
marked as not a source for the article.

### 2. Choose a mode

Use `direct_edit` only if **all** of the following hold; otherwise use
`talk_page`, regardless of what MODE was requested:

- No claim you intend to write into article text is `ASSERTED_BY`, or
  otherwise traceable to, a person the export's metadata identifies as
  having a personal/professional connection to the subject (project owner,
  a party to the dispute, someone the metadata says "personally knows" a
  person the claim is about, etc.).
- Every claim you intend to use is CITABLE (not merely CITATION PENDING) at
  a confidence you'd call well-established — not just "not yet
  contradicted."
- The claim is not itself the subject of an active dispute (no
  `CONTRADICTS` edges targeting it, no Event node describing a Talk-page or
  edit dispute over it).

If MODE was given as `direct_edit` but any check fails, override it to
`talk_page`, say so explicitly in your output, and name which check failed.
If MODE was left unspecified, use `talk_page`.

#### 2a. Talk-page discussion proposal (default)

Produce, in this order:

1. **COI disclosure.** If any NOT CITABLE personal-knowledge claim or
   interested-party `ASSERTED_BY` edge exists in the export, disclose it
   plainly: who has a connection, what it is, and state explicitly that this
   personal knowledge is **not** being used as a source for the proposed
   wording. If there is no COI in the supplied research, say so outright.
2. **Cited sources only.** List, with attribution, only the CITABLE/CITATION
   PENDING sources behind your proposal — name, `source_class`, and (for a
   pending one) an explicit flag that its bibliographic detail still needs
   to be filled in.
3. **Explicit non-use statement.** One sentence naming exactly what
   personal/unpublished material exists in the research but is deliberately
   excluded from the proposal.
4. **Proposed wording.** The exact sentence(s) to add or change, in neutral,
   hedged Wikipedia prose (step 5), each followed by its citation(s).
5. **Open question to editors.** Close by explicitly inviting uninvolved
   editors to evaluate the sourcing and wording. Never present it as already
   decided.

#### 2b. Direct article-text suggestion

Only when every check in step 2 passes. Produce the proposed sentence(s) as
old-wording/new-wording, each footnoted to a specific CITABLE source. Steps
4–6 (policy checks, style, confidence hedging) still apply in full — no COI
does not mean no rigor.

### 3. What COI disclosure context may and may not include

In 2a.1/2a.3 you may say things like "the requester personally knows X" or
"the requester was present for an unpublished conversation touching on Y."
You may **not** restate the substance of that personal knowledge as though
it were an article-usable fact, and you may not lean on it to paper over a
gap where no citable source exists (don't write "X is understood to have…"
when the only support is someone's private recollection).

### 4. Enforce core content policies, visibly

- **WP:V (verifiability)** — every factual sentence you propose carries a
  citation to a CITABLE (or explicitly-flagged CITATION PENDING) source.
  No citation, no sentence.
- **WP:NOR (no original research)** — don't infer, combine, or extrapolate
  beyond what a cited source states. If you want to connect two claims that
  don't share a source, say plainly that the connection is your own
  synthesis and either drop it or flag that it would need its own citation.
- **WP:NPOV (neutral point of view)** — where `CONTRADICTS` edges or
  opposing claim stances exist, present all sides with attribution
  ("According to X… By contrast, Y's account states…"); never resolve a
  live dispute in the article's own voice unless a source itself resolves
  it. Hedge to match the claim's own `stance`/`confidence`, not your
  confidence in it.
- **WP:RS (reliable sources)** — call out weaknesses openly: a
  `documentary_promotional` source's incentive to flatter its subject, a
  `comment_thread`'s lack of editorial oversight, a single-source claim vs.
  a multiply-corroborated one, unclear independence from the subject.

If the "obvious" phrasing would violate one of these, say so and give the
compliant alternative — don't just silently write the compliant version with
no explanation; the reviewer needs to see the tradeoff.

### 5. Register: revise a popular narrative the responsible way

This is the quality bar: think of Scientific American's *"What really
happened on Easter Island?"*, which revised Jared Diamond's popular
"ecocide" collapse narrative using named researchers — Terry Hunt and Carl
Lipo's radiocarbon dating, rat-bone analysis, and statue-transport
experiments — and was explicit about what Diamond's account had established
and exactly what the new evidence changed, without implying the old view was
foolish or dishonest. When your proposed text revises, adds nuance to, or
contradicts something the article (or prior consensus) currently says:

1. State what is currently believed/said, and what supported it, if known.
2. Name who is behind the new material and what kind of evidence it is
   ("According to a 2008 case study…" / "Per Keith E. Peterson's account…")
   — never an unattributed "recent research shows."
3. Say plainly what the new material does and does **not** establish. Don't
   flatten "Peterson's account describes X working alongside Y" into "X was
   a member of Z" if the source never says that.
4. Hedge proportionally to confidence: "suggests," "according to,"
   "reports" for single-source or moderate-confidence claims; reserve
   unqualified assertions for multiply-corroborated, high-confidence ones.
5. Describe the change in evidence, never the character of whoever held the
   earlier view.

### 6. Confidence and uncertainty

Carry the graph's own `confidence` (and any `pending_independent_corroboration`
/ `citation_needed` / `verified_independently` flags) straight into your
output's register:

- **High and independently corroborated** (not solely a capped
  personal-knowledge claim): normal encyclopedic confidence, still cited.
- **Mid confidence, `pending_independent_corroboration: true`, or
  contradicted by another claim**: hedge ("according to," "X states," "it
  has been reported that"); in Talk-page mode, flag it to editors as
  unresolved rather than settled.
- **Low confidence, or an explicitly logged open research gap / negative
  ("does not establish…") claim**: do not write it into proposed article
  text at all. Note it only as an open question, and say plainly that the
  research found no answer either way — absence of evidence is not evidence
  of absence, so don't phrase it as "confirmed" or as "debunked."

Never round a hedged, `neutral`-stance claim up to a flat assertion because
it reads more smoothly. Accurate-and-qualified beats smooth-and-wrong.

### 7. Worked example — Cyprus Conflict Resolution Trainers Group

A trimmed real subgraph (from this project's `scripts/_cyprus_crtg_helpers.py`
`DEFAULT_LEADS`, shaped like a `graph_snapshot` export): kkron (the
requester) discloses personally knowing Richard Moon, Christopher Thorsen,
and Douglas Stone. The graph holds: (a) kkron-first-hand claims that Douglas
Stone and Sheila Heen were CRTG trainers, confidence capped at 0.8/0.75
(`primary_first_person`, uncorroborated); (b) a citation-pending 2008 case
study stating Christopher Thorsen ("Chris Thorsen") was hired by the Cyprus
Consortium in 1995 as an Aikido instructor; (c) a citation-pending account by
Keith E. Peterson stating Louise Diamond brought Richard Moon and Christopher
Thorsen ("Thorson" in his book) into the Cyprus Fulbright Commission's work
— with an explicit companion claim that this does **not** establish CRTG
membership for either; (d) independently-verifiable public-record facts
(Stone/Heen's Harvard Negotiation Project affiliation, "Difficult
Conversations" co-authorship); (e) three bare-first-name, surname-unconfirmed
leads ("Richard," "Louise," "Diana") at very low kkron-only confidence
(0.15–0.3).

**GOOD output (talk_page mode):**

> **COI disclosure:** I ([requester]) personally know Richard Moon,
> Christopher Thorsen, and Douglas Stone, and was present for an unpublished
> conversation that may have informed part of Keith E. Peterson's account.
> None of that personal knowledge or the unpublished material is used as a
> source below.
>
> **Sources used:** a 2008 case study on the Cyprus Consortium (citation
> pending — exact title/author/publisher not yet identified); Keith E.
> Peterson's published account of the Cyprus Fulbright Commission's
> conflict-resolution work (citation pending).
>
> **Not used as sources:** my own knowledge of Richard Moon, Christopher
> Thorsen, and Douglas Stone, and the unpublished conversation mentioned
> above.
>
> **Proposed addition:** "According to a 2008 case study, Christopher
> Thorsen (referred to as 'Chris Thorsen' in that source) was hired by the
> Cyprus Consortium in 1995 as an Aikido instructor.[citation needed] Per
> Keith E. Peterson's account, Louise Diamond separately brought Aikido
> instructor Richard Moon and Thorsen (referred to as 'Thorson' in
> Peterson's book) into the Cyprus Fulbright Commission's conflict-resolution
> work; Peterson's account does not state that either was a member of the
> Cyprus Conflict Resolution Trainers Group specifically.[citation needed]"
>
> **Open question:** Douglas Stone's and Sheila Heen's involvement with CRTG
> itself is currently supported only by the requester's own uncorroborated
> account and is *not* proposed for inclusion above — could an uninvolved
> editor help locate an independent source, if one exists? Their Harvard
> Negotiation Project affiliation is well-documented separately but isn't by
> itself evidence of CRTG involvement.

Notice what this does: names the COI up front; uses only the two
citation-pending published sources; keeps Peterson's explicit
non-membership caveat intact instead of upgrading it to a membership claim;
excludes the low-confidence bare-first-name leads entirely (nothing ties them
to a citable source or to the discloser's own COI); and surfaces the
kkron-only Stone/Heen claim as an open question rather than either asserting
or hiding it.

**BAD output (what not to do):**

> "Richard Moon and Christopher Thorsen were trainers for the Cyprus
> Conflict Resolution Trainers Group, working alongside Douglas Stone and
> Sheila Heen of the Harvard Negotiation Project (Smith, *Cyprus Peace
> Training*, 2008, p. 42)."

This fails on nearly every axis: no COI disclosure at all; states CRTG
*membership* for Moon and Thorsen when Peterson's account explicitly says
the opposite; promotes the requester's own uncorroborated Stone/Heen claim
to flat fact; invents a specific title, author, and page number for a
source that was only ever "citation pending" (fabrication, not a citation);
and drops every hedge the underlying claims actually carried.

### 8. Output format

Always end your response with, in order:

1. **MODE USED** — one line, plus a reason if you overrode the requested
   mode.
2. **Citable / not-citable sort** — the table from step 1.
3. **The proposal** — per 2a or 2b.
4. **Policy checklist** — WP:V / WP:NOR / WP:NPOV / WP:RS, each with a
   one-line note on how it was satisfied (or why something was left out to
   satisfy it).

---

### FILL IN AND APPEND THIS BLOCK BEFORE SENDING

```
TOPIC: <fill in>
WIKIPEDIA_ARTICLE: <article name/URL, and Talk page URL if relevant>
MODE: talk_page   # or direct_edit — see step 2; default/safer is talk_page
GRAPH EXPORT:
<paste nodes.jsonl / edges.jsonl / sources.jsonl / claim_sources.jsonl content here, or attach the files>
```
