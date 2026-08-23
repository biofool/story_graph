# Workflow: Contradiction Detection + Timeline

**Entry Point:** `ContradictionDetector(db)` — called from
`scripts/01_crawl_and_build_graph.py` Phase 3.
**Not a standalone CLI** — invoked programmatically after extraction.

## Execution Path (OBSERVED, ordered)

### Step 1: Infer Implicit Targets
`detector.infer_implicit_targets()`

1. Get all Claim nodes from DB
2. For each claim with no existing ABOUT edges:
   a. Find source works (edges where `work -[CONTAINS]-> claim`)
   b. For each source work, get its MENTIONS edges
   c. For each MENTIONS target of type PERSON or GROUP (not PLACE):
      add `claim -[ABOUT]-> target` edge with `metadata={"inferred": True}`
3. Return count of edges added

**Purpose:** Claims often refer to subjects by pronoun or omit them
entirely. This heuristic inherits the source work's mentioned
persons/groups as implicit claim targets, materially improving
contradiction recall.

### Step 2: Detect Contradictions
`detector.detect_contradictions()`

1. Get all Claim nodes
2. Build map: `target_node_id → list[(claim_id, stance)]` from ABOUT edges
3. For each target, check all claim pairs:
   a. Skip if same claim or already checked (i >= j)
   b. If `(stance1, stance2)` in `CONTRADICTORY_STANCE_PAIRS`:
      - Dedup across targets (frozenset of claim IDs)
      - Add `CONTRADICTS` edge: `claim1 -[CONTRADICTS]-> claim2`
      - Record `(claim_id_1, claim_id_2)` pair
4. Return list of contradicting claim pairs

**Contradictory stance pairs (OBSERVED):**
- (critical, supportive) and reverse
- (critical, self-mythologizing) and reverse
- Neutral is never contradictory with anything.

### Step 3: Build Timeline Edges
`detector.build_timeline_edges()`

1. Get all Event nodes
2. Extract `start_date` from each event's metadata
3. Sort dated events by date (string comparison)
4. For each pair where `date1 < date2`:
   - Add `event1 -[PRECEDES]-> event2` edge
5. Return list of (event_id_1, event_id_2) pairs

**Note:** Uses string comparison for dates (ISO format YYYY-MM-DD sorts
correctly). Non-ISO date strings would sort incorrectly.

## Evidence

| Step | Path | Symbol |
|---|---|---|
| Implicit targets | `src/extractor/contradiction_detector.py` | `infer_implicit_targets()` |
| Contradictions | `src/extractor/contradiction_detector.py` | `detect_contradictions()` |
| Timeline | `src/extractor/contradiction_detector.py` | `build_timeline_edges()` |
| Stance pairs | `src/extractor/contradiction_detector.py` | `CONTRADICTORY_STANCE_PAIRS` |
| Inheritable types | `src/extractor/contradiction_detector.py` | `_INHERITABLE_TARGET_TYPES` |

## Failure Paths

| Failure | Behavior |
|---|---|
| No claims in DB | Returns empty lists, logs info |
| No ABOUT edges on claims | `infer_implicit_targets` adds them; without source works, claims remain untargeted |
| No dated events | `build_timeline_edges` returns empty |
| Non-ISO date strings | String comparison may produce incorrect ordering (DEBT-005) |

## Change Guidance

- **Adding new contradictory stance pairs:** Update
  `CONTRADICTORY_STANCE_PAIRS` set. Add test in
  `test_contradiction_detector.py`.
- **Changing inheritable target types:** Update
  `_INHERITABLE_TARGET_TYPES`. Currently only PERSON and GROUP — adding
  PLACE would tag every claim as about every place mentioned (avoided
  by design).
- **Date comparison logic:** Currently string-based. If non-ISO dates
  are possible, consider `datetime` parsing with fallback.
- **This detector mutates the DB:** All three methods add edges. Running
  twice on the same DB is safe (INSERT OR IGNORE for edges), but
  `infer_implicit_targets` checks for existing ABOUT edges to skip
  already-targeted claims.
