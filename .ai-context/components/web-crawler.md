# Component: Web Crawler

**Path:** `src/crawler/web_crawler.py` (185 LOC)
**Type:** Infrastructure — data acquisition

## Responsibility

BFS web crawler with domain filtering and depth cap. Fetches pages via
`requests`, parses HTML with BeautifulSoup (lxml), extracts text +
outbound links, and respects allowed domains + configurable delay.

## Interface

```python
@dataclass
class CrawledPage:
    url: str
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)
    author: str | None = None
    publish_date: str | None = None
    status_code: int = 0
    error: str | None = None

class WebCrawler:
    def __init__(self, seed_urls, allowed_domains, max_depth=2,
                 max_pages=200, delay_seconds=3.0,
                 user_agent="story-graph-bot/0.1 (+research)", timeout=30)
    def crawl(self) -> list[CrawledPage]
```

## Execution Path (OBSERVED)

1. Initialize BFS queue with `(url, 0)` tuples for each seed URL
2. While queue not empty and `pages_crawled < max_pages`:
   a. Pop `(url, depth)` from queue front
   b. Strip URL fragment, skip if already visited
   c. Mark visited
   d. `_fetch(url)` with tenacity retry (3 attempts, exponential backoff
      2-10s)
   e. On exception: append `CrawledPage(error=...)`, continue
   f. On non-200: append error page, continue
   g. `_parse_page(url, html)`:
      - Extract title from `<title>`
      - Extract author from meta tags (3 selector patterns)
      - Extract publish_date from meta tags (4 selector patterns)
      - Extract text: prefer `<article>`/`<main>`/`<body>`, clean via
        `text_utils.clean_text()`
      - Extract links: resolve relative URLs, filter by allowed domains,
        deduplicate
   h. Append parsed page, increment `pages_crawled`
   i. If `depth < max_depth`: enqueue child links at `depth + 1`
   j. `time.sleep(delay_seconds)` — rate limiting
3. Return all pages (including error pages)

## Dependencies

| Dependency | Type | Evidence |
|---|---|---|
| `requests` | external | HTTP GET in `_fetch()` |
| `beautifulsoup4` + `lxml` | external | HTML parsing in `_parse_page()` |
| `tenacity` | external | `@retry` decorator on `_fetch()` |
| `src.utils.text_utils` | code | `clean_text`, `is_allowed_domain`, `resolve_url` |

## Consumers

| Consumer | How |
|---|---|
| `scripts/01_crawl_and_build_graph.py` | Instantiates WebCrawler, calls `crawl()` |
| `scripts/02_gemini_search.py` | `extract` subcommand creates single-page crawler |
| `tests/integration/test_cli_smoke.py` | Mocks `WebCrawler.crawl` for offline test |

## Failure Paths (OBSERVED)

- **Network exception:** Caught, logged, error page appended. Retry
  handled by tenacity (3 attempts).
- **Non-200 status:** Logged, error page appended. No retry for non-200.
- **No error handling for parse failures:** `_parse_page()` has no
  try/except — a malformed HTML could raise an unhandled exception
  from BeautifulSoup. (DEBT-001)

## Change Guidance

- **Allowed domains:** Configured in `config/settings.py` and passed
  to constructor. Adding domains is safe.
- **Crawl depth/pages:** CLI overrides via `--max-depth`/`--max-pages`.
  Defaults in settings.
- **Parser changes:** `_parse_page()` is the HTML extraction logic.
  Changes here affect all downstream extraction quality.
- **Rate limiting:** `delay_seconds` controls politeness. The tenacity
  retry has its own backoff (2-10s) independent of this.
