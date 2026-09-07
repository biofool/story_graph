# Data Ticket Generator

## When to use

Use when the user asks to "post data to a ticket", "create a data ticket",
"dump graph data to GitHub", "file a ticket with all data on X", or similar
requests to compile all Story Graph data for an entity into a GitHub issue.

## What it does

Runs `scripts/19_generate_data_ticket.py` which:
1. Reads `graph_snapshot/` JSONL files (nodes, edges, sources, claim_sources)
2. Finds all nodes matching the entity name (case-insensitive, matches label/id/canonical_name/source_urls)
3. Selects the canonical Person node (most source_urls)
4. Collects alias/duplicate Person nodes
5. Collects kkron personal-communication claims (uses surname matching for broader coverage)
6. Collects key relationship edges (FOUNDED, MEMBER_OF, WORKED_AT, etc.)
7. Collects ingested web sources with URLs and summaries
8. Generates a structured markdown ticket body
9. Optionally posts to GitHub via `gh issue create`

## Commands

```bash
# Dry run (see what would be included)
python scripts/19_generate_data_ticket.py "sig kufferath" --dry-run

# Output to stdout (review before posting)
python scripts/19_generate_data_ticket.py "sig kufferath"

# Write to file
python scripts/19_generate_data_ticket.py "sig kufferath" -o /tmp/ticket.md

# Post directly to GitHub
python scripts/19_generate_data_ticket.py "sig kufferath" --post \
    --title "Sig Kufferath: complete graph data dump"

# Custom repo and labels
python scripts/19_generate_data_ticket.py "robert nadeau" --post \
    --repo biofool/story_graph --label enhancement --label documentation
```

## Default repo

`biofool/story_graph` (override with `--repo`)

## Default labels

`enhancement` (override with `--label`, repeatable)

## Notes

- Reads from `graph_snapshot/` (committed JSONL), not the live SQLite DB, so
  the ticket reflects the reviewable state of the graph.
- The search is case-insensitive and matches against node labels, IDs,
  canonical names, and source URLs.
- kkron claim matching uses the surname (last word of the search term) in
  addition to the full name, since many claims reference only the surname.
- The canonical Person node is selected as the one with the most source_urls.
- Non-Person node types (Claim, Event, Image, Work, Place, Group) are also
  included in the ticket if they match the search term.
- The script flags data-quality issues (duplicate nodes, wrong edge types)
  in the generated ticket body.
