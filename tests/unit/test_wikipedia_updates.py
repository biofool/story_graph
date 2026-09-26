"""Unit tests for the Wikipedia update pipeline v2 (issue #80).

Covers the six observed failure modes the redesign targets:

1. ASU letter buried in a later/third table — the generated talk view has
   exactly ONE citable-sort table and every decided item appears in it.
2. Duplicated action lists — open action items live in the index view
   only; the talk and wikimarkup views carry no second copy.
3. Moon reliable-vs-incidental — a reliable-domain source with
   coverage_depth "incidental" renders with that depth visible, so a
   RELIABLE count cannot silently override the human notability call.
4. Varjan affiliation guard — visit/lead DOJO_AFFILIATION edges are
   filtered BEFORE candidate ranking in the compare report.
5. Changed article passage — a repair whose anchor no longer matches the
   cached live page is flagged rebase_needed.
6. Token match is never "accepted" — claim signals present in the live
   text yield possible_already_present; status stays 'proposed'.

All tests use fake data — no API keys, no network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = PROJECT_ROOT / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, str(_SCRIPTS / filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def render():
    return _load("wp_updates", "61_render_wikipedia_updates.py")


@pytest.fixture(scope="module")
def cmp():
    return _load("wp_cmp", "58_compare_wikipedia_draft.py")


def _item(**kw):
    base = {
        "id": "upd:test:x",
        "type": "addition",
        "claim": "A claim.",
        "decision": "citable",
        "rationale": "test",
        "status": "proposed",
        "history": [{"at": "2026-01-01", "status": "proposed"}],
        "evidence": [],
    }
    base.update(kw)
    return base


def _store(items, **article_kw):
    article = {"title": "T", "exists": False, "mode": "afc", "coi": "test"}
    article.update(article_kw)
    return {"subject": "test-subject", "article": article, "items": items}


# ---------------------------------------------------------------------------
# 1. ASU-letter-in-third-table → exactly one citable sort table
# ---------------------------------------------------------------------------


class TestSingleCitableTable:
    def test_one_table_every_item(self, render):
        items = [
            _item(id="upd:t:a", claim="First claim."),
            _item(id="upd:t:b", claim="Second claim.",
                  decision="citable-attributed"),
            _item(id="upd:t:c", claim="Excluded claim.",
                  type="excluded", decision="not-citable"),
            _item(id="upd:t:q", claim="Is this ok?", type="question"),
        ]
        ir = render.build_ir(_store(items))
        talk = render.render_talk(ir, {})
        # exactly one sort table (one header row)
        assert talk.count("| Claim | Source(s) | Verdict |") == 1
        # every non-question item's claim lands in that one table
        table = talk.split("## Citable / not-citable sort")[1]
        table = table.split("##")[0]
        for claim in ("First claim.", "Second claim.", "Excluded claim."):
            assert claim in table


# ---------------------------------------------------------------------------
# 2. Duplicated action lists → open actions exist in index only
# ---------------------------------------------------------------------------


class TestNoDuplicatedActionLists:
    def test_open_items_only_in_index(self, render):
        items = [_item(id="upd:t:a", claim="The one action.")]
        store = _store(items)
        store["open_tasks"] = ["do the thing"]
        ir = render.build_ir(store)
        index = render.render_index(ir, {})
        talk = render.render_talk(ir, {})
        markup = render.render_wikimarkup(ir, {})
        assert "## Open action items" in index
        assert "upd:t:a" in index and "do the thing" in index
        assert "## Open action items" not in talk
        assert "## Open action items" not in markup
        # each item id appears exactly once in the index
        assert index.count("upd:t:a") == 1


# ---------------------------------------------------------------------------
# 3. Reliable domain vs incidental coverage stays visible
# ---------------------------------------------------------------------------


class TestCoverageDepth:
    def test_reliable_incidental_renders_depth(self, render):
        items = [_item(
            id="upd:t:moon",
            claim="Moon mentioned in a Nadeau profile.",
            evidence=[{
                "source": "src:fake",
                "reliability": "reliable",
                "independence": "secondary",
                "coverage_depth": "incidental",
                "supports": "partial",
            }],
        )]
        render._SRC_META = {"src:fake": {"title": "Big Paper",
                                         "url": "https://x.test"}}
        ir = render.build_ir(_store(items))
        talk = render.render_talk(ir, {})
        markup = render.render_wikimarkup(ir, {})
        assert "reliable/secondary/incidental" in markup
        assert "incidental" in talk.split("Citable / not-citable")[1]

    def test_external_evidence_allowed(self, render):
        ev = {"external": {"url": "https://x.test/a", "title": "Ext"},
              "reliability": "marginal"}
        errors, warnings = render.validate(
            _store([_item(evidence=[ev], decision="citable-attributed")]),
            set())
        assert not errors
        assert warnings  # external sources warn — not in graph


# ---------------------------------------------------------------------------
# 4. Varjan affiliation guard — leads filtered before ranking
# ---------------------------------------------------------------------------


class TestVarjanGuard:
    @pytest.mark.parametrize("meta", [
        {"association": "frequent_visited_teacher"},
        {"context": "visited frequently per his site; outreach pending"},
        {"evidence_status": "unverified"},
        {"context": "city_or_country_lead"},
    ])
    def test_visit_leads_classified_lead(self, cmp, meta):
        pri = cmp.classify_edge_priority(
            "DOJO_AFFILIATION", "Dojo", meta, "dojo:x")
        assert pri == "lead"

    def test_real_affiliation_not_lead(self, cmp):
        pri = cmp.classify_edge_priority(
            "DOJO_AFFILIATION", "Dojo",
            {"context": "chief instructor since 1980"}, "dojo:x")
        assert pri == "normal"

    def test_email_sourced_edge_noncitable(self, cmp):
        pri = cmp.classify_edge_priority(
            "CO_APPEARANCE", "Dojo",
            {"source": "email://garth-jones/2026-09-24"}, "dojo:x")
        assert pri == "noncitable"

    def test_email_in_source_url_only_noncitable(self, cmp):
        # #81 §1: blank `source` left a leading space that broke
        # startswith — the filter must also fire on source_url
        pri = cmp.classify_edge_priority(
            "CO_APPEARANCE", "Dojo",
            {"source_url": "email://garth-jones/2026-09-24"}, "dojo:x")
        assert pri == "noncitable"

    def test_leadership_is_not_a_lead(self, cmp):
        # #81 §1: 'lead' substring matched 'leadership'/'pleaded'
        pri = cmp.classify_edge_priority(
            "DOJO_AFFILIATION", "Dojo",
            {"context": "took a leadership role at the dojo"}, "dojo:x")
        assert pri == "normal"

    def test_period_suffixed_signal_matches(self, cmp):
        # #81 §1: "Boulder Aikikai." never matched live text
        sig = cmp.extract_signals("He is head instructor of Boulder Aikikai.",
                                  None)
        live = " he is head instructor of boulder aikikai and teaches. "
        assert "Boulder Aikikai" in cmp.signals_present(
            sig["caps"], live)

    def test_lead_edges_not_ranked_in_partition(self, cmp):
        # #81 §1+§7: exclusion must hold in the actual ranking path
        sub = {
            "canonical": {"id": "person:p", "label": "P"},
            "nodes": [
                {"id": "person:p", "type": "Person", "label": "P"},
                {"id": "dojo:k", "type": "Dojo", "label": "Kohala Aikikai"},
            ],
            "edges": [{"src_id": "person:p", "rel_type": "DOJO_AFFILIATION",
                       "dst_id": "dojo:k",
                       "metadata": {"association": "frequent_visited_teacher",
                                    "context": "visited frequently"}}],
        }
        facts = cmp.edge_facts(sub)
        live_blob = " p never visited kohala. "
        missing, filtered, covered = cmp.partition_edge_facts(
            facts, live_blob, None)
        assert not missing                      # no candidate produced
        assert len(filtered["lead"]) == 1       # counted in diagnostics

    def test_filtered_counts_are_post_check(self, cmp):
        # an edge the live article already covers is 'covered', not
        # 'filtered' — counts account for what the article lacks
        sub = {
            "canonical": {"id": "person:p", "label": "P"},
            "nodes": [
                {"id": "person:p", "type": "Person", "label": "P"},
                {"id": "dojo:k", "type": "Dojo", "label": "Kohala Aikikai"},
            ],
            "edges": [{"src_id": "person:p", "rel_type": "DOJO_AFFILIATION",
                       "dst_id": "dojo:k",
                       "metadata": {"association": "frequent_visited_teacher"}}],
        }
        facts = cmp.edge_facts(sub)
        live = " p kohala aikikai visited frequently. "
        _, filtered, covered = cmp.partition_edge_facts(facts, live, None)
        assert filtered["lead"] == []
        assert covered["lead"] == 1

    def test_calendar_co_appearance_routine(self, cmp):
        pri = cmp.classify_edge_priority(
            "CO_APPEARANCE", "Dojo",
            {"source_url": "https://x.com/hiroshi-ikeda-seminar-calendar"},
            "event:y")
        assert pri == "routine"

    def test_person_target_still_suspect(self, cmp):
        pri = cmp.classify_edge_priority(
            "MEMBER_OF", "Person", {}, "person:z")
        assert pri == "suspect"

    def test_lead_edges_not_ranked(self, cmp):
        sub = {
            "canonical": {"id": "person:p", "label": "P"},
            "nodes": [
                {"id": "person:p", "type": "Person", "label": "P"},
                {"id": "dojo:k", "type": "Dojo", "label": "Kohala Aikikai"},
            ],
            "edges": [{"src_id": "person:p", "rel_type": "DOJO_AFFILIATION",
                       "dst_id": "dojo:k",
                       "metadata": {"association": "frequent_visited_teacher",
                                    "context": "visited frequently"}}],
        }
        facts = cmp.edge_facts(sub)
        assert facts[0]["priority"] == "lead"


# ---------------------------------------------------------------------------
# 5 + 6. Freshness: rebase detection and token-match-never-accepted
# ---------------------------------------------------------------------------


class TestFreshness:
    def _write_cache(self, tmp_path, revid, md_text, wt_text=None):
        md = tmp_path / "live.md"
        md.write_text(f"<!-- wikipedia-fetch\nrevid: {revid}\n-->\n\n"
                      + md_text)
        if wt_text is not None:
            (tmp_path / "live.wikitext").write_text(wt_text)
        return str(md)

    def test_rebase_needed_when_anchor_gone(self, render, tmp_path):
        cache = self._write_cache(
            tmp_path, 200, "The passage was rewritten entirely.")
        store = _store(
            [_item(id="upd:t:r", type="repair", claim="Fix it.",
                   proposal={"wikitext": "new text",
                             "base_revid": 200,
                             "anchor": {"section": "S",
                                        "passage": "the old passage"}})],
            exists=True, mode="talk_page",
            live_page={"cache_file": cache, "revid": 200})
        flags = render.freshness(store)["items"]["upd:t:r"]
        assert any("rebase_needed" in f for f in flags)

    def test_anchor_checked_against_wikitext(self, render, tmp_path):
        # markdown flattens [[X]] to X — the wikitext sibling is authoritative
        cache = self._write_cache(
            tmp_path, 200, "He established the dojo.",
            wt_text="He established [[Boulder Aikikai]] in 1980.")
        store = _store(
            [_item(id="upd:t:r", type="repair", claim="Fix link.",
                   proposal={"wikitext": "x", "base_revid": 200,
                             "anchor": {"passage": "[[Boulder Aikikai]]"}})],
            exists=True, mode="talk_page",
            live_page={"cache_file": cache, "revid": 200})
        flags = render.freshness(store)["items"]["upd:t:r"]
        assert "passage_intact" in flags

    def test_revid_drift_flagged_needs_review(self, render, tmp_path):
        cache = self._write_cache(tmp_path, 300, "Body.")
        store = _store(
            [_item(id="upd:t:d", claim="X.",
                   proposal={"wikitext": "x", "base_revid": 200})],
            exists=True, mode="talk_page",
            live_page={"cache_file": cache, "revid": 300})
        flags = render.freshness(store)["items"]["upd:t:d"]
        assert any("needs_review" in f and "300" in f and "200" in f
                   for f in flags)

    def test_token_match_never_accepted(self, render, tmp_path):
        # #81 §7: assert the flag lands in rendered output AND the store
        # stays 'proposed' — acceptance needs a recorded diff + reviewer
        cache = self._write_cache(
            tmp_path, 200,
            "He trained under Robert Tann in 1960 near South San Francisco.")
        item = _item(
            id="upd:t:m",
            claim="Taught by Robert Tann, South San Francisco, in 1960.",
            proposal={"wikitext": "x", "base_revid": 200})
        store = _store([item], exists=True, mode="talk_page",
                       live_page={"cache_file": cache, "revid": 200})
        fresh = render.freshness(store)
        flags = fresh["items"]["upd:t:m"]
        assert any("possible_already_present" in f for f in flags)
        assert item["status"] == "proposed"
        ir = render.build_ir(store)
        talk = render.render_talk(ir, fresh)
        assert "possible_already_present" in talk
        assert "ACCEPTED" not in talk

    def test_deduped_signals_no_double_count(self, render, tmp_path):
        # "1980" twice in the claim must not reach the 2-hit threshold
        cache = self._write_cache(tmp_path, 200, "In 1980 he moved.")
        item = _item(
            id="upd:t:y",
            claim="Moved in 1980; dojo founded 1980.",
            proposal={"wikitext": "x", "base_revid": 200})
        store = _store([item], exists=True, mode="talk_page",
                       live_page={"cache_file": cache, "revid": 200})
        flags = render.freshness(store)["items"]["upd:t:y"]
        assert not any("possible_already_present" in f for f in flags)

    def test_sentence_start_tokens_dropped(self, render):
        # "In May" matched live "In May" text and produced false positives
        assert "May" not in render.claim_signals("In May 2020 he taught")
        assert "Aikido Shimbokukai" in render.claim_signals(
            "hosted by Aikido Shimbokukai in May 2020")

    def test_rebase_holds_item_out_of_patch(self, render, tmp_path):
        cache = self._write_cache(tmp_path, 200, "Rewritten passage.")
        item = _item(
            id="upd:t:r", type="repair", claim="Fix it.",
            evidence=[{"external": {"url": "https://x.test", "title": "X"},
                       "reliability": "marginal"}],
            proposal={"wikitext": "new text", "base_revid": 200,
                      "anchor": {"passage": "the old passage"}})
        store = _store([item], exists=True, mode="talk_page",
                       live_page={"cache_file": cache, "revid": 200})
        fresh = render.freshness(store)
        out = render.render_wikimarkup(render.build_ir(store), fresh)
        assert "new text" not in out          # no paste block at all
        assert "Held" in out and "upd:t:r" in out


# ---------------------------------------------------------------------------
# Validator gates
# ---------------------------------------------------------------------------


class TestValidator:
    def test_not_citable_cannot_carry_wikitext(self, render):
        item = _item(decision="not-citable",
                     proposal={"wikitext": "sneaky"})
        errors, _ = render.validate(_store([item]), set())
        assert any("must not carry proposal.wikitext" in e for e in errors)

    def test_excluded_cannot_carry_wikitext(self, render):
        item = _item(type="excluded", decision="not-citable",
                     proposal={"wikitext": "sneaky"})
        errors, _ = render.validate(_store([item]), set())
        assert any("must not carry proposal.wikitext" in e for e in errors)

    def test_citable_patch_item_needs_proposal_and_revid(self, render):
        item = _item()  # live exists, no proposal at all
        errors, _ = render.validate(
            _store([item], exists=True, mode="talk_page"), set())
        assert any("missing proposal.wikitext" in e for e in errors)
        assert any("missing base_revid" in e for e in errors)

    def test_afc_draft_items_exempt_from_patch_requirement(self, render):
        item = _item()  # draft file carries the wording
        errors, _ = render.validate(
            _store([item], exists=True, mode="afc",
                   draft_wikitext_file="x.wikitext"), set())
        assert not any("proposal.wikitext" in e or "base_revid" in e
                       for e in errors)

    def test_repair_needs_anchor(self, render):
        item = _item(type="repair",
                     proposal={"wikitext": "x", "base_revid": 1,
                               "anchor": {"section": "S"}})
        errors, _ = render.validate(_store([item]), set())
        assert any("anchor.passage" in e for e in errors)

    def test_unresolvable_source_is_error(self, render):
        item = _item(evidence=[{"source": "src:missing"}])
        errors, _ = render.validate(_store([item]), set())
        assert any("not found in graph" in e for e in errors)

    def test_illegal_transition_rejected(self, render):
        item = _item(
            status="accepted",
            history=[{"at": "2026-01-01", "status": "proposed"},
                     {"at": "2026-01-02", "status": "accepted"}],
        )
        errors, _ = render.validate(_store([item]), set())
        assert any("illegal transition" in e for e in errors)

    def test_same_status_history_allowed(self, render):
        item = _item(
            override="lifecycle fixture",
            history=[{"at": "2026-01-01", "status": "proposed"},
                     {"at": "2026-01-02", "status": "proposed",
                      "note": "re-scoped"}],
        )
        errors, _ = render.validate(_store([item]), set())
        assert not errors

    def test_duplicate_ids_rejected(self, render):
        store = _store([_item(id="upd:t:x"), _item(id="upd:t:x")])
        errors, _ = render.validate(store, set())
        assert any("duplicate id" in e for e in errors)

    # -- #81 §2: evidence floor --

    def test_patch_item_needs_reliable_or_marginal_evidence(self, render):
        item = _item(evidence=[{"external": {"url": "https://x.test",
                                             "title": "X"},
                               "reliability": "unreliable"}])
        errors, _ = render.validate(_store([item]), set())
        assert any("no reliable|marginal evidence" in e for e in errors)

    def test_override_satisfies_floor(self, render):
        item = _item(evidence=[], override="mechanical repair")
        errors, _ = render.validate(_store([item]), set())
        assert not errors

    def test_citable_needs_graph_resolved_evidence(self, render):
        item = _item(decision="citable",
                     evidence=[{"external": {"url": "https://x.test",
                                             "title": "X"},
                                "reliability": "marginal"}])
        errors, _ = render.validate(_store([item]), set())
        assert any("graph-resolved evidence" in e for e in errors)

    def test_citable_attributed_allows_external_only(self, render):
        item = _item(decision="citable-attributed",
                     evidence=[{"external": {"url": "https://x.test",
                                             "title": "X"},
                                "reliability": "marginal"}])
        errors, _ = render.validate(_store([item]), set())
        assert not errors

    def test_citation_pending_not_in_patch(self, render):
        item = _item(decision="citation-pending",
                     proposal={"wikitext": "sneaky"})
        store = _store([item])
        errors, _ = render.validate(store, set())
        # citation-pending may carry draft wording, but never renders
        assert not any("proposal.wikitext" in e for e in errors)
        ir = render.build_ir(store)
        assert ir["patch_items"] == []

    # -- #81 §3: lifecycle --

    def test_history_must_start_proposed(self, render):
        item = _item(
            status="posted", override="lifecycle fixture",
            history=[{"at": "2026-01-01", "status": "posted"}])
        errors, _ = render.validate(_store([item]), set())
        assert any("must start at 'proposed'" in e for e in errors)

    def test_accepted_needs_diff_and_reviewer(self, render):
        item = _item(
            status="accepted", override="lifecycle fixture",
            history=[{"at": "2026-01-01", "status": "proposed"},
                     {"at": "2026-01-02", "status": "posted"},
                     {"at": "2026-01-03", "status": "accepted"}])
        errors, _ = render.validate(_store([item]), set())
        assert any("diff/revid" in e and "reviewer" in e for e in errors)

    def test_accepted_with_diff_and_reviewer_ok(self, render):
        item = _item(
            status="accepted", override="lifecycle fixture",
            history=[{"at": "2026-01-01", "status": "proposed"},
                     {"at": "2026-01-02", "status": "posted"},
                     {"at": "2026-01-03", "status": "accepted",
                      "revid": 1377000000, "reviewer": "kkron"}])
        errors, _ = render.validate(_store([item]), set())
        assert not errors

    def test_proposed_to_rejected_allowed(self, render):
        item = _item(
            status="rejected", override="lifecycle fixture",
            history=[{"at": "2026-01-01", "status": "proposed"},
                     {"at": "2026-01-02", "status": "rejected"}])
        errors, _ = render.validate(_store([item]), set())
        assert not errors

    # -- #81 §4: AfC draft gate --

    def test_missing_draft_file_is_error(self, render):
        errors, _ = render.validate(
            _store([_item()], exists=False, mode="afc",
                   draft_wikitext_file="does/not/exist.wikitext"),
            set(), {})
        assert any("draft_wikitext_file not found" in e for e in errors)

    def test_draft_ref_must_resolve_to_item_evidence(self, render,
                                                     tmp_path):
        draft = tmp_path / "d.wikitext"
        draft.write_text("He won.<ref>{{cite web |url=https://unbacked.test"
                         "/x}}</ref>")
        item = _item(decision="citable-attributed",
                     evidence=[{"external": {"url": "https://unbacked.test/x",
                                             "title": "X"},
                                "reliability": "marginal"}])
        # absolute path works: PROJECT_ROOT / "/abs" resolves to /abs
        ok_store = _store([item], exists=False, mode="afc",
                          draft_wikitext_file=str(draft))
        errors, _ = render.validate(ok_store, set(), {})
        assert not errors

        bad_store = _store([item], exists=False, mode="afc",
                           draft_wikitext_file=str(draft))
        bad_store["items"][0]["evidence"][0]["external"]["url"] = (
            "https://other.test/y")
        errors, _ = render.validate(bad_store, set(), {})
        assert any("draft cites https://unbacked.test/x" in e
                   for e in errors)

    def test_draft_gate_checks_inner_archive_url(self, render, tmp_path):
        draft = tmp_path / "d.wikitext"
        draft.write_text(
            "<ref>{{cite web |archive-url=https://web.archive.org/web/"
            "2020/https://real.test/page}}</ref>")
        item = _item(decision="citable-attributed",
                     evidence=[{"external": {"url": "https://real.test/page",
                                             "title": "X"},
                                "reliability": "marginal"}])
        store = _store([item], exists=False, mode="afc",
                       draft_wikitext_file=str(draft))
        errors, _ = render.validate(store, set(), {})
        assert not errors

    # -- #81 §5: passage hash --

    def test_base_passage_hash_mismatch_rejected(self, render):
        passage = "He trained under Robert Tann."
        import hashlib
        good = "sha1:" + hashlib.sha1(
            " ".join(passage.split()).encode()).hexdigest()
        item = _item(
            type="repair", override="fixture",
            proposal={"wikitext": "x", "base_revid": 200,
                      "anchor": {"passage": passage},
                      "base_passage_hash": good})
        errors, _ = render.validate(_store([item]), set())
        assert not errors
        item["proposal"]["anchor"]["passage"] = "Edited passage."
        errors, _ = render.validate(_store([item]), set())
        assert any("base_passage_hash" in e for e in errors)


class TestPolicyChecklist:
    """#81 §6: ticks are computed from the IR, never hardcoded."""

    def test_personal_comm_in_patch_item_unticks_check(self, render):
        ev = {"external": {"url": "email://x/1", "title": "Mail"},
              "reliability": "unreliable"}
        item = _item(decision="citable-attributed", evidence=[ev],
                     proposal={"wikitext": "x", "base_revid": 1})
        lines = render._policy_checklist(
            render.build_ir(_store([item])))
        assert any(l.startswith("- [ ] Personal communications")
                   for l in lines)

    def test_clean_store_ticks_all(self, render):
        ev = {"external": {"url": "https://x.test", "title": "X"},
              "reliability": "marginal", "independence": "secondary"}
        item = _item(decision="citable-attributed", evidence=[ev],
                     proposal={"wikitext": "x", "base_revid": 1})
        lines = render._policy_checklist(
            render.build_ir(_store([item], mode="talk_page")))
        assert all("- [x]" in l for l in lines if l.startswith("- ["))


# ---------------------------------------------------------------------------
# Golden test — rendered output must match committed views
# ---------------------------------------------------------------------------


class TestGoldenRendered:
    RENDERED = PROJECT_ROOT / "docs" / "wikipedia-drafts" / "rendered"

    @pytest.mark.parametrize("slug", [
        "hiroshi-ikeda", "robert-nadeau", "richard-moon",
        "peter-ralston", "bob-tann",
    ])
    def test_rendered_matches_store(self, render, slug):
        store = json.loads(
            (PROJECT_ROOT / "data" / "wikipedia-updates" / f"{slug}.json")
            .read_text())
        render._SRC_META = render.load_source_meta()
        errors, _ = render.validate(
            store, render.load_graph_ids(), render._SRC_META)
        assert errors == []
        fresh = render.freshness(store)
        ir = render.build_ir(store)
        for suffix, fn in (("", render.render_index),
                           ("-wikimarkup", render.render_wikimarkup),
                           ("-talk", render.render_talk)):
            committed = (self.RENDERED / f"{slug}{suffix}.md").read_text()
            assert fn(ir, fresh) == committed, (
                f"{slug}{suffix}.md drifted — re-render")


# ---------------------------------------------------------------------------
# Migration stores validate end-to-end against the real graph
# ---------------------------------------------------------------------------


class TestMigratedStores:
    STORE_DIR = PROJECT_ROOT / "data" / "wikipedia-updates"

    @pytest.mark.parametrize("slug", [
        "hiroshi-ikeda", "robert-nadeau", "richard-moon",
        "peter-ralston", "bob-tann",
    ])
    def test_store_validates_against_graph(self, render, slug):
        store = json.loads((self.STORE_DIR / f"{slug}.json").read_text())
        errors, _ = render.validate(store, render.load_graph_ids(),
                                    render.load_source_meta())
        assert errors == []

    @pytest.mark.parametrize("slug", [
        "hiroshi-ikeda", "robert-nadeau", "peter-ralston",
    ])
    def test_cached_pages_resolve(self, render, slug):
        store = json.loads((self.STORE_DIR / f"{slug}.json").read_text())
        live = store["article"].get("live_page")
        assert live, f"{slug} should have a cached live page"
        page = render.load_live(live["cache_file"])
        assert page.get("revid"), f"{slug} cache missing revid"
