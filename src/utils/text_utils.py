"""
Text utilities: normalization, URL hashing, HTML cleaning, date extraction.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urljoin


def normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace, remove punctuation."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def hash_url(url: str) -> str:
    """Create a short stable hash from a URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def stable_hash(text: str, salt: str = "") -> str:
    """Create a short stable hash from text + optional salt (e.g. URL)."""
    combined = f"{text}|{salt}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


def get_domain(url: str) -> str:
    """Extract the registered domain from a URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    # Strip leading 'www.'
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


def is_same_domain_or_subdomain(url: str, allowed_domain: str) -> bool:
    """Check if url belongs to allowed_domain or a subdomain of it."""
    domain = get_domain(url)
    if domain == allowed_domain:
        return True
    if domain.endswith("." + allowed_domain):
        return True
    return False


def is_allowed_domain(url: str, allowed_domains: set[str]) -> bool:
    """Check if url belongs to any of the allowed domains (or their subdomains)."""
    domain = get_domain(url)
    if not domain:
        return False
    for allowed in allowed_domains:
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False


def resolve_url(base_url: str, href: str) -> str:
    """Resolve a relative href against a base URL."""
    return urljoin(base_url, href)


def clean_text(html_text: str) -> str:
    """Strip HTML tags and collapse whitespace (basic, no parser dependency)."""
    # Remove script and style blocks
    html_text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Remove all tags
    text = re.sub(r"<[^>]+>", " ", html_text)
    # Decode common entities
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_date_from_text(text: str) -> Optional[str]:
    """Try to find a date string in text. Returns ISO format YYYY-MM-DD if found."""
    # Common date patterns
    patterns = [
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
        r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b",
        r"\b(\w+)\s+(\d{1,2}),?\s+(\d{4})\b",
    ]

    month_map = {
        "january": "01", "february": "02", "march": "03", "april": "04",
        "may": "05", "june": "06", "july": "07", "august": "08",
        "september": "09", "october": "10", "november": "11", "december": "12",
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "jun": "06", "jul": "07", "aug": "08", "sep": "09",
        "oct": "10", "nov": "11", "dec": "12",
    }

    for match in re.finditer(patterns[0], text):
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

    for match in re.finditer(patterns[1], text):
        month, day, year = match.group(1), match.group(2), match.group(3)
        return f"{year}-{int(month):02d}-{int(day):02d}"

    for match in re.finditer(patterns[2], text, re.IGNORECASE):
        month_name = match.group(1).lower()
        if month_name in month_map:
            day = match.group(2)
            year = match.group(3)
            return f"{year}-{month_map[month_name]}-{int(day):02d}"

    return None


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (basic, no NLP dependency)."""
    # Protect common abbreviations
    text = re.sub(r"\b(Mr|Mrs|Ms|Dr|vs|etc|Inc|Ltd|St)\.", r"\1<DOT>", text)
    # Split on sentence-ending punctuation
    sentences = re.split(r"[.!?]+", text)
    # Restore dots
    sentences = [s.replace("<DOT>", ".").strip() for s in sentences]
    return [s for s in sentences if len(s) > 10]
