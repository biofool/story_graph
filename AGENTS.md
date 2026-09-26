# Story Graph — Agent Notes

## Ingests are JSON specs, not scripts (default behavior)

Do NOT write new numbered `scripts/NN_ingest_*.py` one-off scripts.
Declare the ingest as a JSON spec in `data/ingest/<name>.json` and apply
it with `python scripts/ingest.py data/ingest/<name>.json`
(`--dry-run` first). Spec keys: `pages` (fetch + `process_page`),
`nodes`, `edges`, `sources`, `claim_sources`, `delete_edges`,
`csv_events` (structured seminar-calendar rows). All historical one-off
ingest scripts were migrated to specs (each spec records
`migrated_from`); `scripts/migrate_ingests.py` captures a legacy script's
writes into a spec if one ever needs converting again.

Only keep parameterized/reusable tooling as scripts (e.g.
`ingest_a_person.py`, `17_ingest_from_kv.py`, `48_ingest_aikiweb_seminars.py`,
`11_ingest_cdnc.py`).

`scripts/ingest_news_feeds.py` runs daily via GitHub Actions
(`.github/workflows/news_ingest.yml`, issue #78) and commits
`graph_snapshot/` diffs back itself — it also refreshes
`data/audit/reingest_candidates.json` via `scripts/reingest_audit.py`,
the standing report of graph areas worth reingesting when algorithms
improve.

## kkron's assertions always go in the graph

Always add kkron's assertions (claims, evidence, verbal confirmations,
personal communications, interview notes) to the graph by default. They
are first-class evidence in this project — kkron is the project owner and
a primary source.

The only exception: kkron explicitly marks an assertion or node as
"not connected" (the `metadata.not_connected = True` flag, set via the
`/api/node/<id>/mark_not_connected` endpoint or the "Mark as not
connected" button in the graph viewer UI). Until kkron does that, treat
every kkron assertion as connected to the core graph and contributing to
claim confidence/veracity.

Do not silently drop, skip, or deprioritize kkron assertions during
ingest, enrichment, or deduplication. If a kkron assertion conflicts with
another source, record both — the graph stores "who said what" rather
than declaring one canonical truth.

### Source identifiers for kkron assertions

- Platform: `kkron (personal communication)`
- Source class: `verbal_confirmation` / `recorded_interview` (as appropriate)
- URL scheme: `kkron://personal-communication`, `kkron://interview/<slug>`

(See commit `ac8a894` for the fix that stopped polluting entity
`source_urls` with `kkron://personal-communication` — that was a separate
bug about edge source attribution, not about excluding kkron assertions.)

## Wikipedia workflow — local drafts only, editor persona for review

Wikipedia output is always a local draft/proposal — never posted to or
edited on the live site. Pipeline: `prompts/graph_to_wikipedia_update.md`
(update proposals, talk_page/direct_edit modes, COI rules),
`scripts/32_generate_wikipedia_article.py` (graph → draft + SRS report),
`scripts/57_fetch_wikipedia_article.py` + `scripts/58_compare_wikipedia_draft.py`
(live fetch + mechanical deltas). For editorial review, drafting, and
source adjudication of Wikipedia content, adopt the persona in
`.devin/skills/martial-arts-journal-editor/SKILL.md` (authoritative
martial-arts journalist + Wikipedia policy expertise). Sourcing rules,
SRS tiers, and martial-arts source guidance live in
`.devin/skills/wikipedia-article-generator/SKILL.md`.

If a source page is repeatedly blocked (HTTP 429, paywall, bot wall),
record the URL in the relevant Wikipedia tracking issue (e.g. #70) so the
blocked pages stay visible and retriable — do not let them disappear into
script logs.

## Facebook browsing — persistent Chrome profile (WSF technique)

Direct Facebook browsing uses `scripts/59_facebook_browser_fetch.py` —
ported from WorldStudioFinder `scripts/acquire_fb_browser.py`. Anonymous
HTTP fetches of facebook.com (desktop and m.*) all redirect to login;
browsing runs headed Chrome with a dedicated persistent profile at
`data/cache/fb_chrome_profile`. On a login wall the script leaves the
browser open and polls up to 600s for a manual login; the session then
persists across runs. A previously exported Playwright `storage_state`
JSON can seed cookies via `--storage-state` (e.g. WSF's
`data/cache/fb_storage_state.json`). Fetched pages land under
`data/reference/facebook/<slug>/` as raw HTML + extracted text — review
first, then ingest via `data/ingest/*.json` specs. `FB_ACCESS_TOKEN`
(Graph API path in `scripts/03_facebook_research.py`) is not configured.
