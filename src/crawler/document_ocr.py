from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

from src.crawler.fetch_page import BROWSER_HEADERS

SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


@dataclass
class OCRMatch:
    term: str
    excerpt: str


@dataclass
class OCRPage:
    page: int
    text: str
    text_sha256: str
    matches: list[OCRMatch]


@dataclass
class OCRResult:
    source: str
    source_sha256: str
    media_type: str
    language: str
    pages: list[OCRPage]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required OCR executable is not installed: {name}")


def _download(url: str, destination: Path, max_bytes: int) -> None:
    with requests.get(url, headers=BROWSER_HEADERS, timeout=60, stream=True) as response:
        response.raise_for_status()
        content_length = int(response.headers.get("Content-Length", 0))
        if content_length > max_bytes:
            raise ValueError(f"Document exceeds {max_bytes} byte download limit")
        size = 0
        with destination.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError(f"Document exceeds {max_bytes} byte download limit")
                output.write(chunk)


def _source_path(source: str, directory: Path, max_bytes: int) -> Path:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        suffix = Path(parsed.path).suffix.lower() or ".bin"
        path = directory / f"source{suffix}"
        _download(source, path, max_bytes)
        return path
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"Document exceeds {max_bytes} byte limit")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_pages(path: Path, directory: Path, dpi: int) -> list[Path]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        _require_binary("pdftoppm")
        prefix = directory / "page"
        process = _run(["pdftoppm", "-jpeg", "-r", str(dpi), str(path), str(prefix)])
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "pdftoppm failed")
        return sorted(
            directory.glob("page-*.jpg"),
            key=lambda page: int(page.stem.rsplit("-", 1)[1]),
        )
    if suffix in SUPPORTED_IMAGE_SUFFIXES:
        output = directory / "page-1.png"
        with Image.open(path) as image:
            image.convert("RGB").save(output)
        return [output]
    raise ValueError(f"Unsupported document type: {suffix or 'unknown'}")


def _excerpt(text: str, match: re.Match[str], radius: int = 180) -> str:
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return " ".join(text[start:end].split())


def _find_matches(text: str, terms: list[str]) -> list[OCRMatch]:
    matches = []
    for term in terms:
        match = re.search(re.escape(term), text, flags=re.IGNORECASE)
        if match:
            matches.append(OCRMatch(term=term, excerpt=_excerpt(text, match)))
    return matches


def ocr_document(
    source: str,
    *,
    terms: list[str] | None = None,
    language: str = "rus+eng",
    dpi: int = 300,
    max_pages: int = 250,
    max_bytes: int = 100 * 1024 * 1024,
    tessdata_dir: Path | None = None,
) -> OCRResult:
    _require_binary("tesseract")
    terms = terms or []
    with tempfile.TemporaryDirectory(prefix="story-graph-ocr-") as temp:
        directory = Path(temp)
        path = _source_path(source, directory, max_bytes)
        pages = _render_pages(path, directory, dpi)
        if not pages:
            raise RuntimeError("No pages were rendered")
        if len(pages) > max_pages:
            raise ValueError(f"Document has {len(pages)} pages; limit is {max_pages}")
        results = []
        for number, page in enumerate(pages, 1):
            command = ["tesseract", str(page), "stdout", "-l", language]
            if tessdata_dir:
                command.extend(["--tessdata-dir", str(tessdata_dir)])
            process = _run(command)
            if process.returncode:
                raise RuntimeError(process.stderr.strip() or f"Tesseract failed on page {number}")
            text = process.stdout.strip()
            results.append(
                OCRPage(
                    page=number,
                    text=text,
                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    matches=_find_matches(text, terms),
                )
            )
        return OCRResult(
            source=source,
            source_sha256=_sha256(path),
            media_type=path.suffix.lower().lstrip("."),
            language=language,
            pages=results,
        )


def write_ocr_result(result: OCRResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
