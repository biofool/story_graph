"""
Image capture: download image candidates found while crawling, dedupe by
content hash, and generate thumbnails.

Images are stored locally under a gitignored directory (default
``data/images/``) — the binary files are never tracked in git. Only
metadata (original URL, content hash, dimensions, alt text, mime type)
gets stored on the graph's Image nodes and exported to graph_snapshot/,
matching the rest of this repo's "SQLite/binaries local, JSONL tracked"
split (see src/storage/json_export.py).

The image node id is the sha256 of the image bytes, so capturing the same
image twice (same photo reused across pages, or re-running a rescan) is a
no-op: the file already exists on disk and the node upsert is idempotent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

_log = logging.getLogger(__name__)

# Absolute, anchored at the repo root (not left relative) because Flask's
# send_file() resolves a relative path against app.root_path (the directory
# containing the Flask app module, e.g. scripts/) rather than the process's
# cwd — a relative default here silently 404'd every thumbnail/image route
# in scripts/09_graph_api.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_IMAGES_DIR = _PROJECT_ROOT / "data" / "images"
THUMB_MAX_SIZE = (320, 320)
MIN_DIMENSION = 200  # skip spacer gifs, tracking pixels, nav icons
MAX_BYTES = 15 * 1024 * 1024  # refuse to download absurdly large "images"

_SKIP_EXTENSIONS = (".svg", ".ico")


@dataclass
class CapturedImage:
    """Metadata for a successfully captured (downloaded + thumbnailed) image."""
    content_hash: str
    original_url: str
    alt: str
    mime: str
    width: int
    height: int
    image_path: Path
    thumb_path: Path


def images_dir(base: Path | str = DEFAULT_IMAGES_DIR) -> Path:
    base = Path(base)
    (base / "thumbs").mkdir(parents=True, exist_ok=True)
    return base


def image_path_for(content_hash: str, ext: str, base: Path | str = DEFAULT_IMAGES_DIR) -> Path:
    return images_dir(base) / f"{content_hash}{ext}"


def thumb_path_for(content_hash: str, base: Path | str = DEFAULT_IMAGES_DIR) -> Path:
    return images_dir(base) / "thumbs" / f"{content_hash}.jpg"


def capture_image(
    url: str,
    alt: str = "",
    base_dir: Path | str = DEFAULT_IMAGES_DIR,
    timeout: int = 20,
    user_agent: str = "story-graph-bot/0.1 (+research)",
    session: requests.Session | None = None,
) -> CapturedImage | None:
    """Download one image, validate/filter it, save it + a thumbnail.

    Returns None (rather than raising) for any filtered-out or failed
    image — callers are expected to capture many images per page and
    should not abort the page on one bad image.
    """
    if url.lower().split("?")[0].endswith(_SKIP_EXTENSIONS):
        return None

    try:
        getter = session.get if session else requests.get
        resp = getter(url, headers={"User-Agent": user_agent}, timeout=timeout, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image/" not in content_type:
            return None
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_BYTES:
            return None
        data = resp.content
        if len(data) > MAX_BYTES:
            return None
    except Exception as e:
        _log.warning(f"Failed to fetch image {url}: {e}")
        return None

    from io import BytesIO

    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        _log.warning(f"Not a decodable image, skipping {url}: {e}")
        return None

    width, height = img.size
    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        return None

    import hashlib

    content_hash = hashlib.sha256(data).hexdigest()
    ext = _ext_for_format(img.format)

    img_path = image_path_for(content_hash, ext, base_dir)
    thumb_path = thumb_path_for(content_hash, base_dir)

    if not img_path.exists():
        img_path.write_bytes(data)

    if not thumb_path.exists():
        thumb = img.convert("RGB")
        thumb.thumbnail(THUMB_MAX_SIZE)
        thumb.save(thumb_path, format="JPEG", quality=80)

    return CapturedImage(
        content_hash=content_hash,
        original_url=url,
        alt=alt,
        mime=content_type.split(";")[0].strip(),
        width=width,
        height=height,
        image_path=img_path,
        thumb_path=thumb_path,
    )


def _ext_for_format(fmt: str | None) -> str:
    return {
        "JPEG": ".jpg",
        "PNG": ".png",
        "GIF": ".gif",
        "WEBP": ".webp",
        "BMP": ".bmp",
    }.get((fmt or "").upper(), ".img")
