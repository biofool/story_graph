#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.crawler.document_ocr import ocr_document, write_ocr_result

DEFAULT_TERMS = [
    "айкидо",
    "Федерация Айкидо СССР",
    "Федерации Айкидо СССР",
    "Всестилевая Федерация Айкидо СССР",
    "учредительная конференция",
    "Роберт Надо",
    "Robert Nadeau",
    "Ленкай",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run auditable page-level OCR on a periodical scan")
    parser.add_argument("source", help="Local PDF/image path or direct HTTP(S) document URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--term", action="append", dest="terms")
    parser.add_argument("--language", default="rus+eng")
    parser.add_argument("--tessdata-dir", type=Path)
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--max-pages", type=int, default=250)
    parser.add_argument("--max-mb", type=int, default=100)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = ocr_document(
        args.source,
        terms=args.terms or DEFAULT_TERMS,
        language=args.language,
        dpi=args.dpi,
        max_pages=args.max_pages,
        max_bytes=args.max_mb * 1024 * 1024,
        tessdata_dir=args.tessdata_dir,
    )
    write_ocr_result(result, args.output)
    matched_pages = sum(bool(page.matches) for page in result.pages)
    print(f"OCR complete: {len(result.pages)} pages, {matched_pages} pages with target terms")
    print(f"Result: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
