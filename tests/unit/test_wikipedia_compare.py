"""Unit tests for the Wikipedia compare pipeline (issue #66).

Tests the pure/deterministic functions of:
- scripts/57_fetch_wikipedia_article.py — title parsing, HTML→markdown
  conversion, provenance header round-trip, disambiguation detection
- scripts/58_compare_wikipedia_draft.py — signal extraction, statement
  filtering, corroboration scoring, edge-fact rendering, contradiction
  helpers, non-citable exclusion

All tests use fake data — no API keys or network required.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"


@pytest.fixture(scope="module")
def fetch():
    spec = importlib.util.spec_from_file_location(
        "wp_fetch", str(_SCRIPTS / "57_fetch_wikipedia_article.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cmp():
    spec = importlib.util.spec_from_file_location(
        "wp_cmp", str(_SCRIPTS / "58_compare_wikipedia_draft.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
#  57 — title parsing
# ---------------------------------------------------------------------------


class TestTitleFromInput:
    def test_bare_title(self, fetch):
        assert fetch.title_from_input("Robert Nadeau (aikidoka)") == (
            "en", "Robert Nadeau (aikidoka)",
        )

    def test_full_url(self, fetch):
        lang, title = fetch.title_from_input(
            "https://en.wikipedia.org/wiki/Robert_Nadeau_(aikidoka)"
        )
        assert lang == "en"
        assert title == "Robert Nadeau (aikidoka)"

    def test_non_english_url(self, fetch):
        lang, title = fetch.title_from_input(
            "https://fr.wikipedia.org/wiki/Aikido"
        )
        assert lang == "fr"
        assert title == "Aikido"


# ---------------------------------------------------------------------------
#  57 — HTML → markdown
# ---------------------------------------------------------------------------


class TestHTMLToMarkdown:
    def test_headings_and_paragraphs(self, fetch):
        html = "<h2>Career</h2><p>He taught aikido.</p><p>He travelled.</p>"
        md = fetch.html_to_markdown(html)
        assert "## Career" in md
        assert "He taught aikido." in md

    def test_external_link_kept_internal_flattened(self, fetch):
        html = (
            '<p><a href="/wiki/Aikido">aikido</a> see '
            '<a href="https://example.com/ref">the source</a></p>'
        )
        md = fetch.html_to_markdown(html)
        assert "[the source](https://example.com/ref)" in md
        assert "aikido" in md
        assert "(/wiki/Aikido)" not in md

    def test_fragment_link_keeps_text_only(self, fetch):
        html = '<p>text<sup><a href="#cite_note-1">[1]</a></sup></p>'
        md = fetch.html_to_markdown(html)
        assert "[1]" in md
        assert "#cite_note" not in md

    def test_editsection_skipped(self, fetch):
        html = (
            '<h2>Title<span class="mw-editsection">'
            '[<a href="/edit">edit</a>]</span></h2><p>Body.</p>'
        )
        md = fetch.html_to_markdown(html)
        assert "edit" not in md.replace("## Title", "")
        assert "Body." in md

    def test_script_and_style_skipped(self, fetch):
        html = "<style>.x{}</style><script>var a=1;</script><p>Hi.</p>"
        md = fetch.html_to_markdown(html)
        assert "var a" not in md and ".x{}" not in md
        assert "Hi." in md


# ---------------------------------------------------------------------------
#  57 — provenance header round-trip + disambiguation
# ---------------------------------------------------------------------------


class TestHeader:
    def test_round_trip(self, fetch):
        meta = {
            "title": "Robert Nadeau (aikidoka)", "pageid": 2028002,
            "revid": 1375338198,
            "oldid_url": "https://en.wikipedia.org/w/index.php?oldid=1375338198",
            "retrieved": "2026-09-24T00:00:00Z",
        }
        text = fetch.build_header(meta) + "\n\n# Title\n\nBody."
        parsed = fetch.parse_header(text)
        assert parsed["title"] == "Robert Nadeau (aikidoka)"
        assert parsed["revid"] == "1375338198"
        assert parsed["retrieved"] == "2026-09-24T00:00:00Z"

    def test_parse_header_absent(self, fetch):
        assert fetch.parse_header("# Just markdown\nNo header.") == {}

    def test_disambiguation_detected(self, fetch):
        parse = {"properties": {"disambiguation": ""}, "categories": []}
        assert fetch.is_disambiguation(parse) is True

    def test_disambiguation_by_category(self, fetch):
        parse = {"properties": {},
                 "categories": [{"category": "All_disambiguation_pages"}]}
        assert fetch.is_disambiguation(parse) is True

    def test_normal_article_not_disambiguation(self, fetch):
        parse = {"properties": {"wikibase_item": "Q1"},
                 "categories": [{"category": "American_aikidoka"}]}
        assert fetch.is_disambiguation(parse) is False


# ---------------------------------------------------------------------------
#  58 — signal extraction
# ---------------------------------------------------------------------------


class TestSignals:
    def test_cap_phrases(self, cmp):
        caps = cmp.extract_cap_phrases(
            "Nadeau taught at Lenkai Aikido Club in Leningrad."
        )
        assert "Lenkai Aikido Club" in caps

    def test_cap_phrases_drop_leading_stopwords(self, cmp):
        caps = cmp.extract_cap_phrases("In the Soviet Union he taught.")
        assert all(not c.startswith("In ") for c in caps)

    def test_years_exclude_decades(self, cmp):
        sig = cmp.extract_signals("in the 1990s and in 1962.", None)
        assert "1962" in sig["years"]
        assert "1990" not in sig["years"]

    def test_ordinals(self, cmp):
        sig = cmp.extract_signals("holding the rank of 8th dan", None)
        assert "8" in sig["ordinals"]

    def test_vocab_entity_match(self, cmp):
        import re
        vocab = re.compile(r"\b(Lenkai Aikido Club|Leningrad)\b", re.I)
        sig = cmp.extract_signals("a seminar at lenkai aikido club", vocab)
        assert "lenkai aikido club" in {
            e.lower() for e in sig["entities"]
        }

    def test_dedupe_signals(self, cmp):
        assert cmp.dedupe_signals(["Aikido", "aikido", "Judo"]) == [
            "Aikido", "Judo",
        ]

    def test_weak_anchor_set(self, cmp):
        weak = cmp.weak_anchor_set({"label": "Robert Nadeau"})
        assert "robert nadeau" in weak
        assert "nadeau" in weak
        assert "aikido" in weak


# ---------------------------------------------------------------------------
#  58 — statement extraction
# ---------------------------------------------------------------------------


LIVE_MD = """<!-- wikipedia-fetch
title: Test Article
revid: 123
-->

# Test Article

*Fetched 2026-01-01 — revision 123.*

## Career

He taught at Lenkai Aikido Club in Leningrad on 1990-10-27.

## References

- ^ Stone, John (1995). [Aikido In America](https://books.google.com/x).
"""


class TestLiveParsing:
    def test_body_strips_header(self, cmp):
        body = cmp.live_body(LIVE_MD)
        assert "title:" not in body
        assert "wikipedia-fetch" not in body
        assert "Lenkai Aikido Club" in body

    def test_statements_skip_reference_sections(self, cmp):
        stmts = cmp.article_statements(cmp.live_body(LIVE_MD))
        assert any("Lenkai Aikido Club" in s for s in stmts)
        assert not any("Aikido In America" in s for s in stmts)

    def test_hatnotes_skipped(self, cmp):
        body = "Not to be confused with Robert Nadeau (science historian).\n\nHe taught aikido for fifty years."
        stmts = cmp.article_statements(body)
        assert not any("science historian" in s for s in stmts)

    def test_cited_urls(self, cmp):
        urls = cmp.live_cited_urls(LIVE_MD)
        assert "https://books.google.com/x" in urls


# ---------------------------------------------------------------------------
#  58 — fact extraction + classification
# ---------------------------------------------------------------------------


class TestDraftFacts:
    def test_skips_references_and_headers(self, cmp):
        draft = (
            "'''Bob''' is a teacher.<ref name=\"ref1\"/>\n\n"
            "== Career ==\n\n"
            "Bob founded the Big Dojo in 1980.<ref name=\"ref2\"/>\n\n"
            "== References ==\n\n"
            "<references>\n"
            "<ref name=\"ref1\">[http://x.com src]</ref>\n"
            "</references>\n"
        )
        facts = cmp.draft_fact_lines(draft)
        texts = [f["text"] for f in facts]
        assert any("Big Dojo" in t for t in texts)
        assert not any("http://x.com" in t for t in texts)
        refs = [r for f in facts for r in f["refs"]]
        assert "ref2" in refs


class TestEdgeFacts:
    def _sub(self):
        return {
            "canonical": {"id": "person:bob", "label": "Bob Smith"},
            "nodes": [
                {"id": "person:bob", "type": "Person", "label": "Bob Smith"},
                {"id": "dojo:lenkai", "type": "Dojo",
                 "label": "Lenkai Aikido Club"},
                {"id": "person:alice", "type": "Person", "label": "Alice"},
            ],
            "edges": [
                {"src_id": "person:bob", "rel_type": "CO_APPEARANCE",
                 "dst_id": "dojo:lenkai",
                 "metadata": {"date": "1990-10-27", "city": "Leningrad",
                              "country": "USSR"}},
                {"src_id": "person:bob", "rel_type": "MEMBER_OF",
                 "dst_id": "person:alice", "metadata": {}},
            ],
        }

    def test_co_appearance_renders_date_city(self, cmp):
        facts = cmp.edge_facts(self._sub())
        lenkai = [f for f in facts if "Lenkai" in f["text"]]
        assert lenkai
        assert "1990-10-27" in lenkai[0]["text"]
        assert "Leningrad" in lenkai[0]["text"]
        assert lenkai[0]["priority"] == "normal"

    def test_member_of_person_flagged_suspect(self, cmp):
        facts = cmp.edge_facts(self._sub())
        alice = [f for f in facts if "Alice" in f["text"]]
        assert alice[0]["priority"] == "suspect"


class TestClassifyFact:
    def test_missing_and_present(self, cmp):
        live = " he taught aikido in california. "
        sig = {"entities": {"Lenkai"}, "caps": set(),
               "years": {"1990"}, "ordinals": set()}
        res = cmp.classify_fact("x", sig, live)
        assert res["missing"] == ["1990", "Lenkai"]
        sig2 = {"entities": set(), "caps": {"California"}, "years": set(),
                "ordinals": set()}
        res2 = cmp.classify_fact("x", sig2, live)
        assert res2["missing"] == []
        assert res2["present"] == ["California"]


class TestCorroborate:
    def _corpus(self):
        return [
            {"kind": "claim", "citable": True,
             "attribution": "http://src",
             "text": "Bob trained with Morihei Ueshiba at Hombu in 1962."},
        ]

    def test_strong_anchor_plus_second_signal_corroborates(self, cmp):
        corpus = self._corpus()
        import re
        vocab = re.compile(r"\b(Morihei Ueshiba|Hombu)\b", re.I)
        corpus_sigs = [cmp.extract_signals(i["text"], vocab) for i in corpus]
        sig = cmp.extract_signals(
            "In 1962 Bob went to Hombu to study with Morihei Ueshiba.",
            vocab,
        )
        res = cmp.corroborate("s", sig, corpus, corpus_sigs,
                              cmp.weak_anchor_set({"label": "Bob"}))
        assert res["verdict"].startswith("corroborated")

    def test_single_weak_anchor_not_corroborated(self, cmp):
        corpus = [{"kind": "claim", "citable": True,
                   "attribution": "http://src",
                   "text": "Bob liked aikido a lot."}]
        sig = {"entities": set(), "caps": {"Bob Liked"}, "years": set(),
               "ordinals": set()}
        corpus_sigs = [{"entities": set(), "caps": {"Bob Liked"},
                        "years": set(), "ordinals": set()}]
        res = cmp.corroborate(
            "s", sig, corpus, corpus_sigs,
            {"bob liked"},  # the shared phrase is weak
        )
        assert res["verdict"].startswith("partially")

    def test_no_signals_returns_none(self, cmp):
        res = cmp.corroborate("s", {"entities": set(), "caps": set(),
                                    "years": set(), "ordinals": set()},
                              [], [], set())
        assert res is None

    def test_non_citable_flagged(self, cmp):
        corpus = [{"kind": "claim", "citable": False,
                   "attribution": "kkron://x",
                   "text": "Bob trained with Morihei Ueshiba in 1962."}]
        corpus_sigs = [{"entities": {"Morihei Ueshiba"}, "caps": set(),
                        "years": {"1962"}, "ordinals": set()}]
        sig = {"entities": {"Morihei Ueshiba"}, "caps": set(),
               "years": {"1962"}, "ordinals": set()}
        res = cmp.corroborate("s", sig, corpus, corpus_sigs, set())
        assert "non-citable" in res["verdict"]


class TestContradictions:
    def test_find_contradictions_scoped_to_person_claims(self, cmp):
        sub = {
            "claims": [{"id": "claim:a"}],
            "nodes": [
                {"id": "claim:a", "type": "Claim", "label": "A"},
                {"id": "claim:b", "type": "Claim", "label": "B"},
                {"id": "claim:c", "type": "Claim", "label": "C"},
            ],
            "edges": [
                {"rel_type": "CONTRADICTS", "src_id": "claim:a",
                 "dst_id": "claim:b", "metadata": {"reason": "test"}},
                # unrelated pair — should be excluded
                {"rel_type": "CONTRADICTS", "src_id": "claim:x",
                 "dst_id": "claim:c", "metadata": {}},
            ],
        }
        out = cmp.find_contradictions(sub)
        assert len(out) == 1
        assert out[0]["src_id"] == "claim:a"
        assert out[0]["reason"] == "test"


class TestYearMismatches:
    def test_flags_mismatch_only_with_strong_anchor(self, cmp):
        corpus = [{"kind": "claim", "citable": True, "attribution": "x",
                   "text": "Bob joined the Lenkai club in 1985."}]
        corpus_sigs = [{"entities": {"Lenkai"}, "caps": set(),
                        "years": {"1985"}, "ordinals": set()}]
        live = [
            ("Bob visited the Lenkai club in 1990.",
             {"entities": {"Lenkai"}, "caps": set(), "years": {"1990"},
              "ordinals": set()}),
            ("Bob did aikido in 1970.",
             {"entities": set(), "caps": set(), "years": {"1970"},
              "ordinals": set()}),  # no strong anchor → skipped
        ]
        out = cmp.year_mismatches(live, corpus, corpus_sigs, weak={"aikido"})
        assert len(out) == 1
        assert out[0]["live_year"] == "1990"
        assert out[0]["graph_years"] == ["1985"]
