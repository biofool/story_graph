#!/usr/bin/env python3
"""
Authority-domain sweep — enumerate high-authority martial-arts domains as
*collection targets* per subject, closing the gap in issue #75 (domains were
registered for post-hoc scoring in scripts/36 but never searched).

For each subject × domain in data/reference/authority_domains.json:

- collection.type == "wordpress_search": fetch the site's ?s= results pages
  (page 1 via search_url, pages 2+ via page_url), extract same-domain article
  URLs matching the domain's article_pattern, dedupe against source URLs
  already in graph_snapshot/sources.jsonl.
- collection.type == "web_search_fallback": emit the configured site: queries
  into the sweep file's "pending_queries" (to be run by the agent, script 02,
  or script 03 — the sweep itself does not call external search APIs).
- collection.type == "dedicated_crawler": recorded as covered; skipped.

Writes one JSON per subject per domain to data/reference/sweeps/<slug>/<domain>.json
plus a per-subject _summary.json.

Usage:
    python scripts/60_authority_domain_sweep.py "hiroshi ikeda"
    python scripts/60_authority_domain_sweep.py "richard moon" "robert nadeau" "peter ralston"
    python scripts/60_authority_domain_sweep.py "peter ralston" --domains aikidojournal.com
    python scripts/60_authority_domain_sweep.py "peter ralston" --query "ralston aikido"
"""

import argparse
import json
import logging
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "graph_snapshot"
REGISTRY_PATH = PROJECT_ROOT / "data" / "reference" / "authority_domains.json"
SWEEPS_DIR = PROJECT_ROOT / "data" / "reference" / "sweeps"

UA = {"User-Agent": "story_graph authority sweep (research; contact: github.com/biofool/story_graph)"}
DELAY_S = 1.0
MAX_PAGES = 5

# Path segments that are site furniture, not articles.
SKIP_SEGMENTS = re.compile(
    r"/(category|tag|author|wp-content|wp-includes|wp-json|feed|comments|page|cdn-cgi|about-us|faq|terms|privacy|contact)/",
    re.IGNORECASE,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("authority_sweep")


class LinkExtractor(HTMLParser):
    """Collect (href, anchor_text) pairs from raw HTML."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None


def fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("fetch failed %s: %s", url, exc)
        return None


def extract_article_links(html: str, domain: str, article_pattern: str | None) -> dict[str, str]:
    """Return {url: anchor_title} for same-domain article links."""
    parser = LinkExtractor()
    parser.feed(html)
    pat = re.compile(article_pattern) if article_pattern else None
    out: dict[str, str] = {}
    for href, text in parser.links:
        url = href.split("#")[0].rstrip("/") + "/"
        if domain not in url:
            continue
        if SKIP_SEGMENTS.search(url) or "?s=" in url or url == f"https://{domain}/" or url == f"https://www.{domain}/":
            continue
        if pat and not pat.match(url):
            continue
        if url not in out or (not out[url] and text):
            out[url] = text
    return out


def load_graph_urls() -> set[str]:
    urls: set[str] = set()
    path = SNAPSHOT_DIR / "sources.jsonl"
    if not path.exists():
        return urls
    for line in path.read_text().splitlines():
        try:
            u = json.loads(line).get("url")
        except json.JSONDecodeError:
            continue
        if u:
            urls.add(u.rstrip("/") + "/")
    return urls


def sweep_wordpress(subject: str, query: str, domain: str, cfg: dict) -> dict:
    article_pat = cfg["collection"].get("article_pattern")
    found: dict[str, str] = {}
    pages_fetched = 0
    for page in range(1, MAX_PAGES + 1):
        if page == 1:
            url = cfg["collection"]["search_url"].format(query=urllib.parse.quote(query))
        else:
            tpl = cfg["collection"].get("page_url")
            if not tpl:
                break
            url = tpl.format(query=urllib.parse.quote(query), page=page)
        html = fetch(url)
        if html is None:
            break
        pages_fetched += 1
        links = extract_article_links(html, domain, article_pat)
        new = {u: t for u, t in links.items() if u not in found}
        log.info("  %s p%d: %d links, %d new", domain, page, len(links), len(new))
        if not new:
            break
        found.update(new)
        time.sleep(DELAY_S)
    return {"pages_fetched": pages_fetched, "results": found}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("subjects", nargs="+", help="Person names, e.g. 'hiroshi ikeda'")
    ap.add_argument("--query", help="Override search query (default: subject name)")
    ap.add_argument("--domains", nargs="*", help="Limit to these registry domains")
    ap.add_argument("--registry", default=str(REGISTRY_PATH))
    args = ap.parse_args()

    registry = json.loads(Path(args.registry).read_text())["domains"]
    if args.domains:
        registry = {d: c for d, c in registry.items() if d in args.domains}
    graph_urls = load_graph_urls()
    log.info("graph has %d source URLs for dedupe", len(graph_urls))

    for subject in args.subjects:
        slug = subject.lower().replace(" ", "-")
        query = args.query or subject
        out_dir = SWEEPS_DIR / slug
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = {"subject": subject, "query": query, "domains": {}}

        for domain, cfg in registry.items():
            ctype = cfg.get("collection", {}).get("type")
            rec = {"tier": cfg.get("tier"), "collection_type": ctype}
            if ctype == "wordpress_search":
                res = sweep_wordpress(subject, query, domain, cfg)
                rec["pages_fetched"] = res["pages_fetched"]
                rec["results"] = [
                    {"url": u, "title": t, "in_graph": u in graph_urls}
                    for u, t in sorted(res["results"].items())
                ]
                rec["new_urls"] = sum(1 for r in rec["results"] if not r["in_graph"])
            elif ctype == "web_search_fallback":
                rec["pending_queries"] = [
                    q.format(subject=subject, query=query)
                    for q in cfg["collection"].get("queries", [])
                ]
            elif ctype == "dedicated_crawler":
                rec["note"] = "covered by: " + ", ".join(cfg["collection"].get("scripts", []))
            else:
                rec["note"] = "no collection method"
            summary["domains"][domain] = {
                k: v for k, v in rec.items() if k in ("tier", "collection_type", "pages_fetched", "new_urls", "note")
            } | {"results": len(rec.get("results", [])), "pending_queries": rec.get("pending_queries", [])}
            (out_dir / f"{domain.replace('.', '_')}.json").write_text(
                json.dumps({"subject": subject, "query": query, "domain": domain, **rec}, indent=1)
            )

        (out_dir / "_summary.json").write_text(json.dumps(summary, indent=1))
        total_new = sum(d.get("new_urls", 0) for d in summary["domains"].values())
        pending = sum(len(d.get("pending_queries", [])) for d in summary["domains"].values())
        print(f"{subject}: {total_new} new candidate URLs, {pending} pending site: queries -> {out_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
