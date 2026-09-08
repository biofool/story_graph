# Aikido Lineage Graph — Production Implementation Plan

> **Status**: Design document, ready for implementation agent handoff
> **Ground truth**: Research from commits `d8afe9e`, `47b6f88`, `f2634fe` (Nadeau/Millman/Moon/Noha cluster + Peter Ralston)
> **Existing infrastructure**: Story Graph (`~/projects/github/story_graph`), WorldStudioFinder dojo data (`~/projects/github/WorldStudioFinder`)

---

## Part 1 — Graph / Relational Schema Design

### 1.1 Design principles

- **Dual representation**: property-graph (nodes/edges) for traversal + relational tables for analytics/BI
- **Provenance first**: every node and edge carries `source_urls`, `discovered_via`, `confidence`, `review_status`
- **Time-aware**: ranks, affiliations, and locations change; use `valid_from`/`valid_until` on edges
- **Disambiguation built-in**: `aliases[]`, `external_ids{}`, and a `name_collisions` resolution table
- **Backward-compatible**: extends the existing Story Graph schema (7 node types, 17 relation types) rather than replacing it

### 1.2 New entity types (extending `NodeType` enum)

The existing `NodeType` enum has: `Person, Group, Place, Work, Event, Claim, Image`.

Add:

| Type | ID prefix | Purpose |
|---|---|---|
| `DOJO` | `dojo:` | Physical training location (distinct from `Place` which is geographic) |
| `FEDERATION` | `fed:` | Governing body (CAA, Aikikai, USAF, Birankai) |
| `BOOK` | `book:` | Published book (distinct from generic `Work`) |
| `PODCAST` | `pod:` | Podcast show or episode |
| `RANK` | `rank:` | Rank award event (e.g., "Nadeau awarded 8th dan") |

`Person`, `Group`, `Place`, `Event`, `Claim`, `Image` remain unchanged.

### 1.3 New edge types (extending `RelationType` enum)

The existing `RelationType` enum has: `ALIAS_OF, FOUNDED, MEMBER_OF, WORKED_AT, LIVED_AT, CREATED, PUBLISHED_AT, DESCRIBES, ABOUT, ASSERTED_BY, CONTRADICTS, SUPPORTED_BY, LOCATED_IN, PRECEDES, MENTIONS, CONTAINS, DEPICTS`.

Add:

| Edge type | Direction | Attributes | Example |
|---|---|---|---|
| `TEACHER_STUDENT` | teacher → student | `start_year`, `end_year`, `context`, `confidence`, `source_url` | `person:robert-nadeau` → `person:dan-millman` |
| `CO_AUTHORED` | person → book | `role` (author/editor/contributor), `source_url` | `person:dan-millman` → `book:way-of-the-peaceful-warrior` |
| `CO_APPEARANCE` | person → person | `event_id`, `date`, `context`, `source_url` | `person:dan-millman` → `person:robert-nadeau` (budovideos book) |
| `ORGANIZATIONAL_ROLE` | person → federation | `role` (division_head/chief_instructor/founder), `start_year`, `end_year`, `source_url` | `person:robert-nadeau` → `fed:caa` (division head) |
| `DOJO_AFFILIATION` | dojo → federation | `division`, `start_year`, `end_year`, `source_url` | `dojo:aikido-of-marin` → `fed:caa` (Division 3) |
| `DOJO_LOCATION` | dojo → place | `address`, `lat`, `lng`, `start_year`, `end_year` | `dojo:aikido-of-marin` → `place:san-rafael-ca` |
| `HEAD_INSTRUCTOR` | person → dojo | `start_year`, `end_year`, `source_url` | `person:richard-moon-aikido` → `dojo:aikido-of-marin` |
| `RANK_AWARDED` | rank → person | `rank_level` (e.g., "6th dan"), `date`, `awarded_by`, `source_url` | `rank:moon-6th-dan` → `person:richard-moon-aikido` |
| `PUBLISHED` | book → source | `publisher`, `isbn`, `publish_date` | `book:quantum-aikido` → `src:publisher:blue-snake-books` |

### 1.4 Relational DDL (PostgreSQL / SQLite)

```sql
-- ============================================================
-- LINEAGE GRAPH — RELATIONAL SCHEMA
-- Extends existing Story Graph tables (nodes, edges, sources)
-- ============================================================

-- Existing tables remain as-is. These are NEW tables for structured
-- lineage data that complement the property-graph JSON columns.

-- --- Persons (denormalized view of Person nodes) ---
CREATE TABLE lineage_persons (
    node_id         TEXT PRIMARY KEY,          -- e.g. 'person:robert-nadeau'
    canonical_name  TEXT NOT NULL,
    aliases         TEXT[],                    -- e.g. ['Bob Nadeau', 'Nadeau Shihan']
    birth_year      INTEGER,
    death_year      INTEGER,
    birth_place     TEXT,
    primary_art     TEXT,                      -- e.g. 'Aikido'
    current_rank    TEXT,                      -- e.g. '8th dan'
    wikipedia_url   TEXT,
    kg_id           TEXT,                      -- Google Knowledge Graph @id
    official_url    TEXT,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- --- Dojos ---
CREATE TABLE lineage_dojos (
    node_id         TEXT PRIMARY KEY,          -- e.g. 'dojo:aikido-of-marin'
    name            TEXT NOT NULL,
    aliases         TEXT[],
    head_instructor TEXT,                      -- person node_id (current)
    federation_id   TEXT,                      -- fed: node_id (current)
    division        TEXT,                      -- e.g. 'Division 3'
    website         TEXT,
    email           TEXT,
    phone           TEXT,
    address_line    TEXT,
    city            TEXT,
    state           TEXT,
    country         TEXT,
    lat             DOUBLE PRECISION,
    lng             DOUBLE PRECISION,
    geocode_source  TEXT,                      -- 'google_geocode' | 'manual' | 'csv'
    lineage         TEXT,                      -- e.g. 'aikikai', 'nadeau', 'ki_society'
    youth_program   BOOLEAN,
    web_maturity    TEXT,                      -- 'basic_cms' | 'real_cms_blog' | etc.
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- --- Federations ---
CREATE TABLE lineage_federations (
    node_id         TEXT PRIMARY KEY,          -- e.g. 'fed:caa'
    name            TEXT NOT NULL,
    full_name       TEXT,                      -- 'California Aikido Association'
    aliases         TEXT[],
    parent_fed      TEXT,                      -- e.g. 'fed:aikikai' (CAA is under Aikikai)
    website         TEXT,
    founded_year    INTEGER,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- --- Books ---
CREATE TABLE lineage_books (
    node_id         TEXT PRIMARY KEY,          -- e.g. 'book:way-of-the-peaceful-warrior'
    title           TEXT NOT NULL,
    subtitle        TEXT,
    isbn_10         TEXT,
    isbn_13         TEXT,
    publisher       TEXT,
    publish_date    DATE,
    openlibrary_key TEXT,                      -- e.g. 'OL1957444W'
    google_books_id TEXT,
    amazon_asin     TEXT,
    author_ids      TEXT[],                    -- person node_ids
    page_count      INTEGER,
    language        TEXT DEFAULT 'en',
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- --- Podcast episodes ---
CREATE TABLE lineage_episodes (
    node_id         TEXT PRIMARY KEY,          -- e.g. 'pod:whistlekick-672'
    show_name       TEXT NOT NULL,
    episode_title   TEXT NOT NULL,
    episode_number  INTEGER,
    publish_date    DATE,
    duration_seconds INTEGER,
    guest_ids       TEXT[],                    -- person node_ids
    host_ids        TEXT[],                    -- person node_ids
    url             TEXT,
    rss_url         TEXT,
    transcript_url  TEXT,
    metadata_json   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- --- Edge table (structured version of the JSON edges table) ---
-- This mirrors the existing 'edges' table but with typed columns
-- for the new lineage-specific edge types.
CREATE TABLE lineage_edges (
    id              SERIAL PRIMARY KEY,
    src_id          TEXT NOT NULL,
    edge_type       TEXT NOT NULL,             -- 'TEACHER_STUDENT' | 'CO_AUTHORED' | etc.
    dst_id          TEXT NOT NULL,
    -- Common attributes
    confidence      REAL DEFAULT 0.5,          -- 0.0–1.0
    source_url      TEXT,
    discovered_via  TEXT,                      -- 'relationship_search' | 'kg_api' | 'manual' | 'biblio_api'
    review_status   TEXT DEFAULT 'pending',    -- 'pending' | 'approved' | 'rejected' | 'auto'
    metadata_json   JSONB DEFAULT '{}',
    -- Time range (for versioning)
    valid_from      DATE,                      -- when relationship started
    valid_until     DATE,                      -- when it ended (NULL = current)
    created_at      TIMESTAMPTZ DEFAULT now(),
    -- Prevent duplicate edges (same src+type+dst+valid_from)
    UNIQUE(src_id, edge_type, dst_id, valid_from)
);

-- --- Name collision resolution ---
CREATE TABLE name_collisions (
    id              SERIAL PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    node_id         TEXT NOT NULL,             -- the resolved entity
    disambiguator   TEXT,                      -- e.g. 'aikido', 'chef', 'law-professor'
    context_note    TEXT,
    resolved_at     TIMESTAMPTZ DEFAULT now(),
    resolved_by     TEXT DEFAULT 'auto',       -- 'auto' | 'manual' | 'kg_api'
    UNIQUE(canonical_name, disambiguator)
);

-- --- Rank history (time-series) ---
CREATE TABLE rank_history (
    id              SERIAL PRIMARY KEY,
    person_id       TEXT NOT NULL,
    rank_level      TEXT NOT NULL,             -- '1st dan', '6th dan', '8th dan'
    rank_system     TEXT DEFAULT 'aikikai',    -- 'aikikai' | 'yoshinkan' | etc.
    awarded_by      TEXT,                      -- person node_id
    awarded_date    DATE,
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(person_id, rank_level, awarded_date)
);

-- --- Dojo affiliation history (time-series) ---
CREATE TABLE dojo_affiliation_history (
    id              SERIAL PRIMARY KEY,
    dojo_id         TEXT NOT NULL,
    federation_id   TEXT NOT NULL,
    division        TEXT,
    start_date      DATE,
    end_date        DATE,                      -- NULL = current
    source_url      TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(dojo_id, federation_id, start_date)
);

-- ============================================================
-- INDEXES
-- ============================================================

-- Persons
CREATE INDEX idx_persons_canonical_name ON lineage_persons(canonical_name);
CREATE INDEX idx_persons_aliases ON lineage_persons USING GIN(aliases);
CREATE INDEX idx_persons_primary_art ON lineage_persons(primary_art);
CREATE INDEX idx_persons_wikipedia ON lineage_persons(wikipedia_url) WHERE wikipedia_url IS NOT NULL;

-- Dojos
CREATE INDEX idx_dojos_city ON lineage_dojos(city);
CREATE INDEX idx_dojos_state ON lineage_dojos(state);
CREATE INDEX idx_dojos_country ON lineage_dojos(country);
CREATE INDEX idx_dojos_federation ON lineage_dojos(federation_id);
CREATE INDEX idx_dojos_lineage ON lineage_dojos(lineage);
CREATE INDEX idx_dojos_head_instructor ON lineage_dojos(head_instructor);
CREATE INDEX idx_dojos_geo ON lineage_dojos(lat, lng) WHERE lat IS NOT NULL;
CREATE INDEX idx_dojos_name_trgm ON lineage_dojos(name) USING gin(trigram_ops);  -- fuzzy search (pg_trgm)

-- Books
CREATE INDEX idx_books_isbn13 ON lineage_books(isbn_13) WHERE isbn_13 IS NOT NULL;
CREATE INDEX idx_books_openlibrary ON lineage_books(openlibrary_key) WHERE openlibrary_key IS NOT NULL;
CREATE INDEX idx_books_authors ON lineage_books USING GIN(author_ids);

-- Episodes
CREATE INDEX idx_episodes_guests ON lineage_episodes USING GIN(guest_ids);
CREATE INDEX idx_episodes_date ON lineage_episodes(publish_date);
CREATE INDEX idx_episodes_show ON lineage_episodes(show_name);

-- Edges
CREATE INDEX idx_edges_src ON lineage_edges(src_id);
CREATE INDEX idx_edges_dst ON lineage_edges(dst_id);
CREATE INDEX idx_edges_type ON lineage_edges(edge_type);
CREATE INDEX idx_edges_src_type ON lineage_edges(src_id, edge_type);
CREATE INDEX idx_edges_dst_type ON lineage_edges(dst_id, edge_type);
CREATE INDEX idx_edges_valid ON lineage_edges(valid_from, valid_until) WHERE valid_until IS NULL;
CREATE INDEX idx_edges_confidence ON lineage_edges(confidence);
CREATE INDEX idx_edges_review ON lineage_edges(review_status);

-- Rank history
CREATE INDEX idx_rank_person ON rank_history(person_id);
CREATE INDEX idx_rank_date ON rank_history(awarded_date);

-- Affiliation history
CREATE INDEX idx_affil_dojo ON dojo_affiliation_history(dojo_id);
CREATE INDEX idx_affil_fed ON dojo_affiliation_history(federation_id);
CREATE INDEX idx_affil_current ON dojo_affiliation_history(dojo_id) WHERE end_date IS NULL;
```

### 1.5 Property-graph model (Neo4j / Apache AGE compatible)

```cypher
// Node labels (maps to NodeType enum + new types)
(:Person {id, canonical_name, aliases[], birth_year, primary_art, current_rank, wikipedia_url, kg_id})
(:Dojo   {id, name, aliases[], website, city, state, country, lat, lng, lineage, youth_program})
(:Federation {id, name, full_name, aliases[], parent_fed, website, founded_year})
(:Book   {id, title, subtitle, isbn_13, publisher, publish_date, openlibrary_key, author_ids[]})
(:Podcast {id, show_name, episode_title, episode_number, publish_date, guest_ids[], url})
(:Place  {id, name, city, state, country, lat, lng})
(:Event  {id, name, date, location_id, description})
(:Rank   {id, person_id, rank_level, rank_system, awarded_date, awarded_by})
(:Claim  {id, label, claim_type, stance, evidence_mode, source_urls[]})

// Edge types with properties
(:Person)-[:TEACHER_STUDENT {start_year, end_year, context, confidence, source_url, review_status}]->(:Person)
(:Person)-[:CO_AUTHORED {role, source_url}]->(:Book)
(:Person)-[:CO_APPEARANCE {event_id, date, context, source_url}]->(:Person)
(:Person)-[:ORGANIZATIONAL_ROLE {role, start_year, end_year, source_url}]->(:Federation)
(:Person)-[:HEAD_INSTRUCTOR {start_year, end_year, source_url}]->(:Dojo)
(:Dojo)-[:DOJO_AFFILIATION {division, start_year, end_year, source_url}]->(:Federation)
(:Dojo)-[:DOJO_LOCATION {address, lat, lng, start_year, end_year}]->(:Place)
(:Rank)-[:RANK_AWARDED {rank_level, date, awarded_by, source_url}]->(:Person)
(:Book)-[:PUBLISHED {publisher, isbn, publish_date}]->(:Source)
(:Person)-[:FOUNDED {year, source_url}]->(:Dojo|:Federation|:Group)
(:Person)-[:MEMBER_OF {context, source_url}]->(:Federation|:Group)
(:Person)-[:MENTIONS {context, source_url, discovered_via}]->(:Person)
(:Claim)-[:ABOUT {evidence}]->(:Person|:Dojo|:Book)
(:Claim)-[:SUPPORTED_BY]->(:Source)
```

### 1.6 Example analytics queries

```sql
-- "Show all dojos teaching Nadeau-lineage aikido in California"
SELECT d.name, d.city, d.website, d.head_instructor, p.canonical_name AS instructor_name
FROM lineage_dojos d
JOIN lineage_persons p ON d.head_instructor = p.node_id
WHERE d.lineage = 'nadeau' AND d.state = 'CA'
ORDER BY d.city;

-- "List all co-authored works linking Nadeau's senior students"
SELECT b.title, b.isbn_13, b.publish_date,
       array_agg(p.canonical_name) AS authors
FROM lineage_books b
JOIN lineage_edges e ON e.dst_id = b.node_id AND e.edge_type = 'CO_AUTHORED'
JOIN lineage_persons p ON e.src_id = p.node_id
WHERE e.src_id IN (
    SELECT dst_id FROM lineage_edges
    WHERE edge_type = 'TEACHER_STUDENT' AND src_id = 'person:robert-nadeau'
)
GROUP BY b.node_id, b.title, b.isbn_13, b.publish_date;

-- "Trace the full lineage from Ueshiba → Nadeau → all students → their dojos"
WITH RECURSIVE lineage AS (
    SELECT 'person:morihei-ueshiba' AS person_id, 0 AS depth
    UNION ALL
    SELECT e.dst_id, l.depth + 1
    FROM lineage l
    JOIN lineage_edges e ON e.src_id = l.person_id AND e.edge_type = 'TEACHER_STUDENT'
    WHERE l.depth < 5
)
SELECT l.person_id, p.canonical_name, l.depth,
       d.name AS dojo_name, d.city, d.state
FROM lineage l
JOIN lineage_persons p ON l.person_id = p.node_id
LEFT JOIN lineage_dojos d ON d.head_instructor = l.person_id
ORDER BY l.depth, p.canonical_name;
```

---

## Part 2 — Concrete API Query Templates

### 2.1 Web search APIs

#### 2.1.1 Brave Search API

**Endpoint**: `GET https://api.search.brave.com/res/v1/web/search`
**Auth**: `X-Subscription-Token: <key>` header
**Status**: Key exists but has 0 monthly quota (needs subscription upgrade)

```python
# Query template — entity-pair relationship search
import requests

headers = {
    "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
    "Accept": "application/json",
}
params = {
    "q": '"Dan Millman" "Robert Nadeau" aikido',
    "count": 20,
    "country": "us",
    "search_lang": "en",
    "safesearch": "moderate",
}
resp = requests.get("https://api.search.brave.com/res/v1/web/search",
                    headers=headers, params=params, timeout=15)
```

**Expected response structure**:
```json
{
  "web": {
    "results": [
      {
        "title": "Robert Nadeau - Aikido Master",
        "url": "https://www.aikido-health.com/robert-nadeau.html",
        "description": "Michael Murphy, George Leonard and Dan Millman...",
        "age": "2024-01-15",
        "page_age": "2024-01-15T00:00:00Z"
      }
    ]
  },
  "query": {"original": "\"Dan Millman\" \"Robert Nadeau\" aikido"}
}
```

**Mapping to schema**:
- `web.results[].url` → `sources.url` (new SourceRecord)
- `web.results[].title` → `sources.title`
- `web.results[].description` → edge `metadata.snippet`
- Query string → edge `metadata.query`
- `"Dan Millman"` + `"Robert Nadeau"` in same result → candidate `TEACHER_STUDENT` or `CO_APPEARANCE` edge (pending review)

**Domain-targeted queries** (for known authoritative sites):
```python
# Site-restricted queries for deep source harvesting
queries = [
    'site:peacefulwarrior.com "Robert Nadeau"',
    'site:quantumaikido.com "Nadeau"',
    'site:nadeaushihan.com "student"',
    'site:aikidojournal.com "Nadeau" "Millman"',
    'site:aikiweb.com "Nadeau" "Moon"',
    'site:budovideos.com "Nadeau" "Millman"',
    'site:en.wikipedia.org "Robert Nadeau" aikido',
]
```

#### 2.1.2 Bing HTML search (fallback — no API key)

**Endpoint**: `GET https://www.bing.com/search?q=...`
**Auth**: None (HTML scraping)
**Status**: Working but degrades results after ~1 query per session (anti-bot)
**Parser**: `src/search/bing_search_client.py` (already implemented)

```python
from src.search.bing_search_client import BingSearchClient

client = BingSearchClient(delay_seconds=8)
results = client.search('"Dan Millman" "Robert Nadeau" aikido', count=20)
# Returns: list[SearchResult(url, title, snippet, provider, query, domain)]
```

**Mapping**: Same as Brave — `url` → source, `title`/`snippet` → edge metadata.

**Anti-bot mitigation strategy**:
- Rotate User-Agent strings
- Use 8–15 second delays between queries
- Cache all results in SQLite (`src/search/search_cache.py`) to avoid re-querying
- Consider Bing Web Search API (paid, ~$3/1K queries) for production

#### 2.1.3 Google Custom Search API

**Endpoint**: `GET https://www.googleapis.com/customsearch/v1`
**Auth**: `key=<API_KEY>&cx=<CUSTOM_SEARCH_ENGINE_ID>`
**Requires**: Creating a Custom Search Engine in Google Cloud Console that targets the domains above

```python
params = {
    "key": GOOGLE_API_KEY,
    "cx": CUSTOM_SEARCH_ENGINE_ID,  # restricts to peacefulwarrior.com, quantumaikido.com, etc.
    "q": '"Robert Nadeau" students',
    "num": 10,
}
resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
```

**Expected response**:
```json
{
  "items": [
    {
      "title": "Robert Nadeau Shihan - City Aikido",
      "link": "https://www.cityaikido.com/nadeau-shihan",
      "snippet": "Robert Nadeau was a personal student of Morihei Ueshiba...",
      "displayLink": "www.cityaikido.com",
      "pagemap": {
        "metatags": [{"og:title": "...", "og:description": "..."}]
      }
    }
  ]
}
```

**Mapping**: `items[].link` → source URL, `items[].pagemap.metatags` → structured metadata extraction.

**Cost**: 100 queries/day free, then $5/1K queries. Create a CSE restricted to: `peacefulwarrior.com, quantumaikido.com, nadeaushihan.com, aikidojournal.com, aikiweb.com, cityaikido.com, aikido-health.com, usadojo.com, budovideos.com, en.wikipedia.org`.

### 2.2 Bibliographic APIs

#### 2.2.1 Open Library API

**Endpoint**: `GET https://openlibrary.org/search.json`
**Auth**: None (free, no key)
**Status**: Working — confirmed 5 books for Peter Ralston

```python
# Query by author
resp = requests.get("https://openlibrary.org/search.json", params={
    "author": "Dan Millman",
    "limit": 20,
    "fields": "key,title,first_publish_year,isbn,author_name,publisher,language,number_of_pages_median,subject",
})
```

**Expected response**:
```json
{
  "docs": [
    {
      "key": "/works/OL1957444W",
      "title": "The Book of Not Knowing",
      "first_publish_year": 2010,
      "isbn": ["9781556438578", "1556438570"],
      "author_name": ["Peter Ralston"],
      "publisher": ["North Atlantic Books"],
      "language": ["eng"],
      "number_of_pages_median": 400,
      "subject": ["martial arts", "consciousness", "zen"]
    }
  ]
}
```

**Mapping to schema**:
- `docs[].key` → `lineage_books.openlibrary_key`
- `docs[].title` → `lineage_books.title`
- `docs[].isbn[0]` → `lineage_books.isbn_13` (filter for 13-digit)
- `docs[].first_publish_year` → `lineage_books.publish_date`
- `docs[].author_name[]` → resolve to `person:` nodes, create `CO_AUTHORED` edges
- `docs[].publisher[0]` → `lineage_books.publisher`
- `docs[].subject[]` → `metadata_json.subjects`

```python
# Query by ISBN (to resolve a known book)
resp = requests.get(f"https://openlibrary.org/api/books", params={
    "bibkeys": "ISBN:9781556438578",
    "format": "json",
    "jscmd": "data",
})
# Returns: {"ISBN:9781556438578": {"title": ..., "authors": [...], "publishers": [...], ...}}
```

**Transformation function** (Open Library → lineage schema):
```python
def ol_to_book_node(doc: dict) -> tuple[GraphNode, list[GraphEdge]]:
    """Transform an Open Library doc into a Book node + CO_AUTHORED edges."""
    ol_key = doc["key"].replace("/works/", "")
    book_id = f"book:{ol_key.lower().replace('ol','ol-')}"
    
    isbns = doc.get("isbn", [])
    isbn_13 = next((s for s in isbns if len(s) == 13), None)
    isbn_10 = next((s for s in isbns if len(s) == 10), None)
    
    book = GraphNode(
        id=book_id,
        type=NodeType.WORK,
        label=doc["title"],
        canonical_name=doc["title"],
        metadata={
            "openlibrary_key": doc["key"],
            "isbn_13": isbn_13,
            "isbn_10": isbn_10,
            "publisher": doc.get("publisher", [None])[0],
            "publish_year": doc.get("first_publish_year"),
            "pages": doc.get("number_of_pages_median"),
            "subjects": doc.get("subject", []),
            "source": "openlibrary_api",
        },
        source_urls=[f"https://openlibrary.org{doc['key']}"],
    )
    
    edges = []
    for author_name in doc.get("author_name", []):
        # Resolve author name to person node (via KG or existing graph)
        person_id = resolve_person_by_name(author_name)  # placeholder
        if person_id:
            edges.append(GraphEdge(
                src_id=person_id,
                rel_type=RelationType.CREATED,  # or CO_AUTHORED
                dst_id=book_id,
                metadata={"role": "author", "source": "openlibrary_api"},
            ))
    
    return book, edges
```

#### 2.2.2 Google Books API

**Endpoint**: `GET https://www.googleapis.com/books/v1/volumes`
**Auth**: None (free tier, no key needed for basic search; API key raises quota)

```python
# Search for books by author + title
resp = requests.get("https://www.googleapis.com/books/v1/volumes", params={
    "q": 'inauthor:"Dan Millman" "Way of the Peaceful Warrior"',
    "maxResults": 10,
    "printType": "books",
})
```

**Expected response**:
```json
{
  "items": [
    {
      "id": "Q5xHPgAACAAJ",
      "volumeInfo": {
        "title": "Way of the Peaceful Warrior",
        "subtitle": "A Book That Changes Lives",
        "authors": ["Dan Millman"],
        "publisher": "H.J. Kramer",
        "publishedDate": "2000-09-01",
        "industryIdentifiers": [
          {"type": "ISBN_10", "identifier": "0915811888"},
          {"type": "ISBN_13", "identifier": "9780915811882"}
        ],
        "pageCount": 240,
        "categories": ["Body, Mind & Spirit"],
        "language": "en",
        "infoLink": "https://books.google.com/books?id=Q5xHPgAACAAJ"
      }
    }
  ]
}
```

**Mapping**:
- `items[].id` → `lineage_books.google_books_id`
- `volumeInfo.industryIdentifiers` → `isbn_10` / `isbn_13`
- `volumeInfo.authors[]` → resolve to `person:` nodes, create `CO_AUTHORED` edges
- `volumeInfo.publishedDate` → `lineage_books.publish_date`
- `volumeInfo.publisher` → `lineage_books.publisher`

**Specific book lookups** (resolve known titles):
```python
books_to_resolve = [
    ('inauthor:"Dan Millman"', "Way of the Peaceful Warrior"),
    ('inauthor:"Richard Moon"', "Quantum Aikido"),
    ('inauthor:"Robert Nadeau"', "Aikido: The Art of Transformation"),
    ('inauthor:"Peter Ralston"', "The Book of Not Knowing"),
    ('inauthor:"George Leonard"', "Mastery"),
    ('inauthor:"Richard Strozzi-Heckler"', "In Search of the Warrior Spirit"),
]
for author_q, title in books_to_resolve:
    q = f'{author_q} "{title}"'
    resp = requests.get("https://www.googleapis.com/books/v1/volumes",
                        params={"q": q, "maxResults": 3})
```

### 2.3 Podcast / media APIs

#### 2.3.1 RSS-based podcast discovery (no API key needed)

**Strategy**: Most podcasts publish RSS feeds. Use the iTunes Search API to find shows, then fetch RSS for episode lists.

**Step 1 — Find podcast shows via iTunes Search API**:
```python
# Search for podcasts featuring target persons
resp = requests.get("https://itunes.apple.com/search", params={
    "term": "Dan Millman aikido",
    "media": "podcast",
    "limit": 10,
})
# Returns: {"results": [{"trackName": "Whistlekick Martial Arts Radio",
#   "feedUrl": "https://whistlekick.com/feed/", "trackId": 123456,
#   "artistName": "...", "trackCount": 500}]}
```

**Step 2 — Fetch RSS feed for episode list**:
```python
import feedparser

feed = feedparser.parse("https://whistlekick.com/feed/")
for entry in feed.entries:
    title = entry.title                      # "Episode 672 - Dan Millman"
    published = entry.published              # "Mon, 15 Jan 2024..."
    summary = entry.summary                  # episode description
    audio_url = entry.enclosures[0].href     # MP3 URL
    duration = entry.itunes_duration         # "45:30"
    # Extract guest name from title/summary
```

**Expected RSS structure** (standard podcast RSS):
```xml
<item>
  <title>Episode 672 - Dan Millman</title>
  <pubDate>Mon, 15 Jan 2024 06:00:00 EST</pubDate>
  <itunes:duration>45:30</itunes:duration>
  <description>Dan Millman discusses his aikido training with Robert Nadeau...</description>
  <enclosure url="https://whistlekick.com/ep672.mp3" type="audio/mpeg"/>
  <itunes:episode>672</itunes:episode>
</item>
```

**Mapping to schema**:
- `feed.feed.title` → `lineage_episodes.show_name`
- `entry.title` → `lineage_episodes.episode_title`
- `entry.itunes:episode` → `lineage_episodes.episode_number`
- `entry.pubDate` → `lineage_episodes.publish_date`
- `entry.itunes:duration` → `lineage_episodes.duration_seconds`
- `entry.enclosures[0].url` → `lineage_episodes.url`
- Extracted guest names from title/summary → resolve to `person:` nodes → `guest_ids[]`
- If two target persons appear in same episode → `CO_APPEARANCE` edge

**Guest extraction logic**:
```python
import re

def extract_guests_from_episode(title: str, summary: str, known_persons: dict[str, str]) -> list[str]:
    """Extract guest person_ids from episode title and summary.
    
    Args:
        known_persons: {canonical_name_lower: person_node_id}
    Returns:
        List of person node_ids found in the text.
    """
    text = (title + " " + summary).lower()
    found = []
    for name_lower, node_id in known_persons.items():
        # Check for full name or last name (with context)
        if name_lower in text:
            found.append(node_id)
        else:
            # Check last name only if it's distinctive enough
            last_name = name_lower.split()[-1]
            if last_name in text and last_name not in COMMON_LAST_NAMES:
                found.append(node_id)
    return found
```

#### 2.3.2 YouTube search (for video interviews)

**Endpoint**: `GET https://www.googleapis.com/youtube/v3/search`
**Auth**: `key=<YOUTUBE_API_KEY>` (free tier: 10K units/day)

```python
resp = requests.get("https://www.googleapis.com/youtube/v3/search", params={
    "key": YOUTUBE_API_KEY,
    "q": '"Robert Nadeau" aikido interview',
    "type": "video",
    "maxResults": 10,
    "part": "snippet",
    "publishedAfter": "2020-01-01T00:00:00Z",
})
# Returns: {"items": [{"id": {"videoId": "abc123"},
#   "snippet": {"title": "...", "publishedAt": "...", "description": "..."}}]}
```

**Mapping**: `videoId` → YouTube URL, `snippet.title`/`description` → extract guest names → `CO_APPEARANCE` edge if 2+ target persons mentioned.

### 2.4 Google Knowledge Graph API (already implemented)

**Endpoint**: `GET https://kgsearch.googleapis.com/v1/entities:search`
**Auth**: `key=<GOOGLE_API_KEY>` (must be a Cloud/Maps key, not Gemini)
**Status**: Working via `src/search/kg_client.py`

```python
from src.search.kg_client import KnowledgeGraphClient

kg = KnowledgeGraphClient(api_key=KG_KEY)
entity = kg.resolve_person("Dan Millman", "author martial arts")
# Returns: KGEntity(name, description, wikipedia_url, url, article_body, kg_id)
```

**Mapping**: `entity.wikipedia_url` → `lineage_persons.wikipedia_url`, `entity.kg_id` → `lineage_persons.kg_id`, `entity.article_body` → `metadata_json.kg_article_body`.

---

## Part 3 — Extension Plan

### 3.1 Phase 1: Enrich Nadeau student network

**Current state**: 5 students of Nadeau ingested (Millman, Moon, Strozzi-Heckler, Leonard, Ralston). Wikipedia lists these as "Notable students".

**Workflow**:
1. **Fetch Wikipedia Nadeau article** → extract full student list (already done: George Leonard, Richard Strozzi-Heckler, Dan Millman, Richard Moon)
2. **For each student**, run the pipeline:
   - KG resolution → get Wikipedia URL, description
   - Open Library query → enumerate all books
   - Bing/Brave search → find interviews, seminar appearances, organizational roles
   - Fetch student's Wikipedia page (if exists) → extract teachers, students, dojos
3. **Create edges**:
   - `TEACHER_STUDENT` from Nadeau → each student
   - `CO_AUTHORED` from each student → their books
   - `CO_APPEARANCE` between students who appear together (e.g., budovideos book)
   - `ORGANIZATIONAL_ROLE` for any federation roles
4. **Recursive expansion**: For each student who is also a teacher, repeat steps 2–3 for their students (depth-limited to 3 levels)

**Target students to research next**:
- George Leonard → Wikipedia exists, author of *Mastery*, co-founder of Esalen-related work
- Richard Strozzi-Heckler → Wikipedia exists, author of *In Search of the Warrior Spirit*, 6th dan
- Peter Ralston → no Wikipedia (issue #22), author of 9+ books, 1978 world champion
- Additional students from City Aikido / Aikido of Marin pages

### 3.2 Phase 2: CAA division heads and dojo integration

**Current state**: WorldStudioFinder has `data/audit/aikido_pilot_review.csv` with 1,390 aikido dojos (name, city, state, country, website, lineage, dojo_cho_name). `data/reference/aikido_lineage_patterns.json` includes a `nadeau` lineage pattern.

**CAA structure** (from public sources):
- Division 1: Northern California (Nadeau lineage)
- Division 2: Central California
- Division 3: Southern California
- Each division has a division head who reports to the CAA chief instructor

**ETL steps from WorldStudioFinder CSV → lineage schema**:

```python
# Step 1: Load CSV and filter to aikido dojos
import csv

with open("data/audit/aikido_pilot_review.csv") as f:
    reader = csv.DictReader(f)
    aikido_dojos = [row for row in reader if row["lineage"] and row["lineage"] != ""]

print(f"Total aikido dojos with lineage: {len(aikido_dojos)}")
# Expected: ~1,390 rows

# Step 2: Create dojo nodes
for row in aikido_dojos:
    dojo_id = f"dojo:{slugify(row['name'])}"
    dojo = GraphNode(
        id=dojo_id,
        type=NodeType.DOJO,  # new type
        label=row["name"],
        canonical_name=row["name"],
        metadata={
            "city": row["city"],
            "state": row["state"],
            "country": row["country"],
            "website": row["website"],
            "lineage": row["lineage"],
            "dojo_cho_name": row["dojo_cho_name"],
            "heuristic_dojo_cho": row["heuristic_dojo_cho"],
            "youth_program": row["youth_program"] == "yes",
            "web_maturity": row["web_maturity"],
            "source": "worldstudiofinder_aikido_pilot",
        },
        source_urls=[row["website"]] if row["website"] else [],
    )
    db.add_node(dojo)
    
    # Step 3: Geocode (if not already geocoded)
    if not row.get("lat"):
        # Use Google Geocoding API or OpenStreetMap Nominatim
        coords = geocode(f"{row['name']}, {row['city']}, {row['state']}, {row['country']}")
        if coords:
            dojo.metadata["lat"] = coords["lat"]
            dojo.metadata["lng"] = coords["lng"]
    
    # Step 4: Link to federation based on lineage
    lineage = row["lineage"].lower()
    if lineage == "aikikai":
        fed_id = "fed:aikikai"
    elif lineage == "nadeau":
        fed_id = "fed:caa"  # Nadeau lineage → CAA
    elif lineage == "ki_society":
        fed_id = "fed:ki-society"
    # ... etc.
    
    if fed_id:
        edge = GraphEdge(
            src_id=dojo_id,
            rel_type=RelationType.DOJO_AFFILIATION,  # new type
            dst_id=fed_id,
            metadata={
                "lineage": lineage,
                "source": "worldstudiofinder_aikido_pilot",
            },
        )
        db.add_edge(edge)
    
    # Step 5: Link head instructor (if resolvable)
    cho_name = row["dojo_cho_name"] or row["heuristic_dojo_cho"]
    if cho_name:
        person_id = resolve_person_by_name(cho_name)
        if person_id:
            edge = GraphEdge(
                src_id=person_id,
                rel_type=RelationType.HEAD_INSTRUCTOR,  # new type
                dst_id=dojo_id,
                metadata={"source": "worldstudiofinder_csv"},
            )
            db.add_edge(edge)
```

**Step 6: CAA division head ingestion** (from CAA website or Wikipedia):
```python
# CAA division heads (to be verified from ca-aikido.com)
caa_divisions = [
    {"division": "Division 1", "head": "person:robert-nadeau", "region": "Northern California"},
    {"division": "Division 2", "head": None, "region": "Central California"},
    {"division": "Division 3", "head": None, "region": "Southern California"},
]

for div in caa_divisions:
    if div["head"]:
        edge = GraphEdge(
            src_id=div["head"],
            rel_type=RelationType.ORGANIZATIONAL_ROLE,  # new type
            dst_id="fed:caa",
            metadata={"role": "division_head", "division": div["division"]},
        )
        db.add_edge(edge)
```

### 3.3 Phase 3: US and global dojo directory integration

**Goal**: Every dojo node linked to lineage (teacher, federation, division) + geolocation (city, region, coordinates).

**Data sources**:
1. **WorldStudioFinder CSV** — 1,390 aikido dojos (already available)
2. **AikiWeb dojo directory** — `https://www.aikiweb.com/search/` (needs scraping, already has Chrome profile cached)
3. **CAA dojo list** — `https://ca-aikido.com/dojos/` (needs fetching)
4. **Aikikai Hombu international dojo list** — needs API/scraping

**ETL pipeline**:
```
[CSV/HTML sources] → [Parse] → [Normalize] → [Geocode] → [Disambiguate] → [Ingest] → [Export]
      ↓                ↓           ↓            ↓            ↓            ↓          ↓
   raw_html/      parsers/   lineage_dojos  Google API   name_collisions  GraphDB  snapshot/
```

**Geocoding strategy**:
- Use Google Geocoding API (existing key, $200/month free credit)
- Cache all geocode results in `data/cache/geocode_cache.sqlite` (lat/lng by address)
- Fallback: OpenStreetMap Nominatim (free, 1 req/sec limit)
- Store: `lat`, `lng`, `geocode_precision` (ROOFTOP/APPROXIMATE), `geocode_source`

### 3.4 ETL from existing dojo datasets

#### 3.4.1 Raw staging layer

Assume CSV/SQLite source tables with columns like:
```
dojo_name, website, head_name, email, phone_number, division, city, region, country
```

**Step 1 — Stage raw data into `dojo_raw` table** (no transformation, preserves provenance):

```sql
CREATE TABLE IF NOT EXISTS dojo_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT NOT NULL,              -- e.g. 'aikido_pilot_review.csv'
    source_row      INTEGER NOT NULL,
    dojo_name       TEXT,
    website         TEXT,
    head_name       TEXT,
    email           TEXT,
    phone_number    TEXT,
    division        TEXT,
    city            TEXT,
    region          TEXT,
    state           TEXT,
    country         TEXT,
    lat             REAL,
    lng             REAL,
    lineage         TEXT,
    youth_program   TEXT,
    web_maturity    TEXT,
    dojo_cho_name   TEXT,
    heuristic_dojo_cho TEXT,
    philosophy_keywords TEXT,
    raw_json        TEXT,                       -- full original row as JSON
    imported_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE(source_file, source_row)
);

CREATE INDEX idx_dojo_raw_name ON dojo_raw(dojo_name);
CREATE INDEX idx_dojo_raw_website ON dojo_raw(website);
CREATE INDEX idx_dojo_raw_city ON dojo_raw(city, state, country);
```

```python
def stage_dojo_csv(csv_path: str, db: GraphDB):
    """Stage raw CSV rows into dojo_raw without any transformation."""
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            db.execute("""
                INSERT OR IGNORE INTO dojo_raw (source_file, source_row, dojo_name, website,
                    head_name, email, phone_number, division, city, region, state, country,
                    lat, lng, lineage, youth_program, web_maturity, dojo_cho_name,
                    heuristic_dojo_cho, philosophy_keywords, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                Path(csv_path).name, row_num,
                row.get("name", ""), row.get("website", ""),
                row.get("dojo_cho_name", "") or row.get("head_name", ""),
                row.get("email", ""), row.get("phone", ""),
                row.get("division", ""), row.get("city", ""),
                row.get("region", ""), row.get("state", ""),
                row.get("country", ""),
                row.get("lat"), row.get("lng"),
                row.get("lineage", ""), row.get("youth_program", ""),
                row.get("web_maturity", ""), row.get("dojo_cho_name", ""),
                row.get("heuristic_dojo_cho", ""),
                row.get("philosophy_keywords", ""),
                json.dumps(row),
            ))
```

#### 3.4.2 Cleaning and deduplication

**Step 2 — Clean names (trim, normalize case) and deduplicate by website+city**:

```python
import re
from urllib.parse import urlparse

def clean_dojo_name(name: str) -> str:
    """Normalize dojo name: trim, title-case, remove redundant suffixes."""
    name = name.strip()
    # Remove trailing "Aikido" if it's redundant (e.g., "Aikido of Marin Aikido")
    name = re.sub(r'\s+Aikido$', '', name, flags=re.IGNORECASE)
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name)
    return name

def normalize_domain(website: str) -> str:
    """Extract and normalize the domain from a URL."""
    if not website:
        return ""
    url = website.strip()
    if not url.startswith("http"):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().removeprefix("www.")
        return domain
    except Exception:
        return ""

def deduplicate_dojos(db: GraphDB) -> list[dict]:
    """Deduplicate dojo_raw rows by (normalized_domain, city).
    
    Returns a list of deduplicated dojo dicts ready for node creation.
    """
    rows = db.query_all("""
        SELECT * FROM dojo_raw
        ORDER BY source_file, source_row
    """)
    
    seen = {}  # key: (domain, city_lower) → first row
    deduped = []
    
    for row in rows:
        domain = normalize_domain(row["website"])
        city_lower = (row["city"] or "").strip().lower()
        
        # Primary dedup key: domain (if present)
        if domain:
            key = f"domain:{domain}"
        else:
            # Fallback: name + city
            name_lower = clean_dojo_name(row["dojo_name"]).lower()
            key = f"name_city:{name_lower}|{city_lower}"
        
        if key not in seen:
            seen[key] = row
            deduped.append(row)
        else:
            # Merge: keep the row with more complete data
            existing = seen[key]
            for field in ["email", "phone_number", "dojo_cho_name", "lat", "lng"]:
                if not existing.get(field) and row.get(field):
                    existing[field] = row[field]
    
    _log.info("Dojo dedup: %d raw → %d unique (by domain+city)", len(rows), len(deduped))
    return deduped
```

#### 3.4.3 Mapping to organization nodes and person edges

**Step 3 — Map to organization, creating new IDs**:

```python
def slugify(text: str) -> str:
    """Create a URL-safe slug from text."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = text.strip('-')
    return text

def create_dojo_nodes(deduped: list[dict], db: GraphDB) -> dict[str, str]:
    """Create Dojo nodes from deduplicated rows. Returns {dedup_key: node_id}."""
    id_map = {}
    for row in deduped:
        clean_name = clean_dojo_name(row["dojo_name"])
        dojo_id = f"dojo:{slugify(clean_name)}"
        
        # Skip if already exists (idempotent)
        if db.get_node(dojo_id):
            id_map[row["id"]] = dojo_id
            continue
        
        node = GraphNode(
            id=dojo_id,
            type=NodeType.DOJO,
            label=clean_name,
            canonical_name=clean_name,
            metadata={
                "city": row["city"],
                "state": row["state"],
                "region": row["region"],
                "country": row["country"],
                "website": row["website"],
                "domain": normalize_domain(row["website"]),
                "email": row["email"],
                "phone": row["phone_number"],
                "lineage": row["lineage"],
                "youth_program": row["youth_program"] == "yes",
                "web_maturity": row["web_maturity"],
                "philosophy_keywords": row["philosophy_keywords"],
                "lat": row["lat"],
                "lng": row["lng"],
                "source": "worldstudiofinder_etl",
                "source_file": row["source_file"],
            },
            source_urls=[row["website"]] if row["website"] else [],
        )
        db.add_node(node)
        id_map[row["id"]] = dojo_id
    return id_map
```

**Step 4 — Map `head_name` strings to person nodes via string normalization and alias lists**:

```python
def normalize_person_name(name: str) -> str:
    """Normalize a person name for matching."""
    name = name.strip()
    # Remove common titles
    name = re.sub(r'^(Sensei|Shihan|Hanshi|Professor|Prof\.|Dr\.)\s+', '', name, flags=re.IGNORECASE)
    # Normalize whitespace
    name = re.sub(r'\s+', ' ', name)
    return name

def map_head_to_person(head_name: str, db: GraphDB, alias_index: dict) -> str | None:
    """Map a head_name string from a CSV row to a person node_id.
    
    Resolution order:
    1. Exact match on canonical_name (case-insensitive)
    2. Match against alias index (pre-built from all Person nodes)
    3. Fuzzy match (Levenshtein distance ≤ 2 on last name)
    4. Return None → goes to person_candidate table
    """
    normalized = normalize_person_name(head_name)
    if not normalized:
        return None
    
    name_lower = normalized.lower()
    
    # 1. Exact canonical_name match
    matches = db.query_all("""
        SELECT node_id FROM lineage_persons
        WHERE lower(canonical_name) = ?
    """, name_lower)
    if len(matches) == 1:
        return matches[0]["node_id"]
    
    # 2. Alias match
    if name_lower in alias_index:
        candidates = alias_index[name_lower]
        if len(candidates) == 1:
            return candidates[0]
        # Multiple candidates → ambiguous, needs disambiguation
        return None  # → person_candidate
    
    # 3. Fuzzy last-name match
    last_name = name_lower.split()[-1]
    fuzzy = db.query_all("""
        SELECT node_id, canonical_name FROM lineage_persons
        WHERE lower(canonical_name) LIKE ?
    """, f"%{last_name}%")
    if len(fuzzy) == 1:
        return fuzzy[0]["node_id"]
    
    return None  # → person_candidate
```

**Step 5 — Insert `HEAD_INSTRUCTOR` and `DOJO_AFFILIATION` edges**:

```python
def insert_dojo_edges(dojo_id: str, row: dict, person_id: str | None, db: GraphDB):
    """Insert HEAD_INSTRUCTOR and DOJO_AFFILIATION edges for a dojo."""
    
    # HEAD_INSTRUCTOR edge (if person resolved)
    if person_id:
        edge = GraphEdge(
            src_id=person_id,
            rel_type=RelationType.HEAD_INSTRUCTOR,
            dst_id=dojo_id,
            metadata={
                "source": "worldstudiofinder_etl",
                "source_file": row["source_file"],
                "is_primary": True,  # first/head instructor
            },
        )
        db.add_edge(edge)
    
    # DOJO_AFFILIATION edge (based on lineage field)
    lineage = (row["lineage"] or "").lower()
    fed_id = LINEAGE_TO_FED.get(lineage)  # {"nadeau": "fed:caa", "aikikai": "fed:aikikai", ...}
    if fed_id:
        edge = GraphEdge(
            src_id=dojo_id,
            rel_type=RelationType.DOJO_AFFILIATION,
            dst_id=fed_id,
            metadata={
                "division": row.get("division", ""),
                "lineage": lineage,
                "source": "worldstudiofinder_etl",
            },
        )
        db.add_edge(edge)
```

#### 3.4.4 Entity reconciliation table

**Step 6 — Manual reconciliation layer for ambiguous cases**:

```sql
CREATE TABLE IF NOT EXISTS entity_reconciliation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT NOT NULL,              -- 'person' | 'dojo'
    candidate_name  TEXT NOT NULL,              -- the raw name from source
    candidate_data  TEXT,                       -- JSON: {source_file, row, context}
    matched_node_id TEXT,                       -- resolved node_id (NULL if unresolved)
    match_method    TEXT,                       -- 'exact' | 'alias' | 'fuzzy' | 'manual' | 'kg_api'
    confidence      REAL DEFAULT 0.0,           -- 0.0–1.0
    resolution_status TEXT DEFAULT 'pending',   -- 'pending' | 'resolved' | 'rejected' | 'needs_review'
    resolved_by     TEXT,                       -- 'auto' | 'manual:<reviewer>' | 'kg_api'
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    notes           TEXT
);

CREATE INDEX idx_recon_status ON entity_reconciliation(resolution_status);
CREATE INDEX idx_recon_name ON entity_reconciliation(candidate_name);
CREATE INDEX idx_recon_node ON entity_reconciliation(matched_node_id);
```

```python
def queue_for_reconciliation(name: str, entity_type: str, candidate_data: dict,
                              db: GraphDB, confidence: float = 0.0):
    """Queue an ambiguous match for manual review."""
    db.execute("""
        INSERT INTO entity_reconciliation
            (entity_type, candidate_name, candidate_data, confidence, resolution_status)
        VALUES (?, ?, ?, ?, 'needs_review')
    """, entity_type, name, json.dumps(candidate_data), confidence)

def resolve_reconciliation(rec_id: int, node_id: str, reviewer: str, notes: str = ""):
    """Manually resolve a reconciliation candidate."""
    db.execute("""
        UPDATE entity_reconciliation
        SET matched_node_id = ?, match_method = 'manual',
            resolution_status = 'resolved', resolved_by = ?,
            resolved_at = now(), notes = ?
        WHERE id = ?
    """, node_id, f"manual:{reviewer}", notes, rec_id)
```

**If multiple rows map to same canonical name, reuse `person_id`**:
```python
def get_or_create_person(name: str, db: GraphDB, alias_index: dict) -> tuple[str, bool]:
    """Get existing person_id or create new. Returns (node_id, was_created)."""
    existing = map_head_to_person(name, db, alias_index)
    if existing:
        return existing, False
    
    # Create new person node
    normalized = normalize_person_name(name)
    person_id = f"person:{slugify(normalized)}"
    
    # Check for name collision — if exists, add disambiguator
    if db.get_node(person_id):
        # Queue for reconciliation
        queue_for_reconciliation(name, "person", {"reason": "name_collision"}, db)
        return None, False
    
    node = GraphNode(
        id=person_id,
        type=NodeType.PERSON,
        label=normalized,
        canonical_name=normalized,
        metadata={"source": "dojo_etl_auto_created", "needs_review": True},
    )
    db.add_node(node)
    return person_id, True
```

### 3.5 Disambiguation strategies

#### 3.5.1 Challenges

- **Common names**: "Robert Nadeau" appears as an aikidoka and as a separate academic
- **Multiple teachers per dojo**: a dojo may list 3–5 instructors
- **Changes in affiliation over time**: dojos switch divisions or federations

#### 3.5.2 Contextual signal disambiguation

Use contextual signals (rank, aikido-specific keywords, domain names) to disambiguate aikidoka vs non-aikidoka for the same name:

```python
AIKIDO_CONTEXT_SIGNALS = [
    "aikido", "sensei", "shihan", "dojo", "dan", "aikikai",
    "ueshiba", "hombu", "seminar", "training", "uke",
    "iaido", "jo", "bokken", "tatami", "keikogi", "hakama",
]

def is_likely_aikidoka(name: str, context_text: str, domain: str = "") -> bool:
    """Determine if a name reference is likely an aikido practitioner.
    
    Uses contextual signals from surrounding text and website domain
    to disambiguate aikidoka from non-aikidoka with the same name.
    """
    text_lower = (context_text or "").lower()
    domain_lower = (domain or "").lower()
    
    # Strong signal: aikido-related domain
    aikido_domains = ["aikido", "aikikai", "dojo", "caa"]
    if any(d in domain_lower for d in aikido_domains):
        return True
    
    # Context keywords
    signal_count = sum(1 for s in AIKIDO_CONTEXT_SIGNALS if s in text_lower)
    return signal_count >= 2

def disambiguate_person(name: str, context: str, domain: str,
                        candidates: list[dict]) -> str | None:
    """Disambiguate among multiple person candidates using context.
    
    Args:
        candidates: list of {node_id, disambiguator, metadata} from name_collisions
    Returns:
        The best-matching node_id, or None if still ambiguous.
    """
    if len(candidates) == 1:
        return candidates[0]["node_id"]
    
    # Filter by aikido context
    if is_likely_aikidoka(name, context, domain):
        aikido_candidates = [c for c in candidates if c.get("disambiguator") == "aikido"]
        if len(aikido_candidates) == 1:
            return aikido_candidates[0]["node_id"]
    
    # Filter by domain match (person's primary_url domain matches source domain)
    for c in candidates:
        primary_url = c.get("metadata", {}).get("primary_url", "")
        if primary_url and normalize_domain(primary_url) == normalize_domain(domain):
            return c["node_id"]
    
    # Still ambiguous → queue for reconciliation
    return None
```

#### 3.5.3 Aliases and primary_url for clustering

Maintain aliases and `primary_url` for each person to cluster search hits:

```sql
-- Add to lineage_persons table:
ALTER TABLE lineage_persons ADD COLUMN primary_url TEXT;
-- aliases[] already defined as TEXT[] in the schema

-- Build an alias index for fast lookup:
CREATE INDEX idx_persons_aliases_gin ON lineage_persons USING GIN(aliases);
```

```python
def build_alias_index(db: GraphDB) -> dict[str, list[str]]:
    """Build a {alias_lower: [person_node_ids]} index from all Person nodes."""
    persons = db.query_all("SELECT node_id, canonical_name, aliases FROM lineage_persons")
    index = {}
    for p in persons:
        names = [p["canonical_name"]] + (p["aliases"] or [])
        for name in names:
            key = name.strip().lower()
            if key:
                index.setdefault(key, []).append(p["node_id"])
    return index
```

#### 3.5.4 Multiple instructors per dojo

Where a dojo lists multiple instructors, allow multiple `HEAD_INSTRUCTOR` edges; optionally designate one as `primary_head` via a property:

```python
def add_dojo_instructors(dojo_id: str, instructor_names: list[str],
                          primary_idx: int, db: GraphDB, alias_index: dict):
    """Add multiple instructor edges for a dojo.
    
    Args:
        instructor_names: list of instructor name strings from the source
        primary_idx: index into instructor_names of the primary/head instructor
    """
    for i, name in enumerate(instructor_names):
        person_id = map_head_to_person(name, db, alias_index)
        if not person_id:
            queue_for_reconciliation(name, "person", {
                "dojo_id": dojo_id,
                "context": "instructor_list",
            }, db, confidence=0.3)
            continue
        
        edge = GraphEdge(
            src_id=person_id,
            rel_type=RelationType.HEAD_INSTRUCTOR,
            dst_id=dojo_id,
            metadata={
                "is_primary": i == primary_idx,
                "source": "dojo_etl",
            },
        )
        db.add_edge(edge)
```

```sql
-- Query: get all instructors for a dojo, primary first
SELECT p.canonical_name, e.metadata_json->>'is_primary' AS is_primary
FROM lineage_edges e
JOIN lineage_persons p ON e.src_id = p.node_id
WHERE e.dst_id = ? AND e.edge_type = 'HEAD_INSTRUCTOR'
ORDER BY (e.metadata_json->>'is_primary') DESC, p.canonical_name;
```

#### 3.5.5 Person candidate table for uncertain matches

Keep uncertain matches in a `person_candidate` table with lower confidence; only promote to canonical person after manual review or multiple corroborating sources:

```sql
CREATE TABLE IF NOT EXISTS person_candidate (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_name  TEXT NOT NULL,
    suggested_node_id TEXT,                    -- best guess (may be NULL)
    context         TEXT,                      -- where this candidate was seen
    source_url      TEXT,
    source_file     TEXT,
    confidence      REAL DEFAULT 0.0,
    corroborating_sources TEXT DEFAULT '[]',   -- JSON array of source URLs
    status          TEXT DEFAULT 'candidate',  -- 'candidate' | 'promoted' | 'rejected'
    promoted_to     TEXT,                      -- person node_id if promoted
    created_at      TIMESTAMPTZ DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     TEXT
);

CREATE INDEX idx_pcandidate_name ON person_candidate(candidate_name);
CREATE INDEX idx_pcandidate_status ON person_candidate(status);
```

```python
def add_person_candidate(name: str, context: str, source_url: str,
                          suggested_node_id: str | None, confidence: float,
                          db: GraphDB):
    """Add an uncertain person match as a candidate."""
    # Check if this candidate already exists
    existing = db.query_one("""
        SELECT id, corroborating_sources FROM person_candidate
        WHERE candidate_name = ? AND status = 'candidate'
    """, name)
    
    if existing:
        # Add corroborating source
        sources = json.loads(existing["corroborating_sources"] or "[]")
        if source_url not in sources:
            sources.append(source_url)
        db.execute("""
            UPDATE person_candidate
            SET corroborating_sources = ?, confidence = ?
            WHERE id = ?
        """, json.dumps(sources), min(1.0, confidence + 0.1), existing["id"])
    else:
        db.execute("""
            INSERT INTO person_candidate
                (candidate_name, suggested_node_id, context, source_url, confidence)
            VALUES (?, ?, ?, ?, ?)
        """, name, suggested_node_id, context, source_url, confidence)

def promote_candidate(candidate_id: int, person_node_id: str, reviewer: str):
    """Promote a person candidate to a canonical person after review."""
    db.execute("""
        UPDATE person_candidate
        SET status = 'promoted', promoted_to = ?,
            reviewed_at = now(), reviewed_by = ?
        WHERE id = ?
    """, person_node_id, reviewer, candidate_id)
```

**Auto-promotion rule**: If a candidate accumulates ≥3 corroborating sources and confidence ≥0.7, auto-promote:
```python
def auto_promote_candidates(db: GraphDB):
    """Auto-promote candidates with strong corroboration."""
    candidates = db.query_all("""
        SELECT * FROM person_candidate
        WHERE status = 'candidate'
        AND json_array_length(corroborating_sources) >= 3
        AND confidence >= 0.7
    """)
    for c in candidates:
        if c["suggested_node_id"]:
            promote_candidate(c["id"], c["suggested_node_id"], "auto_promotion")
```

### 3.6 Versioning and time-series handling

**Principle**: Never overwrite historical data. Use `valid_from`/`valid_to` on edges and maintain `observed_at` timestamps so you can reconstruct the graph state at any point in time.

#### 3.6.1 Edge versioning with valid_from / valid_to

When you detect a change (e.g., a dojo changes affiliation from Division 2 to Division 1; a person is promoted from 6th dan to 7th dan), close out the old edge by setting `valid_to`, and insert a new edge with updated properties:

```python
def update_edge_with_version(db, src_id, edge_type, dst_id,
                              new_metadata: dict, valid_from: str,
                              observed_at: str | None = None):
    """Close the current edge version and open a new one.
    
    Args:
        valid_from: ISO date string for when the new version takes effect
        observed_at: when we observed this change (defaults to now)
    """
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    
    # Close existing current edge
    db.execute("""
        UPDATE lineage_edges 
        SET valid_until = ?, observed_at = ?
        WHERE src_id = ? AND edge_type = ? AND dst_id = ? AND valid_until IS NULL
    """, (valid_from, observed, src_id, edge_type, dst_id))
    
    # Insert new version
    db.execute("""
        INSERT INTO lineage_edges 
            (src_id, edge_type, dst_id, valid_from, observed_at, 
             confidence, source_url, discovered_via, review_status, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        src_id, edge_type, dst_id, valid_from, observed,
        new_metadata.get("confidence", 0.5),
        new_metadata.get("source_url"),
        new_metadata.get("discovered_via", "etl"),
        new_metadata.get("review_status", "pending"),
        json.dumps(new_metadata),
    ))
```

#### 3.6.2 observed_at timestamp for temporal reconstruction

Maintain an `observed_at` timestamp for each edge; you can reconstruct the graph state at any point in time for historical analysis:

```sql
-- Add observed_at to lineage_edges (if not already present)
ALTER TABLE lineage_edges ADD COLUMN observed_at TIMESTAMPTZ DEFAULT now();
CREATE INDEX idx_edges_observed ON lineage_edges(observed_at);

-- "What did Nadeau's lineage network look like in 2005 vs 2025?"
-- Reconstruct graph state as of a specific date:
CREATE OR REPLACE VIEW graph_state_at(date TEXT) AS
SELECT * FROM lineage_edges
WHERE valid_from <= date::date
  AND (valid_until IS NULL OR valid_until > date::date);
```

```python
def query_graph_at_date(db, date: str, edge_type: str | None = None):
    """Reconstruct all edges active as of a specific date.
    
    Example: query_graph_at_date(db, "2005-06-01", "TEACHER_STUDENT")
    returns all teacher-student relationships that were active on June 1, 2005.
    """
    return db.query_all("""
        SELECT * FROM lineage_edges
        WHERE valid_from <= ?
          AND (valid_until IS NULL OR valid_until > ?)
          AND (? IS NULL OR edge_type = ?)
        ORDER BY edge_type, src_id
    """, date, date, edge_type, edge_type)

def lineage_network_at_date(db, person_id: str, date: str, depth: int = 3):
    """Reconstruct a person's lineage network as of a specific date.
    
    Answers: 'What did Nadeau's lineage network look like in 2005?'
    """
    return db.query_all("""
        WITH RECURSIVE lineage AS (
            SELECT ? AS person_id, 0 AS depth
            UNION ALL
            SELECT e.dst_id, l.depth + 1
            FROM lineage l
            JOIN lineage_edges e ON e.src_id = l.person_id AND e.edge_type = 'TEACHER_STUDENT'
            WHERE e.valid_from <= ?
              AND (e.valid_until IS NULL OR e.valid_until > ?)
              AND l.depth < ?
        )
        SELECT l.person_id, p.canonical_name, l.depth,
               d.name AS dojo_name, d.city, d.state
        FROM lineage l
        JOIN lineage_persons p ON l.person_id = p.node_id
        LEFT JOIN lineage_dojos d ON d.head_instructor = l.person_id
        ORDER BY l.depth, p.canonical_name
    """, person_id, date, date, depth)
```

#### 3.6.3 Rank history (append-only)

```python
def record_rank_change(person_id: str, new_rank: str, awarded_date: str,
                        awarded_by: str | None, source_url: str, db: GraphDB):
    """Record a rank promotion. Never update existing rank_history rows."""
    db.execute("""
        INSERT OR IGNORE INTO rank_history 
            (person_id, rank_level, rank_system, awarded_by, awarded_date, source_url)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (person_id, new_rank, "aikikai", awarded_by, awarded_date, source_url))
    
    # Close old RANK_AWARDED edge, open new one
    update_edge_with_version(db, awarded_by or "fed:aikikai", "RANK_AWARDED",
                              person_id, {"rank_level": new_rank}, awarded_date)
    
    # Update denormalized current_rank in lineage_persons
    db.execute("""
        UPDATE lineage_persons SET current_rank = ?, updated_at = now()
        WHERE node_id = ?
    """, new_rank, person_id)
```

#### 3.6.4 Dojo affiliation history (append-only)

```python
def record_affiliation_change(dojo_id: str, new_fed_id: str, division: str,
                               start_date: str, source_url: str, db: GraphDB):
    """Record a dojo changing federation/division.
    
    Example: dojo moves from CAA Division 2 to Division 1.
    """
    # Close old affiliation
    db.execute("""
        UPDATE dojo_affiliation_history 
        SET end_date = ?
        WHERE dojo_id = ? AND end_date IS NULL
    """, (start_date, dojo_id))
    
    # Insert new affiliation
    db.execute("""
        INSERT INTO dojo_affiliation_history 
            (dojo_id, federation_id, division, start_date, source_url)
        VALUES (?, ?, ?, ?, ?)
    """, (dojo_id, new_fed_id, division, start_date, source_url))
    
    # Close old DOJO_AFFILIATION edge, open new one
    update_edge_with_version(db, dojo_id, "DOJO_AFFILIATION", new_fed_id,
                              {"division": division, "source_url": source_url},
                              start_date)
```

### 3.7 Indexing and analytics examples

With the above design, the implementation agent can expose queries like:

#### 3.7.1 All dojos teaching Nadeau-lineage aikido in California

**In SQL** — join `TEACHER_STUDENT` edges from Nadeau to a person, to `HEAD_INSTRUCTOR` edges from that person to a dojo, filter by region and confidence:

```sql
SELECT DISTINCT d.name, d.city, d.state, d.website,
       p.canonical_name AS instructor_name,
       e2.confidence AS instructor_confidence
FROM lineage_edges e1
JOIN lineage_persons p ON e1.dst_id = p.node_id
JOIN lineage_edges e2 ON e2.src_id = p.node_id AND e2.edge_type = 'HEAD_INSTRUCTOR'
JOIN lineage_dojos d ON e2.dst_id = d.node_id
WHERE e1.src_id = 'person:robert-nadeau'
  AND e1.edge_type = 'TEACHER_STUDENT'
  AND d.state = 'CA'
  AND e2.confidence >= 0.7
  AND e2.valid_until IS NULL
ORDER BY d.city, d.name;
```

**In Neo4j**:
```cypher
MATCH (n:Person {canonical_name: "Robert Nadeau"})-[:TEACHER_STUDENT]->(s:Person)
      -[:HEAD_INSTRUCTOR]->(d:Dojo)
WHERE d.state = "California" AND e.confidence >= 0.7
RETURN d, s;
```

#### 3.7.2 List all co-authored works linking Nadeau's senior students

**In SQL**:
```sql
SELECT b.title, b.isbn_13, b.publish_date,
       array_agg(p.canonical_name) AS co_authors
FROM lineage_books b
JOIN lineage_edges e ON e.dst_id = b.node_id AND e.edge_type = 'CO_AUTHORED'
JOIN lineage_persons p ON e.src_id = p.node_id
WHERE b.node_id IN (
    SELECT e2.dst_id FROM lineage_edges e2
    JOIN lineage_edges e3 ON e3.dst_id = e2.src_id
    WHERE e3.src_id = 'person:robert-nadeau'
      AND e3.edge_type = 'TEACHER_STUDENT'
      AND e2.edge_type = 'CO_AUTHORED'
)
GROUP BY b.node_id, b.title, b.isbn_13, b.publish_date
ORDER BY b.publish_date;
```

**In Neo4j**:
```cypher
MATCH (n:Person {canonical_name: "Robert Nadeau"})-[:TEACHER_STUDENT]->(s:Person)-[:CO_AUTHORED]->(w:Book)
WITH collect(s) AS students, w
MATCH (w)<-[:CO_AUTHORED]-(co:Person)
WHERE co IN students
RETURN w.title, collect(co.canonical_name);
```

#### 3.7.3 Show all CAA division heads and their dojos

**In SQL**:
```sql
SELECT div.metadata_json->>'division' AS division,
       p.canonical_name AS division_head,
       array_agg(d.name) AS dojos
FROM lineage_edges div
JOIN lineage_persons p ON div.src_id = p.node_id
LEFT JOIN lineage_dojos d ON d.federation_id = div.dst_id
  AND d.division = div.metadata_json->>'division'
WHERE div.edge_type = 'ORGANIZATIONAL_ROLE'
  AND div.dst_id = 'fed:caa'
  AND div.metadata_json->>'role' = 'division_head'
  AND div.valid_until IS NULL
GROUP BY division, p.canonical_name
ORDER BY division;
```

**In Neo4j**:
```cypher
MATCH (caa:Federation {name: "California Aikido Association"})
      <-[:DOJO_AFFILIATION {division: d}]-(dojo:Dojo),
      (head:Person)-[:ORGANIZATIONAL_ROLE {role: "division_head", division: d}]->(caa)
RETURN d AS division, head.canonical_name AS division_head, collect(dojo.name) AS dojos;
```

### 3.8 Implementation order (priority sequence)

| Step | Task | Dependencies | Est. effort |
|---|---|---|---|
| 1 | Add new `NodeType` and `RelationType` enum values to `models.py` | None | 30 min |
| 2 | Create new SQL tables (`lineage_*`, `dojo_raw`, `rank_history`, `dojo_affiliation_history`, `name_collisions`, `entity_reconciliation`, `person_candidate`) | Step 1 | 1 hour |
| 3 | Build `scripts/26_create_lineage_tables.py` — DDL migration script | Step 2 | 30 min |
| 4 | Build `src/storage/lineage_db.py` — typed CRUD for lineage tables with `valid_from`/`valid_to` versioning, `observed_at` timestamps | Step 2 | 3 hours |
| 5 | Build `src/search/disambiguator.py` — person/dojo name resolution with contextual signals, alias index, `person_candidate` queueing | Step 2 | 2 hours |
| 6 | Build `scripts/27_etl_dojo_directory.py` — full ETL: stage raw CSV → `dojo_raw`, clean+dedup by domain+city, create Dojo nodes, map `head_name` → Person, insert `HEAD_INSTRUCTOR` + `DOJO_AFFILIATION` edges | Steps 3, 4, 5 | 3 hours |
| 7 | Build `src/search/openlibrary_client.py` — Open Library API client | None | 1 hour |
| 8 | Build `src/search/google_books_client.py` — Google Books API client | None | 1 hour |
| 9 | Build `src/search/itunes_podcast_client.py` — iTunes + RSS podcast discovery | None | 2 hours |
| 10 | Build `scripts/28_resolve_books.py` — resolve all target persons' books via OL + Google Books | Steps 7, 8 | 1 hour |
| 11 | Build `scripts/29_discover_podcasts.py` — discover podcast episodes featuring target persons | Step 9 | 2 hours |
| 12 | Build `src/search/geocode_client.py` — geocoding with caching | None | 1 hour |
| 13 | Build `scripts/30_geocode_dojos.py` — batch geocode all dojo addresses | Step 12 | 1 hour |
| 14 | Build `scripts/31_caa_division_heads.py` — ingest CAA organizational structure with `ORGANIZATIONAL_ROLE` edges | Step 4 | 1 hour |
| 15 | Build `scripts/32_recursive_lineage_expansion.py` — depth-limited recursive student-of expansion | Steps 1–14 | 3 hours |
| 16 | Build `scripts/33_temporal_reconstruction.py` — graph state at date queries, lineage network snapshots over time | Step 4 | 2 hours |
| 17 | Add lineage query endpoints to Graph API (Flask) | Step 4 | 2 hours |
| 18 | Build `scripts/34_export_lineage_geojson.py` — export dojos as GeoJSON for map visualization | Step 13 | 1 hour |

### 3.9 Downstream analytics and visualization

**Pre-built query templates** (to expose as API endpoints):

```python
# API endpoint: GET /api/lineage/dojos?lineage=nadeau&state=CA
@app.route("/api/lineage/dojos")
def dojos_by_lineage():
    lineage = request.args.get("lineage")
    state = request.args.get("state")
    return db.query("""
        SELECT d.*, p.canonical_name AS instructor_name
        FROM lineage_dojos d
        LEFT JOIN lineage_persons p ON d.head_instructor = p.node_id
        WHERE d.lineage = ? AND (? IS NULL OR d.state = ?)
        ORDER BY d.country, d.state, d.city
    """, lineage, state, state)

# API endpoint: GET /api/lineage/coauthored?person_id=person:robert-nadeau
@app.route("/api/lineage/coauthored")
def coauthored_books():
    person_id = request.args.get("person_id")
    return db.query("""
        SELECT b.title, b.isbn_13, b.publish_date,
               array_agg(p.canonical_name) AS co_authors
        FROM lineage_books b
        JOIN lineage_edges e ON e.dst_id = b.node_id AND e.edge_type = 'CO_AUTHORED'
        JOIN lineage_persons p ON e.src_id = p.node_id
        WHERE b.node_id IN (
            SELECT dst_id FROM lineage_edges
            WHERE src_id = ? AND edge_type = 'CO_AUTHORED'
        ) AND e.src_id != ?
        GROUP BY b.node_id
    """, person_id, person_id)

# API endpoint: GET /api/lineage/tree?person_id=person:morihei-ueshua&depth=5
@app.route("/api/lineage/tree")
def lineage_tree():
    person_id = request.args.get("person_id")
    depth = int(request.args.get("depth", 5))
    return db.query("""
        WITH RECURSIVE lineage AS (
            SELECT ? AS person_id, 0 AS depth
            UNION ALL
            SELECT e.dst_id, l.depth + 1
            FROM lineage l
            JOIN lineage_edges e ON e.src_id = l.person_id AND e.edge_type = 'TEACHER_STUDENT'
            WHERE l.depth < ?
        )
        SELECT l.person_id, p.canonical_name, l.depth,
               d.name AS dojo_name, d.city, d.state, d.lat, d.lng
        FROM lineage l
        JOIN lineage_persons p ON l.person_id = p.node_id
        LEFT JOIN lineage_dojos d ON d.head_instructor = l.person_id
        ORDER BY l.depth, p.canonical_name
    """, person_id, depth)
```

**GeoJSON export for map visualization**:
```python
# scripts/33_export_lineage_geojson.py
def export_dojo_geojson(db, lineage_filter=None):
    """Export dojos as GeoJSON FeatureCollection for Leaflet/Mapbox."""
    dojos = db.query("SELECT * FROM lineage_dojos WHERE lat IS NOT NULL"
                     + (" AND lineage = ?" if lineage_filter else ""),
                     lineage_filter)
    
    features = []
    for d in dojos:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [d["lng"], d["lat"]]},
            "properties": {
                "name": d["name"],
                "city": d["city"],
                "state": d["state"],
                "lineage": d["lineage"],
                "website": d["website"],
                "head_instructor": d.get("instructor_name"),
                "federation": d.get("federation_id"),
            }
        })
    return {"type": "FeatureCollection", "features": features}
```

---

## Appendix A — Existing infrastructure to reuse

| Component | Path | Status |
|---|---|---|
| GraphDB (SQLite) | `src/storage/graph_db.py` | Working, 7,210 nodes |
| Graph models | `src/storage/models.py` | Working, needs new enum values |
| JSON export/import | `src/storage/json_export.py` | Working |
| Brave search client | `src/search/brave_search_client.py` | Working (0 quota on current key) |
| Bing search client | `src/search/bing_search_client.py` | Working (anti-bot after 1 query) |
| DuckDuckGo client | `src/search/duckduckgo_search_client.py` | Blocked by CAPTCHA |
| KG client | `src/search/kg_client.py` | Working (needs Cloud key, not Gemini) |
| Search cache | `src/search/search_cache.py` | Working (SQLite, 30-day TTL) |
| Quota tracker | `src/search/quota.py` | Working |
| Relationship searcher | `src/search/relationship_searcher.py` | Working |
| Fetch page (tiered) | `src/crawler/fetch_page.py` | Working (direct + Wayback fallback) |
| WorldStudioFinder dojo CSV | `data/audit/aikido_pilot_review.csv` | 1,390 rows, ready for ETL |
| WorldStudioFinder lineage patterns | `data/reference/aikido_lineage_patterns.json` | 10 lineages including `nadeau` |
| WorldStudioFinder studios DB | `data/processed/pipeline.db` | 104K studios, 17K schools |
| KG API key | Secret Manager `GOOGLE_API_KEY` | 39-char Cloud key, working |

## Appendix B — Key disambiguation rules

| Name | Disambiguator | Node ID | Context |
|---|---|---|---|
| Richard Moon | aikido | `person:richard-moon-aikido` | Aikido of Marin founder, 6th dan |
| Richard Moon | chef | `person:richard-moon-chef` | Unrelated |
| Richard Moon | law-professor | `person:richard-moon-law-professor` | Unrelated |
| Bob Noha | aikido | `person:bob-noha` | Aikido instructor (only one in graph) |
| Dan Millman | author | `person:dan-millman` | Author, aikido practitioner (only one in graph) |
| Robert Nadeau | aikido | `person:robert-nadeau` | 8th dan Shihan (only one in graph) |
| Peter Ralston | martial-arts | `person:peter-ralston` | Cheng Hsin founder (only one in graph) |
| George Leonard | author | `person:george-leonard` | Writer, aikido practitioner (only one in graph) |

## Appendix C — Wikipedia draft syntax and editorial guidance

> **Purpose**: Authoritative, current reference for drafting Wikipedia-style biographies of
> Story Graph subjects (Peter Ralston, Bob Noha, and future subjects). Applies to
> `docs/wikipedia-ralston-noha.md` and any successor draft files.
> **Scope**: Drafting and pre-submission review only. This project does **not** publish,
> submit, or edit live Wikipedia articles without explicit operator approval.
> **Authoritative sources reviewed**: Wikipedia policy/guideline pages fetched 2026-09-08 —
> [Wikipedia:Drafts](https://en.wikipedia.org/wiki/Wikipedia:Drafts),
> [Wikipedia:Articles for creation](https://en.wikipedia.org/wiki/Wikipedia:Articles_for_creation),
> [Wikipedia:Notability (people)](https://en.wikipedia.org/wiki/Wikipedia:Notability_(people)),
> [Wikipedia:Biographies of living persons](https://en.wikipedia.org/wiki/Wikipedia:Biographies_of_living_persons),
> [Wikipedia:Conflict of interest](https://en.wikipedia.org/wiki/Wikipedia:Conflict_of_interest),
> [Wikipedia:Citing sources](https://en.wikipedia.org/wiki/Wikipedia:Citing_sources),
> [Template:Draft article](https://en.wikipedia.org/wiki/Template:Draft_article),
> [Template:AfC submission](https://en.wikipedia.org/wiki/Template:AFC_submission),
> [Template:Cite web](https://en.wikipedia.org/wiki/Template:Cite_web).

### C.1 Draft lifecycle and namespace

- Drafts live in the **Draft namespace** (`Draft:Peter Ralston (martial artist)`), not mainspace.
  Drafts are excluded from search-engine indexing, which is intentional during development.
- A draft begins with `{{Draft article|<intended title>}}` at the top. This renders the
  "This is a draft article" banner and categorizes the page under
  [Category:Draft articles](https://en.wikipedia.org/wiki/Category:Draft_articles).
  Do **not** use `{{Draft article}}` in mainspace — it will not display there.
- When the draft is ready for review, replace the Draft article banner with
  `{{subst:submit}}` (or use the "Submit for review" button). This substitutes the
  [Template:AfC submission](https://en.wikipedia.org/wiki/Template:AFC_submission) banner,
  which places the draft in the
  [Articles for Creation](https://en.wikipedia.org/wiki/Wikipedia:Articles_for_creation)
  review queue. A yellow "Review waiting, please be patient" box confirms submission.
- **Do not add categories to drafts** — reviewers add categories upon acceptance. Stub
  templates (e.g. `{{US-martial-artist-bio-stub}}`) are acceptable but are also typically
  added/adjusted by the reviewer.
- **WikiProject banners** (e.g. `{{WikiProject Biography}}`) belong on the draft's **talk
  page**, not the draft itself. The AfC "Add tags to your draft" button wires these up.
  The current `docs/wikipedia-ralston-noha.md` places `{{WikiProject Biography}}` on the
  draft body — this should move to the talk page before submission.
- Drafts not edited for six months are routinely deleted under
  [WP:CSD#G13](https://en.wikipedia.org/wiki/Wikipedia:Criteria_for_speedy_deletion#G13);
  they can be recovered at WP:REFUND/G13.
- **Articles generated entirely by LLMs will be rejected** (per AfC). Drafts may be
  assembled with LLM assistance but must be reviewed, fact-checked, and rewritten by a
  human editor before submission.

### C.2 Lead section and headings

- The **lead** is the first paragraph, has no heading, and should establish notability,
  nationality, occupation, and the single most defining achievement. The subject's name
  is **bold** on first mention: `'''Peter Ralston''' is an American martial artist...`.
- Do not overstate. The lead summarizes what **independent reliable sources** say, not
  what the subject says about themselves.
- Headings use `== Title ==` (level 2). Subsections use `=== Sub ===`. Sentence case for
  headings: `== Early life and training ==`, not `== Early Life And Training ==`.
- Standard biography headings: *Early life*, *Career*, *Bibliography* (for authors),
  *Personal life* (only if independently sourced), *See also*, *References*,
  *External links*. Avoid trivial sections (e.g. "Connection to Aikido lineage" is too
  thin unless it has independent sourcing and substance).

### C.3 Wikilinks

- Link the first occurrence of a notable concept or person: `[[Aikido]]`,
  `[[Robert Nadeau (aikidoka)|Robert Nadeau]]` (piped link with disambiguator).
- Do not link to non-existent articles (red links) in drafts unless you intend to create
  them. Link to the disambiguated form only if the target exists: `[[Cheng Hsin]]` is a
  red link today — either remove it or pipe to a broader existing article.
- Avoid overlinking: link a term once per section, not every occurrence.

### C.4 Citations and `<ref>` tags

- Every contentious or likely-challenged claim needs an **inline citation** in a
  `<ref>` tag. Per [WP:V](https://en.wikipedia.org/wiki/Wikipedia:Verifiability),
  quotations and BLP claims always require citations.
- Named references for reuse: `<ref name="chenghsin-bio">{{cite web ... }}</ref>` then
  later `<ref name="chenghsin-bio" />`. The current draft uses this correctly.
- The references section uses `{{Reflist}}` (or `{{Reflist|2}}` for two columns). The
  current draft uses `{{Reflist}}` correctly.
- **Avoid citation overloading**: do not stack 3+ refs on a single trivial claim to
  manufacture the appearance of strong sourcing. One solid independent source beats
  three self-published ones.

### C.5 Citation templates — current parameter syntax

Use the [citation templates](https://en.wikipedia.org/wiki/Help:Citation_Style_1) per
CS1. Key templates and their current parameters:

**`{{cite web}}`** — for web pages:
```
{{cite web
  | url         =
  | title       =
  | website     =
  | publisher   =
  | last        =
  | first       =
  | date        =
  | access-date =
  | archive-url =
  | archive-date=
  | url-status  = live
}}
```
- Use `access-date` (hyphenated), **not** `accessdate`. The current draft uses
  `accessdate` — this is a **syntax fix needed** before submission (it still renders,
  but `access-date` is the current canonical form).
- `website` is the name of the site; `publisher` is the publishing organization. If the
  site name equals the publisher, prefer `website` and omit `publisher`.
- Add `archive-url` and `archive-date` for any source likely to change or disappear
  (personal sites, publisher pages, Medium). Set `|url-status=live` if the original is
  still live.

**`{{cite book}}`** — for books (use for the bibliography entries):
```
{{cite book
  | last    =
  | first   =
  | title   =
  | publisher=
  | location=
  | date    =
  | isbn    =
  | pages   =
}}
```

**`{{cite news}}`** — for newspaper/magazine articles:
```
{{cite news
  | last      =
  | first     =
  | title     =
  | newspaper =
  | date      =
  | url       =
  | access-date=
  | pages     =
}}
```

**`{{cite interview}}`** — for interviews (use for the MAYTT and Argus Courier pieces):
```
{{cite interview
  | last    =
  | first   =
  | interviewer=
  | title   =
  | work    =
  | date    =
  | url     =
  | access-date=
}}
```

### C.6 Bibliography formatting

- A bibliography list (`== Bibliography ==`) uses a bulleted list or a wikitable. The
  current draft uses a `{| class="wikitable sortable" ... |}` table — this is valid
  wikitext. Keep columns factual (Title, Year, Publisher). The "Subject" column in the
  Ralston draft is editorial/subjective — consider removing it or sourcing each entry.
- For each book, prefer a `{{cite book}}` reference over a bare table row so the entry
  is verifiable against Open Library or the publisher.

### C.7 External links

- `== External links ==` goes last, before stub templates. Format:
  `* [https://chenghsin.com Official Cheng Hsin website]`.
- Only link the subject's **official** site and major authoritative profiles (Open
  Library, publisher author page). Do not link to promotional pages, Amazon listings,
  or self-published blogs.
- The current Ralston draft links to a YouTube channel and an Amazon Australia listing
  indirectly via book citations — the YouTube channel link is acceptable if it is the
  subject's official channel; remove any retail/affiliate links.

### C.8 Infobox guidance

- Biographies of martial artists should use
  [Template:Infobox person](https://en.wikipedia.org/wiki/Template:Infobox_person)
  (or a specialized infobox if one exists). The current drafts have **no infobox** —
  add one before submission with: `name`, `birth_date`, `birth_place`,
  `occupation`, `known_for`, `website`. Only include fields that are independently
  sourced.
- Do not put unsourced or self-published personal details (birth date, family) in the
  infobox for a living person.

### C.9 Neutral point of view and attribution

- Attribute contested or self-reported claims in text: "According to his official
  biography..." or "His publisher's profile states..." rather than asserting them as
  fact. The current draft asserts "first non-Asian ever to win" as fact sourced only to
  chenghsin.com and a publisher page — this needs **independent** sourcing (news
  archives, martial-arts magazines) or must be attributed.
- Avoid promotional language: "historically significant achievement," "one of the
  founders of the consciousness movement," "profound spiritual awakening." Replace
  with neutral, sourced statements.
- No original research: do not synthesize a "Connection to Aikido lineage" from a
  single book listing. Each claim must trace to a reliable source.

### C.10 Reliable, independent, secondary sources

- [WP:GNG](https://en.wikipedia.org/wiki/Wikipedia:Notability#General_notability_guideline)
  requires **significant coverage** in **multiple** **independent** **secondary**
  **reliable** sources. Self-published, official, and promotional sources do not count
  toward notability (they can establish facts but not notability).
- Source tiers for this project:
  - **Independent secondary (counts toward notability)**: newspaper archives (Argus
    Courier profile), martial-arts magazines (Aikido Journal, Black Belt, Journal of
    Asian Martial Arts), book reviews in independent publications, academic coverage
    of the consciousness movement.
  - **Publisher/bibliographic (establishes facts, weak for notability)**: Open Library,
    Penguin NZ author page, Inner Traditions author page, Simon & Schuster author page.
  - **Self-published/official (establishes facts about the subject's own claims, does
    not establish notability)**: chenghsin.com, aikidopetaluma.com, nadeaushihan.com.
  - **User-generated/promotional (avoid for BLP claims)**: Medium/Authority Magazine,
    personal blogs, Goodreads, Amazon reviews. These are generally not reliable
    sources per
    [WP:USERG](https://en.wikipedia.org/wiki/Wikipedia:Reliable_sources#User-generated_content).
- The current Ralston draft leans heavily on chenghsin.com and publisher pages —
  **notability is not yet established**. The current Noha draft leans on
  aikidopetaluma.com and Medium — **notability is not yet established**. Both need
  independent secondary sourcing before submission.

### C.11 Biographies of living persons (BLP)

- Both Ralston and Noha are living. Per
  [WP:BLP](https://en.wikipedia.org/wiki/Wikipedia:Biographies_of_living_persons),
  all material about living persons must be written with the greatest care for
  verifiability, neutrality, and avoidance of original research.
- **Remove contentious material that is unsourced or poorly sourced immediately** — do
  not wait for a challenge. This includes rank claims, biographical details, and family
  information sourced only to the subject's own site.
- Self-published sources may be used for **limited** claims about the subject themselves
  (their own occupation, their own school) but **not** for third-party claims or
  contentious material. The subject's own rank claims (5th/6th/7th dan) sourced only to
  aikidopetaluma.com are acceptable as self-description but should be attributed:
  "According to his dojo's biography, Noha holds the rank of 7th dan."
- Do not publish personal details (home address, family members' names) beyond what
  independent reliable sources have published.

### C.12 Conflict of interest (COI) disclosure

- Per [WP:COI](https://en.wikipedia.org/wiki/Wikipedia:Conflict_of_interest), editors
  with a conflict of interest (including being paid, being a student/associate of the
  subject, or promoting the subject's organization) **must disclose** on the draft's
  talk page and **must use the AfC process** rather than creating mainspace articles
  directly.
- If this project's operator has a relationship with the subjects (student, collaborator,
  lineage member), that must be disclosed on the talk page before submission.
- **Articles generated entirely by LLMs will be rejected**. LLM-assisted drafts must be
  human-reviewed and rewritten. Disclose AI assistance if asked by a reviewer.

### C.13 Notability evidence — pre-submission checklist

Before submitting either draft, confirm:
- [ ] At least **two** independent, secondary, reliable sources provide **significant**
      (not trivial/passing) coverage of the subject.
- [ ] The "first non-Asian to win" championship claim (Ralston) is sourced to
      independent news or martial-arts magazine coverage, not only chenghsin.com.
- [ ] The 7th dan rank claim (Noha) is either attributed to the dojo's own page or
      sourced to an independent rank-promotion record (CAA, Aikikai).
- [ ] No claim relies solely on Medium/Authority Magazine or other user-generated
      platforms.
- [ ] The lead does not assert notability as fact — it summarizes what sources say.
- [ ] Promotional adjectives ("profound," "historically significant," "pioneer") are
      removed or attributed.

### C.14 Pre-submission validation steps

1. Run the draft through the
   [Wikipedia article wizard](https://en.wikipedia.org/wiki/Wikipedia:Articles_for_creation)
   or copy into `Draft:` namespace.
2. Fix `accessdate` → `access-date` in all `{{cite web}}` calls.
3. Move `{{WikiProject Biography}}` to the draft's talk page.
4. Add an `{{Infobox person}}` with independently-sourced fields.
5. Add `archive-url`/`archive-date` to self-published and publisher sources.
6. Remove or attribute every claim sourced only to a self-published/official source.
7. Remove the "Subject" column from the Ralston bibliography table or source each.
8. Remove the "Connection to Aikido lineage" section unless independently sourced.
9. Disclose any COI on the draft talk page.
10. Replace `{{Draft article}}` with `{{subst:submit}}` when ready for AfC review.

### C.15 Maintenance templates and categories (post-acceptance)

- Reviewers add categories upon acceptance — do not pre-add them.
- Stub templates (`{{US-martial-artist-bio-stub}}`) are acceptable in drafts but may be
  swapped for a more specific stub by the reviewer.
- If a draft is accepted and later needs cleanup, use maintenance templates like
  `{{BLP sources}}` (insufficient sourcing for a BLP), `{{COI}}` (conflict of interest),
  `{{Advert}}` (promotional tone). These are reviewer/operator tools, not draft-stage
  tags.

### C.16 Monthly refresh requirement

> **This section must be reviewed and refreshed at least once per calendar month.**

Wikipedia policy, templates, and AfC workflow change frequently (template parameters
are deprecated/renamed, submission processes are restructured, notability criteria are
amended). To keep this guidance accurate:

- **Cadence**: review this Appendix C on the first working day of each month.
- **Next review due**: 2026-10-01.
- **Last reviewed**: 2026-09-08.
- **Review process**:
  1. Re-fetch the authoritative Wikipedia pages listed in the header of this appendix
     (Drafts, AfC, Notability (people), BLP, COI, Citing sources, Template:Draft
     article, Template:AfC submission, Template:Cite web) and diff against the guidance
     here.
  2. Update parameter names, template usage, and policy citations if they have changed.
  3. Check for newly deprecated citation parameters (e.g. `accessdate` → `access-date`
     was one such migration) and update the draft files accordingly.
  4. Update the "Last reviewed" date and "Next review due" date.
  5. Commit the refresh with a message like
     `docs: monthly refresh of Wikipedia draft syntax guidance (Appendix C)`.
- **Do not** treat this guidance as permanently current. If a Wikipedia policy or
  template referenced here has been renamed, merged, or deprecated, update this section
  before relying on it for a new draft or submission.
