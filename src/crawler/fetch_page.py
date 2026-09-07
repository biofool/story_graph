"""
Tiered web page retrieval with archive fallback.

Retrieval strategy (most reliable first):

  Tier 1 — Direct fetch with full browser-like headers
      (User-Agent, Accept, Accept-Language, Accept-Encoding,
      Sec-Fetch-*, DNT, Upgrade-Insecure-Requests). Most sites that
      403 a bare bot User-Agent will serve a browser-like request.

  Tier 2 — Wayback Machine
      If the direct fetch fails (403/404/timeout/connection error), fall
      back to the Internet Archive's Wayback Machine availability API
      (https://archive.org/wayback/available) and fetch the closest
      archived snapshot. The Wayback toolbar markup is stripped before
      parsing so it does not pollute the extracted text.

  Tier 3 — Google cache / other archives
      (reserved; currently a no-op stub that returns None — kept as a
      seam so additional archive services can be plugged in later
      without changing the call sites).

Protocol-relative URLs (``//upload.wikimedia.org/...``) are normalized to
``https://...`` before any fetch so they do not fail with
"No scheme supplied".

The public entry point is :func:`fetch_page`, which returns a
:class:`~src.crawler.web_crawler.CrawledPage` — the same interface the
ingestion scripts and the BFS crawler use, so callers do not change.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from src.crawler.web_crawler import CrawledPage, ImageCandidate
from src.utils.text_utils import clean_text

_log = logging.getLogger(__name__)

# A current-ish desktop Chrome User-Agent. Sites that block bare bot
# User-Agents (AJJF, Jujitsu America, Facebook, etc.) generally serve
# this one.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Full browser-like header set. Including Sec-Fetch-* and
# Upgrade-Insecure-Requests makes the request indistinguishable from a
# real navigation at the header level, which is what most bot fences
# check.
BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": BROWSER_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Wayback Machine availability API.
WAYBACK_AVAILABILITY_API = "https://archive.org/wayback/available"

# Wayback wraps archived pages in a toolbar delimited by these HTML
# comments. We strip everything between them so the toolbar's text does
# not leak into the extracted page text.
_WAYBACK_TOOLBAR_START = "<!-- BEGIN WAYBACK TOOLBAR INSERT -->"
_WAYBACK_TOOLBAR_END = "<!-- END WAYBACK TOOLBAR INSERT -->"


def fix_protocol_relative_url(url: str) -> str:
    """Normalize a protocol-relative URL (``//host/...``) to ``https://``.

    ``requests`` raises ``MissingSchema: No scheme supplied`` for
    ``//upload.wikimedia.org/...`` style URLs (common in Wikipedia image
    markup). Prepend ``https:`` so they fetch correctly.
    """
    if url.startswith("//"):
        return "https:" + url
    return url


def _strip_wayback_toolbar(html: str) -> str:
    """Remove the Wayback Machine toolbar markup from archived HTML."""
    start = html.find(_WAYBACK_TOOLBAR_START)
    if start == -1:
        return html
    end = html.find(_WAYBACK_TOOLBAR_END, start)
    if end == -1:
        # No closing marker — drop from the start marker to EOF.
        return html[:start]
    end += len(_WAYBACK_TOOLBAR_END)
    return html[:start] + html[end:]


def _fetch_direct(
    url: str, timeout: int, headers: dict[str, str]
) -> requests.Response:
    """Tier 1: direct GET with browser-like headers."""
    return requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)


def _wayback_snapshot_url(url: str, timeout: int) -> str | None:
    """Ask the Wayback availability API for the closest archived snapshot URL."""
    api_url = f"{WAYBACK_AVAILABILITY_API}?url={quote(url, safe=':')}"
    try:
        resp = requests.get(api_url, timeout=timeout, headers=BROWSER_HEADERS)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        _log.warning("Wayback availability lookup failed for %s: %s", url, e)
        return None

    snapshots = data.get("archived_snapshots", {})
    closest = snapshots.get("closest")
    if not closest or not closest.get("available"):
        return None
    snap_url = closest.get("url")
    if not snap_url:
        return None
    # Wayback returns http:// snapshot URLs; upgrade to https for reliability.
    if snap_url.startswith("http://"):
        snap_url = "https://" + snap_url[len("http://"):]
    return snap_url


def _fetch_wayback(url: str, timeout: int) -> tuple[requests.Response, str] | None:
    """Tier 2: fetch the closest Wayback Machine snapshot for ``url``.

    Returns ``(response, snapshot_url)`` on success, or ``None`` if no
    archived snapshot exists or the snapshot fetch fails.
    """
    snap_url = _wayback_snapshot_url(url, timeout)
    if snap_url is None:
        _log.info("No Wayback snapshot available for %s", url)
        return None
    _log.info("Wayback fallback: %s -> %s", url, snap_url)
    try:
        resp = requests.get(
            snap_url, timeout=timeout, headers=BROWSER_HEADERS, allow_redirects=True
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        _log.warning("Wayback snapshot fetch failed for %s: %s", snap_url, e)
        return None
    return resp, snap_url


def _fetch_google_cache(url: str, timeout: int) -> tuple[requests.Response, str] | None:
    """Tier 3 (stub): Google cache / other archive services.

    Google's web cache (``webcache.googleusercontent.com``) was deprecated
    and is unreliable. This is a reserved seam so additional archive
    services can be plugged in later without changing call sites. It
    currently always returns ``None``.
    """
    return None


def _parse_html(
    url: str, html: str, status_code: int, *, extract_links: bool = False
) -> CrawledPage:
    """Parse fetched HTML into a :class:`CrawledPage`.

    Shared by every tier so the extraction (title, author, date, text,
    images) is identical regardless of where the HTML came from. Link
    extraction is opt-in (the BFS crawler does its own link handling;
    the ingestion scripts only need text + metadata + images).
    """
    soup = BeautifulSoup(html, "lxml")

    # Title
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Author (common meta tags)
    author = None
    for selector in [
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
        ("meta", {"name": "twitter:creator"}),
    ]:
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            author = tag["content"]
            break

    # Publish date
    publish_date = None
    for selector in [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"name": "DC.date"}),
        ("time", {}),
    ]:
        tag = soup.find(*selector)
        if tag:
            val = tag.get("content") or tag.get("datetime") or ""
            if val:
                publish_date = val
                break

    # Extract text — prefer article/main, fallback to body
    content_area = soup.find("article") or soup.find("main") or soup.find("body") or soup
    text = clean_text(str(content_area))

    # Links (opt-in — ingestion scripts pass extract_links=False)
    links: list[str] = []
    if extract_links:
        for a_tag in content_area.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href and not href.startswith(("javascript:", "mailto:", "#")):
                links.append(href)
        links = list(dict.fromkeys(links))

    # Extract images (og:image + in-content <img>)
    images: list[ImageCandidate] = []
    seen: set[str] = set()
    og_image = soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        img_url = og_image["content"].strip()
        if img_url and not img_url.startswith("data:"):
            img_url = fix_protocol_relative_url(img_url)
            seen.add(img_url)
            images.append(ImageCandidate(url=img_url, alt=title))

    for img_tag in content_area.find_all("img"):
        src = (img_tag.get("src") or img_tag.get("data-src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        if src.lower().split("?")[0].endswith((".svg", ".ico")):
            continue
        src = fix_protocol_relative_url(src)
        if src in seen:
            continue
        seen.add(src)
        images.append(ImageCandidate(url=src, alt=img_tag.get("alt", "").strip()))

    return CrawledPage(
        url=url,
        title=title,
        text=text,
        links=links,
        images=images,
        author=author,
        publish_date=publish_date,
        status_code=status_code,
    )


def fetch_page(
    url: str,
    *,
    timeout: int = 30,
    user_agent: str | None = None,
    use_browser_ua: bool = True,
    retry_archive: bool = False,
    extract_links: bool = False,
) -> CrawledPage:
    """Fetch and parse a single URL into a :class:`CrawledPage`.

    Tiered retrieval (most reliable first):

      1. Direct fetch with full browser-like headers.
      2. Wayback Machine archived snapshot (automatic on 403/404/timeout).
      3. Google cache / other archives (reserved stub).

    Parameters
    ----------
    url:
        URL to fetch. Protocol-relative URLs (``//host/...``) are
        normalized to ``https://`` automatically.
    timeout:
        Per-request timeout in seconds.
    user_agent:
        Override the User-Agent. When ``None`` and ``use_browser_ua`` is
        True (the default), a full browser header set is used. When
        ``None`` and ``use_browser_ua`` is False, a minimal bot UA is
        used.
    use_browser_ua:
        Use the full browser-like header set (default). Set False to
        send only a User-Agent (matches the legacy crawler behavior).
    retry_archive:
        Skip the direct fetch and go straight to the Wayback Machine.
        Useful for re-trying URLs known to be live only in the archive.
    extract_links:
        Populate ``CrawledPage.links`` from in-content ``<a href>`` tags.
        Default False — ingestion scripts only need text + metadata +
        images; the BFS crawler does its own domain-filtered link
        extraction.

    Returns
    -------
    CrawledPage
        Parsed page. On total failure (all tiers exhausted) raises
        :class:`requests.RequestException` so callers can handle it as
        before.

    Raises
    ------
    requests.RequestException
        If every tier fails.
    """
    url = fix_protocol_relative_url(url)

    # Build the header set for Tier 1.
    if user_agent is not None:
        headers = dict(BROWSER_HEADERS) if use_browser_ua else {}
        headers["User-Agent"] = user_agent
    elif use_browser_ua:
        headers = dict(BROWSER_HEADERS)
    else:
        headers = {"User-Agent": "story-graph-bot/0.1 (+research)"}

    # --- Tier 1: direct fetch -------------------------------------------
    if not retry_archive:
        try:
            resp = _fetch_direct(url, timeout, headers)
            if resp.status_code == 200:
                return _parse_html(
                    url, resp.text, resp.status_code, extract_links=extract_links
                )
            _log.warning(
                "Tier 1 direct fetch returned HTTP %d for %s",
                resp.status_code,
                url,
            )
        except requests.RequestException as e:
            _log.warning("Tier 1 direct fetch failed for %s: %s", url, e)
    else:
        _log.info("retry_archive=True — skipping direct fetch for %s", url)

    # --- Tier 2: Wayback Machine ----------------------------------------
    wb = _fetch_wayback(url, timeout)
    if wb is not None:
        resp, snap_url = wb
        html = _strip_wayback_toolbar(resp.text)
        page = _parse_html(
            snap_url, html, resp.status_code, extract_links=extract_links
        )
        # Keep the *original* URL as the page's identity (so the graph
        # records the canonical source URL, not the archive URL), but
        # note the archive provenance.
        page.url = url
        return page

    # --- Tier 3: Google cache / other archives (stub) -------------------
    gc = _fetch_google_cache(url, timeout)
    if gc is not None:
        resp, cache_url = gc
        return _parse_html(
            cache_url, resp.text, resp.status_code, extract_links=extract_links
        )

    # All tiers exhausted.
    raise requests.RequestException(
        f"All retrieval tiers failed for {url} "
        "(direct fetch + Wayback Machine fallback)"
    )
