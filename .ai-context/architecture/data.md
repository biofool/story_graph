# Data Architecture

## SQLite Schema (OBSERVED)

Source: `src/storage/graph_db.py:SCHEMA_SQL` (lines 26-71)

### Tables

#### `nodes`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PRIMARY KEY | Format: `{type}:{slug}` (e.g. `person:james-edward-baker`) |
| `type` | TEXT NOT NULL | One of: Person, Group, Place, Work, Event, Claim |
| `label` | TEXT NOT NULL | Display name |
| `canonical_name` | TEXT | Normalized canonical name (nullable) |
| `metadata_json` | TEXT DEFAULT '{}' | JSON blob for type-specific fields |
| `source_urls_json` | TEXT DEFAULT '[]' | JSON array of source URLs |

Indexes: `idx_nodes_type`, `idx_nodes_canonical_name`

#### `edges`
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | Auto-generated |
| `src_id` | TEXT NOT NULL | FK to nodes.id (not enforced) |
| `rel_type` | TEXT NOT NULL | One of 16 RelationType enum values |
| `dst_id` | TEXT NOT NULL | FK to nodes.id (not enforced) |
| `metadata_json` | TEXT DEFAULT '{}' | JSON blob |

Constraint: `UNIQUE(src_id, rel_type, dst_id)` — duplicate edges silently ignored.

Indexes: `idx_edges_src`, `idx_edges_dst`, `idx_edges_rel`

#### `sources`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PRIMARY KEY | Same as Work node ID (`work:{hash}`) |
| `url` | TEXT UNIQUE NOT NULL | Crawled URL |
| `title` | TEXT | Page title |
| `author` | TEXT | Extracted from meta tags |
| `publish_date` | TEXT | Extracted from meta tags |
| `platform` | TEXT | Domain name |
| `raw_text` | TEXT | First 50K chars of cleaned page text |
| `source_class` | TEXT | SourceClass enum value |
| `bias_hint` | TEXT | BiasHint enum value |

Index: `idx_sources_url`

#### `claim_sources`
| Column | Type | Notes |
|---|---|---|
| `claim_id` | TEXT NOT NULL | FK to nodes.id (Claim type) |
| `source_id` | TEXT NOT NULL | FK to sources.id |
| `quote_span_start` | INTEGER | Optional |
| `quote_span_end` | INTEGER | Optional |

Constraint: `PRIMARY KEY (claim_id, source_id)`

## Node Types (OBSERVED)

Source: `src/storage/models.py:NodeType` (lines 13-19)

| Type | ID Format | Key Metadata Fields |
|---|---|---|
| Person | `person:{slug}` | `aliases[]`, `extraction_source`, `roles[]` |
| Group | `group:{slug}` | (varies) |
| Place | `place:{slug}` | (varies) |
| Work | `work:{hash16}` | `url`, `publish_date`, `author`, `platform`, `work_type` |
| Event | `event:{slug}` | `event_type`, `start_date`, `end_date`, `description` |
| Claim | `claim:{hash16}` | `claim_text`, `claim_type`, `stance`, `confidence`, `evidence_mode` |

## Relation Types (OBSERVED)

Source: `src/storage/models.py:RelationType` (lines 22-38)

16 relation types: `ALIAS_OF`, `FOUNDED`, `MEMBER_OF`, `WORKED_AT`,
`LIVED_AT`, `CREATED`, `PUBLISHED_AT`, `DESCRIBES`, `ABOUT`,
`ASSERTED_BY`, `CONTRADICTS`, `SUPPORTED_BY`, `LOCATED_IN`, `PRECEDES`,
`MENTIONS`, `CONTAINS`.

## Controlled Vocabularies (OBSERVED)

| Enum | Values | Source |
|---|---|---|
| `ClaimStance` | critical, supportive, neutral, self-mythologizing | `models.py:41-45` |
| `ClaimType` | biographical, abuse_allegation, financial_control, sexual_control, documentary_critique, historical_dispute | `models.py:48-55` |
| `EvidenceMode` | first_person, archival_clipping, commentary, audio_tape_summary, secondary_report | `models.py:58-63` |
| `SourceClass` | primary_first_person, archival, journalistic, documentary_promotional, comment_thread | `models.py:66-71` |
| `BiasHint` | hostile, defensive, nostalgic, neutral_ish | `models.py:74-78` |

## Persistence Behavior

- **Upsert by ID:** `add_node()` merges metadata and source_urls on
  conflict. `add_source()` uses `COALESCE` to fill nulls.
- **Edge dedup:** `add_edge()` uses `INSERT OR IGNORE` — duplicate
  (src, rel, dst) triples are silently dropped.
- **No migrations:** Schema is `CREATE TABLE IF NOT EXISTS` — additive
  only. No ALTER TABLE, no migration framework.
- **No foreign key enforcement:** `src_id`/`dst_id` in edges are not
  FK-constrained to `nodes.id`. Orphan edges are possible.
- **No transactions across operations:** Each `add_node`/`add_edge`/
  `add_source` commits individually. No batch transaction support.
