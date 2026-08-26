"""Unit tests for WebCrawler's image-candidate extraction (_parse_page/_extract_images)."""

from __future__ import annotations

from src.crawler.web_crawler import WebCrawler

HTML = """
<html><head>
<title>Some Article</title>
<meta property="og:image" content="/social-preview.jpg">
</head>
<body>
<article>
<img src="https://cdn.example.com/photo1.jpg" alt="First photo">
<img data-src="/lazy/photo2.png" alt="Lazy loaded">
<img src="data:image/png;base64,AAAA" alt="inline data uri">
<img src="/icons/nav.svg" alt="nav icon">
<a href="https://example.com/other">link</a>
</article>
</body></html>
"""


def _crawler():
    return WebCrawler(seed_urls=[], allowed_domains={"example.com"})


class TestImageExtraction:
    def test_collects_og_image_and_content_images(self):
        page = _crawler()._parse_page("https://example.com/article", HTML)
        urls = [img.url for img in page.images]
        assert "https://example.com/social-preview.jpg" in urls
        assert "https://cdn.example.com/photo1.jpg" in urls
        assert "https://example.com/lazy/photo2.png" in urls

    def test_skips_data_uris_and_svg_icons(self):
        page = _crawler()._parse_page("https://example.com/article", HTML)
        urls = [img.url for img in page.images]
        assert not any(u.startswith("data:") for u in urls)
        assert not any(u.endswith(".svg") for u in urls)

    def test_alt_text_preserved(self):
        page = _crawler()._parse_page("https://example.com/article", HTML)
        by_url = {img.url: img.alt for img in page.images}
        assert by_url["https://cdn.example.com/photo1.jpg"] == "First photo"

    def test_og_image_uses_page_title_as_alt(self):
        page = _crawler()._parse_page("https://example.com/article", HTML)
        og = next(img for img in page.images if img.url.endswith("social-preview.jpg"))
        assert og.alt == "Some Article"

    def test_deduplicates_repeated_urls(self):
        html = HTML.replace(
            '<a href="https://example.com/other">link</a>',
            '<img src="https://cdn.example.com/photo1.jpg" alt="dup">',
        )
        page = _crawler()._parse_page("https://example.com/article", html)
        urls = [img.url for img in page.images]
        assert urls.count("https://cdn.example.com/photo1.jpg") == 1
