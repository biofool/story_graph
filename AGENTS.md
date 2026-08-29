# Story Graph — Agent Notes

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
