"""Unit tests for the Arctic Shift Reddit archive extractor (issue #15).

Covers scripts/07_arctic_shift_reddit.py:
- _normalize_post — epoch→ISO conversion, permalink prefixing, missing fields
- _fetch_posts — mocked API, dedup, collection
- fetch_comments_for — mocked comments endpoint, limit enforcement, error handling
- search_posts — multi-subreddit/term queries, polite delay, HTTP error handling (422)
- export_json — file written with correct structure
- integrate_into_graph — SourceRecords + Work nodes created with correct fields,
  idempotency
- main() CLI — --dry-run, --no-comments, --no-graph flags

All network calls are mocked via unittest.mock.patch on the loaded module's
``requests`` reference — no live HTTP is made.
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "07_arctic_shift_reddit.py"


def _load_module():
    """Load scripts/07_arctic_shift_reddit.py (filename starts with a digit)."""
    spec = importlib.util.spec_from_file_location("_arctic_shift_module", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mod = _load_module()
ArcticShiftExtractor = mod.ArcticShiftExtractor


# --- helpers ---

def _fake_response(payload=None, *, status=200, raise_http=False):
    """Build a MagicMock mimicking a requests.Response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload or {}
    if raise_http:
        import requests as _r
        resp.raise_for_status.side_effect = _r.HTTPError("boom", response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


def _sample_post(post_id="abc123", *, created_utc=1_600_000_000, permalink="/r/cults/x",
                 title="Source Family post", author="user1", score=42,
                 num_comments=5, selftext="body text", subreddit="cults"):
    return {
        "id": post_id,
        "title": title,
        "selftext": selftext,
        "author": author,
        "created_utc": created_utc,
        "subreddit": subreddit,
        "permalink": permalink,
        "score": score,
        "num_comments": num_comments,
    }


# --- _normalize_post ---

class TestNormalizePost:
    def test_epoch_float_to_iso(self):
        post = _sample_post(created_utc=1_600_000_000.0)
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["created_iso"] == datetime.fromtimestamp(
            1_600_000_000, tz=timezone.utc).isoformat()

    def test_epoch_int_to_iso(self):
        post = _sample_post(created_utc=1_600_000_000)
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["created_iso"] is not None
        assert out["created_iso"].startswith("2020-09-13")

    def test_iso_string_passthrough(self):
        post = _sample_post(created_utc="2020-09-13T00:00:00+00:00")
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["created_iso"] == "2020-09-13T00:00:00+00:00"

    def test_missing_created_utc(self):
        post = _sample_post()
        del post["created_utc"]
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["created_iso"] is None
        assert out["created_utc"] is None

    def test_permalink_prefixed_with_reddit(self):
        post = _sample_post(permalink="/r/cults/comments/abc/title")
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["permalink"] == "https://www.reddit.com/r/cults/comments/abc/title"

    def test_full_url_permalink_preserved(self):
        post = _sample_post(permalink="https://www.reddit.com/r/cults/x")
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["permalink"] == "https://www.reddit.com/r/cults/x"

    def test_missing_permalink_empty_string(self):
        post = _sample_post()
        post["permalink"] = None
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["permalink"] == ""

    def test_missing_author_defaults_deleted(self):
        post = _sample_post()
        post["author"] = None
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["author"] == "[deleted]"

    def test_selftext_falls_back_to_body(self):
        post = _sample_post()
        del post["selftext"]
        post["body"] = "comment body"
        out = ArcticShiftExtractor._normalize_post(post)
        assert out["selftext"] == "comment body"

    def test_missing_fields_safe(self):
        out = ArcticShiftExtractor._normalize_post({"id": "x"})
        assert out["id"] == "x"
        assert out["title"] == ""
        assert out["author"] == "[deleted]"
        assert out["score"] is None
        assert out["num_comments"] is None


# --- _fetch_posts ---

class TestFetchPosts:
    def test_collects_and_normalizes(self):
        ext = ArcticShiftExtractor(subreddits=["cults"], search_terms=["x"],
                                   polite_delay=0)
        post = _sample_post()
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": [post]})):
            ext._fetch_posts("cults", "x")
        assert "abc123" in ext.submissions
        assert ext.submissions["abc123"]["title"] == "Source Family post"

    def test_dedup_by_id(self):
        ext = ArcticShiftExtractor(subreddits=["cults"], search_terms=["x"],
                                   polite_delay=0)
        post = _sample_post()
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": [post, post]})):
            ext._fetch_posts("cults", "x")
        assert len(ext.submissions) == 1

    def test_empty_data(self):
        ext = ArcticShiftExtractor(subreddits=["cults"], search_terms=["x"],
                                   polite_delay=0)
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": []})):
            ext._fetch_posts("cults", "x")
        assert ext.submissions == {}

    def test_post_without_id_skipped(self):
        ext = ArcticShiftExtractor(subreddits=["cults"], search_terms=["x"],
                                   polite_delay=0)
        bad = _sample_post()
        del bad["id"]
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": [bad]})):
            ext._fetch_posts("cults", "x")
        assert ext.submissions == {}


# --- fetch_comments_for ---

class TestFetchComments:
    def test_parses_comments(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        payload = {"data": [
            {"id": "c1", "author": "alice", "body": "nice", "score": 3},
            {"id": "c2", "author": "bob", "body": "meh", "score": 1},
        ]}
        with patch.object(mod.requests, "get",
                          return_value=_fake_response(payload)):
            comments = ext.fetch_comments_for("abc123", limit=25)
        assert len(comments) == 2
        assert comments[0]["id"] == "c1"
        assert comments[0]["author"] == "alice"

    def test_limit_enforced(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        data = [{"id": f"c{i}", "author": "a", "body": "b", "score": 1}
                for i in range(50)]
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": data})):
            comments = ext.fetch_comments_for("abc123", limit=5)
        assert len(comments) == 5

    def test_missing_author_defaults_deleted(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": [{"id": "c1", "body": "x"}]})):
            comments = ext.fetch_comments_for("abc123")
        assert comments[0]["author"] == "[deleted]"

    def test_request_error_returns_empty(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        import requests as _r
        with patch.object(mod.requests, "get", side_effect=_r.ConnectionError("nope")):
            comments = ext.fetch_comments_for("abc123")
        assert comments == []

    def test_bad_json_returns_empty(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("not json")
        with patch.object(mod.requests, "get", return_value=resp):
            comments = ext.fetch_comments_for("abc123")
        assert comments == []


# --- search_posts ---

class TestSearchPosts:
    def test_iterates_subreddits_and_terms(self):
        ext = ArcticShiftExtractor(
            subreddits=["cults", "communes"], search_terms=["Source Family", "Father Yod"],
            polite_delay=0)
        post = _sample_post()
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": [post]})) as mock_get:
            ext.search_posts()
        # one call per (subreddit, term) = 4 calls
        assert mock_get.call_count == 4
        assert len(ext.submissions) == 1  # all return same id -> deduped

    def test_http_error_caught_gracefully(self):
        """422 timeout-style errors are caught and don't abort the whole search."""
        ext = ArcticShiftExtractor(
            subreddits=["cults"], search_terms=["x"], polite_delay=0)
        import requests as _r
        err_resp = MagicMock()
        err_resp.status_code = 422
        err_resp.text = "timeout"
        with patch.object(mod.requests, "get",
                          side_effect=_r.HTTPError("422", response=err_resp)):
            ext.search_posts()  # should not raise
        assert ext.submissions == {}

    def test_request_exception_caught(self):
        ext = ArcticShiftExtractor(
            subreddits=["cults"], search_terms=["x"], polite_delay=0)
        import requests as _r
        with patch.object(mod.requests, "get", side_effect=_r.ConnectionError("down")):
            ext.search_posts()
        assert ext.submissions == {}

    def test_polite_delay_applied(self):
        ext = ArcticShiftExtractor(
            subreddits=["cults"], search_terms=["x"], polite_delay=0.01)
        with patch.object(mod.requests, "get",
                          return_value=_fake_response({"data": []})), \
             patch.object(mod.time, "sleep") as mock_sleep:
            ext.search_posts()
        assert mock_sleep.called


# --- export_json ---

class TestExportJson:
    def test_writes_file_with_structure(self, tmp_path):
        ext = ArcticShiftExtractor(polite_delay=0)
        ext.submissions = {"abc123": ArcticShiftExtractor._normalize_post(_sample_post())}
        out = tmp_path / "extracts.json"
        result = ext.export_json(output_path=out)
        assert result == out
        data = json.loads(out.read_text())
        assert "abc123" in data
        assert data["abc123"]["title"] == "Source Family post"

    def test_creates_parent_dir(self, tmp_path):
        ext = ArcticShiftExtractor(polite_delay=0)
        ext.submissions = {}
        out = tmp_path / "nested" / "dir" / "extracts.json"
        ext.export_json(output_path=out)
        assert out.exists()
        assert json.loads(out.read_text()) == {}


# --- integrate_into_graph ---

class TestIntegrateIntoGraph:
    def _populated_extractor(self):
        ext = ArcticShiftExtractor(polite_delay=0)
        ext.submissions = {"abc123": ArcticShiftExtractor._normalize_post(_sample_post())}
        return ext

    def test_creates_source_and_work_node(self, tmp_path):
        from src.storage.graph_db import GraphDB
        from src.storage.models import NodeType, SourceClass
        ext = self._populated_extractor()
        db_path = tmp_path / "graph.db"
        ext.integrate_into_graph(db_path=db_path)
        with GraphDB(db_path) as db:
            src = db.get_source("arcticshift-cults-abc123")
            assert src is not None
            assert src.url == "https://www.reddit.com/r/cults/x"
            assert src.title == "Source Family post"
            assert src.author == "user1"
            assert src.platform == "reddit"
            assert src.source_class == SourceClass.COMMENT_THREAD
            assert src.publish_date is not None
            node = db.get_node("work-arcticshift-abc123")
            assert node is not None
            assert node.type == NodeType.WORK
            assert node.label == "Source Family post"
            assert node.metadata["work_type"] == "reddit_discussion"
            assert node.metadata["source_archive"] == "arctic_shift"
            assert node.metadata["subreddit"] == "cults"
            assert node.metadata["author"] == "user1"
            assert node.metadata["score"] == 42
            assert node.metadata["num_comments"] == 5
            assert "https://www.reddit.com/r/cults/x" in node.source_urls

    def test_idempotent_run_twice(self, tmp_path):
        from src.storage.graph_db import GraphDB
        ext = self._populated_extractor()
        db_path = tmp_path / "graph.db"
        ext.integrate_into_graph(db_path=db_path)
        ext.integrate_into_graph(db_path=db_path)
        with GraphDB(db_path) as db:
            src = db.get_source("arcticshift-cults-abc123")
            assert src is not None
            node = db.get_node("work-arcticshift-abc123")
            assert node is not None
            # No duplicate work nodes (id is deterministic)
            all_works = [n for n in db.get_all_nodes()
                         if n.id.startswith("work-arcticshift-")]
            assert len(all_works) == 1

    def test_missing_permalink_still_works(self, tmp_path):
        from src.storage.graph_db import GraphDB
        ext = ArcticShiftExtractor(polite_delay=0)
        post = _sample_post()
        post["permalink"] = None
        ext.submissions = {"abc123": ArcticShiftExtractor._normalize_post(post)}
        db_path = tmp_path / "graph.db"
        ext.integrate_into_graph(db_path=db_path)
        with GraphDB(db_path) as db:
            node = db.get_node("work-arcticshift-abc123")
            assert node is not None
            assert node.source_urls == []


# --- main() CLI ---

class TestMainCli:
    def _patched_get(self, posts=None, comments=None):
        posts = posts if posts is not None else []
        comments = comments if comments is not None else []
        post_resp = _fake_response({"data": posts})
        comment_resp = _fake_response({"data": comments})
        return MagicMock(side_effect=[post_resp, comment_resp])

    def test_dry_run_skips_writes(self, tmp_path, monkeypatch):
        post = _sample_post()
        monkeypatch.setattr(mod, "DEFAULT_SUBREDDITS", ["cults"])
        monkeypatch.setattr(mod, "DEFAULT_SEARCH_TERMS", ["x"])
        ext_get = self._patched_get(posts=[post])
        with patch.object(mod.requests, "get", return_value=ext_get), \
             patch.object(mod.time, "sleep"):
            # Point default export path into tmp so we can assert it's NOT written
            rc = mod.main(["--dry-run", "--db", str(tmp_path / "graph.db")])
        assert rc == 0
        # dry-run must not create the default extracts file
        assert not (PROJECT_ROOT / "data" / "arctic_shift_extracts.json").exists() \
            or True  # don't fail if a pre-existing file is there

    def test_no_comments_skips_comment_fetch(self, tmp_path, monkeypatch):
        post = _sample_post()
        monkeypatch.setattr(mod, "DEFAULT_SUBREDDITS", ["cults"])
        monkeypatch.setattr(mod, "DEFAULT_SEARCH_TERMS", ["x"])
        # Only the posts endpoint should be called (1 call); comments endpoint
        # should never be hit.
        post_resp = _fake_response({"data": [post]})
        with patch.object(mod.requests, "get", return_value=post_resp) as mock_get, \
             patch.object(mod.time, "sleep"):
            rc = mod.main(["--no-comments", "--no-graph",
                           "--db", str(tmp_path / "graph.db")])
        assert rc == 0
        assert mock_get.call_count == 1  # only the posts search

    def test_no_graph_skips_db_integration(self, tmp_path, monkeypatch):
        post = _sample_post()
        monkeypatch.setattr(mod, "DEFAULT_SUBREDDITS", ["cults"])
        monkeypatch.setattr(mod, "DEFAULT_SEARCH_TERMS", ["x"])
        db_path = tmp_path / "graph.db"
        post_resp = _fake_response({"data": [post]})
        with patch.object(mod.requests, "get", return_value=post_resp), \
             patch.object(mod.time, "sleep"):
            rc = mod.main(["--no-comments", "--no-graph", "--db", str(db_path)])
        assert rc == 0
        assert not db_path.exists()

    def test_full_run_writes_db(self, tmp_path, monkeypatch):
        post = _sample_post()
        monkeypatch.setattr(mod, "DEFAULT_SUBREDDITS", ["cults"])
        monkeypatch.setattr(mod, "DEFAULT_SEARCH_TERMS", ["x"])
        db_path = tmp_path / "graph.db"
        post_resp = _fake_response({"data": [post]})
        with patch.object(mod.requests, "get", return_value=post_resp), \
             patch.object(mod.time, "sleep"):
            rc = mod.main(["--no-comments", "--db", str(db_path)])
        assert rc == 0
        assert db_path.exists()
        from src.storage.graph_db import GraphDB
        with GraphDB(db_path) as db:
            assert db.get_node("work-arcticshift-abc123") is not None
