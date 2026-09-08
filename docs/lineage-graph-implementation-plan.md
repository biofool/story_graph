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

### 3.4 Disambiguation strategies

#### 3.4.1 Person name collisions

**Problem**: "Richard Moon" exists as 3+ different people (aikido instructor, chef, law professor).

**Solution**: `name_collisions` table + disambiguator suffix in node IDs.

```python
def resolve_person_by_name(name: str, context: str = "") -> str | None:
    """Resolve a name to a person node_id, handling collisions.
    
    1. Check name_collisions table for exact match + disambiguator
    2. If multiple matches and no disambiguator, return None (ambiguous)
    3. If single match, return the node_id
    4. If no match, try KG API for resolution
    """
    # Check existing collisions
    matches = db.query("SELECT node_id FROM name_collisions WHERE canonical_name = ?", name)
    if len(matches) == 1:
        return matches[0]["node_id"]
    elif len(matches) > 1:
        if context:
            # Try disambiguator
            for m in matches:
                if context.lower() in m.get("disambiguator", "").lower():
                    return m["node_id"]
        return None  # ambiguous — needs manual resolution
    return None
```

**Rules**:
- Node ID format: `person:<first-last>-<disambiguator>` (e.g., `person:richard-moon-aikido`)
- Disambiguator is the shortest unique qualifier: `aikido`, `chef`, `law-professor`
- `name_collisions` table tracks all known collisions and their resolution
- When a new person is created, check for existing nodes with the same canonical name → if found, require a disambiguator

#### 3.4.2 Multiple teachers per dojo

**Problem**: A dojo may have multiple instructors, or the head instructor may change over time.

**Solution**: `HEAD_INSTRUCTOR` edges with `valid_from`/`valid_until` dates. Current instructor = edge where `valid_until IS NULL`.

```sql
-- Get current head instructor for a dojo
SELECT p.canonical_name, e.valid_from
FROM lineage_edges e
JOIN lineage_persons p ON e.src_id = p.node_id
WHERE e.dst_id = 'dojo:aikido-of-marin'
  AND e.edge_type = 'HEAD_INSTRUCTOR'
  AND e.valid_until IS NULL;
```

#### 3.4.3 Dojo name collisions

**Problem**: "Aikido of San Francisco" might appear in multiple datasets with slightly different names.

**Solution**: Normalize by website domain (primary key) rather than name.

```python
def dedupe_dojo_by_website(dojo: dict, existing: dict) -> str | None:
    """Match dojo by website domain, then by name+city."""
    domain = extract_domain(dojo.get("website", ""))
    if domain and domain in existing["by_domain"]:
        return existing["by_domain"][domain]
    # Fallback: name + city match
    key = f"{dojo['name'].lower()}|{dojo.get('city','').lower()}"
    if key in existing["by_name_city"]:
        return existing["by_name_city"][key]
    return None
```

### 3.5 Versioning / time-series handling

**Principle**: Never overwrite historical data. Use `valid_from`/`valid_until` on edges and append-only history tables.

**Edge versioning**:
- When a person's rank changes, don't update the old edge — insert a new edge with `valid_from = today` and set the old edge's `valid_until = today`
- When a dojo changes federation, same pattern
- When a head instructor changes, same pattern

```python
def update_edge_with_version(db, src_id, edge_type, dst_id, new_metadata, valid_from):
    """Update an edge, closing the old version and opening a new one."""
    # Close existing current edge
    db.execute("""
        UPDATE lineage_edges 
        SET valid_until = ? 
        WHERE src_id = ? AND edge_type = ? AND dst_id = ? AND valid_until IS NULL
    """, (valid_from, src_id, edge_type, dst_id))
    
    # Insert new version
    db.execute("""
        INSERT INTO lineage_edges (src_id, edge_type, dst_id, valid_from, metadata_json, ...)
        VALUES (?, ?, ?, ?, ?, ...)
    """, (src_id, edge_type, dst_id, valid_from, json.dumps(new_metadata), ...))
```

**Rank history** (append-only):
```python
def record_rank_change(person_id, new_rank, awarded_date, awarded_by, source_url):
    """Record a rank promotion. Never update existing rank_history rows."""
    db.execute("""
        INSERT INTO rank_history (person_id, rank_level, awarded_by, awarded_date, source_url)
        VALUES (?, ?, ?, ?, ?)
    """, (person_id, new_rank, awarded_by, awarded_date, source_url))
    
    # Update the person's current_rank in lineage_persons (denormalized view)
    db.execute("""
        UPDATE lineage_persons SET current_rank = ?, updated_at = now()
        WHERE node_id = ?
    """, (new_rank, person_id))
```

**Dojo affiliation history** (append-only):
```python
def record_affiliation_change(dojo_id, new_fed_id, division, start_date, source_url):
    """Record a dojo changing federation/division."""
    # Close old affiliation
    db.execute("""
        UPDATE dojo_affiliation_history 
        SET end_date = ? 
        WHERE dojo_id = ? AND end_date IS NULL
    """, (start_date, dojo_id))
    
    # Insert new affiliation
    db.execute("""
        INSERT INTO dojo_affiliation_history (dojo_id, federation_id, division, start_date, source_url)
        VALUES (?, ?, ?, ?, ?)
    """, (dojo_id, new_fed_id, division, start_date, source_url))
```

### 3.6 Implementation order (priority sequence)

| Step | Task | Dependencies | Est. effort |
|---|---|---|---|
| 1 | Add new `NodeType` and `RelationType` enum values to `models.py` | None | 30 min |
| 2 | Create new SQL tables (`lineage_*`, `rank_history`, `dojo_affiliation_history`, `name_collisions`) | Step 1 | 1 hour |
| 3 | Build `scripts/26_create_lineage_tables.py` — DDL migration script | Step 2 | 30 min |
| 4 | Build `src/search/openlibrary_client.py` — Open Library API client | None | 1 hour |
| 5 | Build `src/search/google_books_client.py` — Google Books API client | None | 1 hour |
| 6 | Build `src/search/itunes_podcast_client.py` — iTunes + RSS podcast discovery | None | 2 hours |
| 7 | Build `scripts/27_resolve_books.py` — resolve all target persons' books via OL + Google Books | Steps 4, 5 | 1 hour |
| 8 | Build `scripts/28_discover_podcasts.py` — discover podcast episodes featuring target persons | Step 6 | 2 hours |
| 9 | Build `scripts/29_etl_dojo_directory.py` — ETL WorldStudioFinder CSV → lineage_dojos | Step 2 | 3 hours |
| 10 | Build `src/search/geocode_client.py` — geocoding with caching | None | 1 hour |
| 11 | Build `scripts/30_geocode_dojos.py` — batch geocode all dojo addresses | Step 10 | 1 hour |
| 12 | Build `scripts/31_caa_division_heads.py` — ingest CAA organizational structure | Step 2 | 1 hour |
| 13 | Build `src/search/disambiguator.py` — person/dojo name resolution | Step 2 | 2 hours |
| 14 | Build `src/storage/lineage_db.py` — typed CRUD for lineage tables with versioning | Step 2 | 3 hours |
| 15 | Build `scripts/32_recursive_lineage_expansion.py` — depth-limited recursive student-of expansion | Steps 1–13 | 3 hours |
| 16 | Add lineage query endpoints to Graph API (Flask) | Step 14 | 2 hours |
| 17 | Build `scripts/33_export_lineage_geojson.py` — export dojos as GeoJSON for map visualization | Step 11 | 1 hour |

### 3.7 Downstream analytics and visualization

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
