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
