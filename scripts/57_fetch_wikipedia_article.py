#!/usr/bin/env python3
"""
Fetch a live Wikipedia article and save it as markdown with provenance.

Downloads the article via the Action API (action=parse, both wikitext and
rendered HTML), converts the rendered HTML to markdown with a small stdlib
HTMLParser-based converter, and writes the result to a local file whose
header records the page title, pageid, revid, retrieval date, and API URL
so the fetch is reproducible.

The output is reference material only — it is never ingested into the
graph and never posted back to Wikipedia (project policy; see
prompts/graph_to_wikipedia_update.md).

Usage:
    # Fetch by title
    python scripts/57_fetch_wikipedia_article.py "Robert Nadeau (aikidoka)" \
        --output docs/wikipedia-drafts/robert-nadeau-live-wikipedia.md

    # Fetch by URL (language inferred from the host)
    python scripts/57_fetch_wikipedia_article.py \
        "https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)" \
        --output docs/wikipedia-drafts/robert-nadeau-live-wikipedia.md

    # Also save the raw wikitext alongside
    python scripts/57_fetch_wikipedia_article.py "Robert Nadeau (aikidoka)" \
        --output out.md --wikitext-out out.wikitext
"""

import argparse
import html.parser
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent

USER_AGENT = (
    "story_graph/1.0 (research tool; "
    "https://github.com/biofool/story_graph)"
)
API_URL_TMPL = "https://{lang}.wikipedia.org/w/api.php"
API_PARAMS = {
    "action": "parse",
    "prop": "wikitext|text|sections|categories|properties|displaytitle|revid",
    "format": "json",
    "formatversion": "2",
    "redirects": "1",
}

HEADER_MARKER = "wikipedia-fetch"


class WikiFetchError(Exception):
    """Raised when the Wikipedia article cannot be fetched."""


def title_from_input(page: str) -> tuple[str, str]:
    """Parse a page argument into (lang, title).

    Accepts a bare title ("Robert Nadeau (aikidoka)") or a full URL
    ("https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)").
    """
    page = page.strip()
    m = re.match(
        r"^https?://([a-z][a-z0-9-]*)\.wikipedia\.org/wiki/(.+)$", page
    )
    if m:
        lang = m.group(1)
        title = unquote(m.group(2)).replace("_", " ")
        # Strip any fragment
        title = title.split("#", 1)[0]
        return lang, title
    return "en", page


def fetch_article(
    title: str, lang: str = "en", timeout: int = 30,
) -> dict:
    """Fetch a Wikipedia article via the Action API.

    Returns the 'parse' object from the API response. Raises
    WikiFetchError on network errors, HTTP errors, API errors
    (including missing/disambiguation-independent failures).
    """
    api_url = API_URL_TMPL.format(lang=lang)
    params = dict(API_PARAMS, page=title)
    try:
        resp = requests.get(
            api_url, params=params,
            headers={"User-Agent": USER_AGENT}, timeout=timeout,
        )
    except requests.RequestException as e:
        raise WikiFetchError(f"network error fetching {api_url}: {e}") from e

    if resp.status_code != 200:
        raise WikiFetchError(
            f"HTTP {resp.status_code} from {api_url} "
            f"for page '{title}'"
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise WikiFetchError(
            f"non-JSON response from {api_url} for page '{title}': {e}"
        ) from e

    if "error" in data:
        err = data["error"]
        code = err.get("code", "unknown")
        info = err.get("info", "")
        if code == "missingtitle":
            raise WikiFetchError(
                f"Wikipedia article not found: '{title}' "
                f"({lang}.wikipedia.org)"
            )
        raise WikiFetchError(f"Wikipedia API error {code}: {info}")

    if "parse" not in data:
        raise WikiFetchError(
            f"unexpected API response (no 'parse' key) for '{title}'"
        )
    return data["parse"]


def is_disambiguation(parse: dict) -> bool:
    """Check whether the fetched page is a disambiguation page."""
    props = parse.get("properties") or {}
    if "disambiguation" in props:
        return True
    for cat in parse.get("categories") or []:
        if "disambiguation" in (cat.get("category") or "").lower():
            return True
    return False


# --- Rendered HTML → markdown ----------------------------------------------
#
# Deliberately simple stdlib converter: good enough for the comparison
# stage (headings, paragraphs, lists, links, bold/italic, rough tables).
# Internal wiki links (/wiki/...) are flattened to their text; external
# links are kept as [text](url) so cited source URLs survive in the
# markdown. Footnote backlinks (#cite_note-...) are dropped but their
# "[n]" text is kept.


class _HTMLToMarkdown(html.parser.HTMLParser):
    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _SKIP_TAGS = {"script", "style", "noscript", "img"}
    # Elements identified by CSS class rather than tag name — edit links,
    # navboxes, and other chrome that isn't article content.
    _SKIP_CLASSES = (
        "mw-editsection", "navbox", "sister-bar", "noprint",
        "mw-jump-link", "ambox", "shortdescription",
    )
    _BLOCK_TAGS = {"p", "div", "section", "blockquote", "table",
                   "ul", "ol", "dl", "figure", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._list_stack: list[str] = []
        self._link_stack: list[str | None] = []
        self._skip_depth = 0
        self._class_skip_stack: list[str] = []
        self._pre_depth = 0

    def _emit(self, text: str) -> None:
        if self._skip_depth == 0 and not self._class_skip_stack:
            self._out.append(text)

    def _blank_line(self) -> None:
        # Collapse trailing whitespace and ensure a blank line boundary
        text = "".join(self._out)
        if not text.endswith("\n\n"):
            self._emit("\n\n" if text.strip() else "")

    def handle_starttag(self, tag, attrs):
        attr = dict(attrs)
        # Inside a class-skipped element: track same-tag nesting, ignore all
        if self._class_skip_stack:
            if tag == self._class_skip_stack[-1]:
                self._class_skip_stack.append(tag)
            return
        classes = attr.get("class") or ""
        if any(c in classes.split() for c in self._SKIP_CLASSES):
            self._class_skip_stack.append(tag)
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "pre":
            self._pre_depth += 1
            self._blank_line()
            return
        if tag in self._HEADING_TAGS:
            self._blank_line()
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "br":
            self._emit("\n")
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._blank_line()
        elif tag == "li":
            self._emit("\n" + "  " * (len(self._list_stack) - 1) + "- ")
        elif tag == "dt":
            self._emit("\n**")
        elif tag == "dd":
            self._emit("** — ")
        elif tag == "a":
            href = attr.get("href") or ""
            self._link_stack.append(href)
            if self._is_external(href):
                self._emit("[")
        elif tag in ("b", "strong"):
            self._emit("**")
        elif tag in ("i", "em"):
            self._emit("*")
        elif tag == "tr":
            self._emit("\n| ")
        elif tag in ("td", "th"):
            # cell separator (not at row start)
            text = "".join(self._out)
            if text and not text.rstrip().endswith("|") \
                    and not text.endswith("\n"):
                self._emit(" | ")
        elif tag in self._BLOCK_TAGS:
            self._blank_line()

    def handle_endtag(self, tag):
        if self._class_skip_stack:
            if tag == self._class_skip_stack[-1]:
                self._class_skip_stack.pop()
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "pre":
            self._pre_depth = max(0, self._pre_depth - 1)
            self._blank_line()
            return
        if tag in self._HEADING_TAGS or tag in self._BLOCK_TAGS:
            self._blank_line()
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._blank_line()
        elif tag == "a":
            href = self._link_stack.pop() if self._link_stack else None
            if href and self._is_external(href):
                self._emit(f"]({href})")
        elif tag in ("b", "strong"):
            self._emit("**")
        elif tag in ("i", "em"):
            self._emit("*")

    def handle_data(self, data):
        if self._skip_depth or self._class_skip_stack:
            return
        if self._pre_depth == 0:
            # Collapse runs of whitespace into single spaces
            data = re.sub(r"\s+", " ", data)
        self._emit(data)

    @staticmethod
    def _is_external(href: str) -> bool:
        return href.startswith("http://") or href.startswith("https://")

    def get_markdown(self) -> str:
        text = "".join(self._out)
        # Clean up: strip trailing spaces, collapse 3+ newlines
        lines = [ln.rstrip() for ln in text.split("\n")]
        text = "\n".join(lines)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip() + "\n"


def html_to_markdown(html_text: str) -> str:
    """Convert rendered Wikipedia HTML to markdown (stdlib only)."""
    parser = _HTMLToMarkdown()
    parser.feed(html_text)
    parser.close()
    return parser.get_markdown()


# --- Provenance header ------------------------------------------------------


def build_header(meta: dict) -> str:
    """Build the provenance comment block for the output file."""
    lines = [f"<!-- {HEADER_MARKER}"]
    for key in (
        "title", "pageid", "revid", "oldid_url", "page_url", "api_url",
        "lang", "retrieved", "redirected_from", "disambiguation", "format",
    ):
        if key in meta and meta[key] not in (None, ""):
            lines.append(f"{key}: {meta[key]}")
    lines.append("-->")
    return "\n".join(lines)


_HEADER_LINE_RE = re.compile(r"^([a-z_]+): (.*)$")


def parse_header(text: str) -> dict:
    """Parse the provenance header of a fetched article file back out.

    Returns a dict of the header fields, or {} if no header is present.
    """
    m = re.match(
        r"^<!-- " + re.escape(HEADER_MARKER) + r"\n(.*?)\n-->",
        text, re.DOTALL,
    )
    if not m:
        return {}
    meta = {}
    for line in m.group(1).split("\n"):
        kv = _HEADER_LINE_RE.match(line.strip())
        if kv:
            meta[kv.group(1)] = kv.group(2).strip()
    return meta


def render_output(parse: dict, meta: dict) -> str:
    """Assemble the output file: header + title + markdown body."""
    parts = [build_header(meta), ""]
    display = parse.get("displaytitle") or parse.get("title") or ""
    display = re.sub(r"<[^>]+>", "", display)
    parts.append(f"# {display}")
    parts.append("")
    parts.append(
        f"*Fetched {meta['retrieved']} — revision {meta.get('revid', '?')} "
        f"({meta.get('oldid_url', meta.get('page_url', ''))}). "
        f"Reference copy for local comparison only; "
        f"do not edit Wikipedia from this file.*"
    )
    parts.append("")
    parts.append(html_to_markdown(parse.get("text", "")))
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a live Wikipedia article as markdown with "
                    "provenance (local reference copy only)."
    )
    parser.add_argument(
        "page",
        help="Article title or full Wikipedia URL",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Write the markdown article to this file",
    )
    parser.add_argument(
        "--lang",
        default=None,
        help="Wikipedia language code (default: en, or inferred from URL)",
    )
    parser.add_argument(
        "--wikitext-out",
        type=Path,
        default=None,
        help="Also save the raw wikitext to this file",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30)",
    )

    args = parser.parse_args()

    url_lang, title = title_from_input(args.page)
    lang = args.lang or url_lang

    try:
        parse = fetch_article(title, lang=lang, timeout=args.timeout)
    except WikiFetchError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    final_title = parse.get("title", title)
    pageid = parse.get("pageid", "")
    revid = parse.get("revid", "")
    retrieved = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    redirects = parse.get("redirects") or []
    redirected_from = ""
    if redirects:
        # e.g. [{"from": "Robert Nadeau", "to": "Robert Nadeau (aikidoka)"}]
        redirected_from = " > ".join(
            r.get("from", "") for r in redirects if r.get("from")
        )
        print(
            f"Redirected: {redirected_from} -> {final_title}",
            file=sys.stderr,
        )

    disambig = is_disambiguation(parse)
    if disambig:
        print(
            f"WARNING: '{final_title}' is a disambiguation page, "
            f"not an article — output saved but probably not the "
            f"page you want.",
            file=sys.stderr,
        )

    quoted = quote(final_title.replace(" ", "_"), safe="()_")
    page_url = f"https://{lang}.wikipedia.org/wiki/{quoted}"
    meta = {
        "title": final_title,
        "pageid": pageid,
        "revid": revid,
        "oldid_url": (
            f"https://{lang}.wikipedia.org/w/index.php?"
            f"title={quoted}&oldid={revid}"
        ),
        "page_url": page_url,
        "api_url": (
            f"{API_URL_TMPL.format(lang=lang)}?action=parse&"
            f"page={quote(final_title)}&format=json&redirects=1"
        ),
        "lang": lang,
        "retrieved": retrieved,
        "redirected_from": redirected_from,
        "disambiguation": "true" if disambig else "",
        "format": "rendered-html-to-markdown (stdlib HTMLParser, "
                  "action=parse prop=text); wikitext not retained "
                  "unless --wikitext-out was used",
    }

    output = render_output(parse, meta)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    print(
        f"Fetched '{final_title}' revid={revid} -> {args.output}",
        file=sys.stderr,
    )

    if args.wikitext_out:
        args.wikitext_out.parent.mkdir(parents=True, exist_ok=True)
        args.wikitext_out.write_text(
            parse.get("wikitext", ""), encoding="utf-8",
        )
        print(f"Wikitext saved to {args.wikitext_out}", file=sys.stderr)


if __name__ == "__main__":
    main()
