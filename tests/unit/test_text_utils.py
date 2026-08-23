"""Unit tests for text utilities."""

from src.utils.text_utils import (
    clean_text,
    extract_date_from_text,
    get_domain,
    hash_url,
    is_allowed_domain,
    normalize,
    resolve_url,
    slugify,
    split_sentences,
    stable_hash,
)


class TestNormalize:
    def test_basic(self):
        assert normalize("Father Yod") == "father yod"

    def test_punctuation(self):
        assert normalize("Jim Baker, Jr.") == "jim baker jr"

    def test_whitespace(self):
        assert normalize("  multiple   spaces  ") == "multiple spaces"


class TestSlugify:
    def test_basic(self):
        assert slugify("James Edward Baker") == "james-edward-baker"

    def test_special_chars(self):
        assert slugify("Ya Ho Wa 13!") == "ya-ho-wa-13"


class TestHashUrl:
    def test_stable(self):
        assert hash_url("https://example.com") == hash_url("https://example.com")

    def test_different(self):
        assert hash_url("https://example.com") != hash_url("https://example.org")


class TestStableHash:
    def test_with_salt(self):
        h1 = stable_hash("claim text", "url1")
        h2 = stable_hash("claim text", "url2")
        assert h1 != h2

    def test_stable(self):
        assert stable_hash("text", "salt") == stable_hash("text", "salt")


class TestGetDomain:
    def test_basic(self):
        assert get_domain("https://example.com/page") == "example.com"

    def test_www(self):
        assert get_domain("https://www.example.com/page") == "example.com"

    def test_subdomain(self):
        assert get_domain("https://blog.blogspot.com/page") == "blog.blogspot.com"


class TestIsAllowedDomain:
    def test_allowed(self):
        assert is_allowed_domain("https://cultnews.com/page", {"cultnews.com"})

    def test_subdomain_allowed(self):
        assert is_allowed_domain("https://lifeinthesourcefamily.blogspot.com/", {"blogspot.com"})

    def test_not_allowed(self):
        assert not is_allowed_domain("https://evil.com/page", {"cultnews.com"})


class TestResolveUrl:
    def test_absolute(self):
        assert resolve_url("https://example.com", "https://other.com/page") == "https://other.com/page"

    def test_relative(self):
        assert resolve_url("https://example.com/dir/", "page.html") == "https://example.com/dir/page.html"


class TestCleanText:
    def test_strips_tags(self):
        assert clean_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strips_script(self):
        assert "script" not in clean_text("<script>alert(1)</script>Hello")

    def test_entities(self):
        assert clean_text("A &amp; B") == "A & B"


class TestExtractDate:
    def test_iso(self):
        assert extract_date_from_text("Event on 2013-08-25") == "2013-08-25"

    def test_slash_format(self):
        assert extract_date_from_text("On 08/25/2013") == "2013-08-25"

    def test_month_name(self):
        assert extract_date_from_text("August 25, 2013") == "2013-08-25"

    def test_no_date(self):
        assert extract_date_from_text("No date here") is None


class TestSplitSentences:
    def test_basic(self):
        sents = split_sentences("Hello world. This is a test sentence. Goodbye now.")
        assert len(sents) == 3  # All three sentences are > 10 chars
        assert "This is a test sentence" in sents

    def test_abbreviation(self):
        sents = split_sentences("Mr. Baker said hello there. He left the building.")
        assert len(sents) == 2

    def test_short_filtered(self):
        sents = split_sentences("Hi. This is longer enough.")
        assert all(len(s) > 10 for s in sents)
