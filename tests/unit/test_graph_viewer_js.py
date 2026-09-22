"""Smoke/structural tests for the graph viewer JavaScript (issue #12).

The graph viewer UI is client-side JavaScript embedded inline in
``scripts/09_graph_api.py`` as an f-string HTML template. There is no
browser-automation framework (Playwright/Selenium) in the repo, so these
tests take the pragmatic approach recommended in the issue: they fetch the
served HTML page via the Flask test client and assert that the expected
JavaScript functions, UI elements, data-attributes, and tooltips are
present and wired up correctly.

This catches regressions where a refactor accidentally drops a feature
(e.g. removes the ``data-search-node`` clickable-link wiring, the
PRECEDES toggle, the images-only filter, the connection ranking logic,
or the not_connected race-condition guard) even though it cannot exercise
the live DOM. A future iteration can extract the JS to separate ``.js``
files and add Playwright E2E tests on top of this structural baseline.
"""

import importlib.util
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "09_graph_api.py"


def _load_api_module():
    """Load scripts/09_graph_api.py as a module (filename starts with a digit)."""
    spec = importlib.util.spec_from_file_location("_graph_api_module_js", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


api_mod = _load_api_module()
app = api_mod.app


@pytest.fixture
def tmp_db(tmp_path):
    """Point the API server's global _DB at a fresh temp GraphDB."""
    from src.storage.graph_db import GraphDB

    db = GraphDB(tmp_path / "test_graph.db")
    saved_db, saved_snap = api_mod._DB, api_mod._SNAPSHOT_DIR
    api_mod._DB = db
    api_mod._SNAPSHOT_DIR = tmp_path / "snapshot"
    yield db
    db.close()
    api_mod._DB = saved_db
    api_mod._SNAPSHOT_DIR = saved_snap


@pytest.fixture
def client(tmp_db):
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def index_html(client):
    """Fetch the full HTML page served at / and cache it as text."""
    r = client.get("/")
    assert r.status_code == 200
    return r.data.decode("utf-8")


# --- Core JS functions present ---

class TestJsFunctionsPresent:
    """Every graph-viewer feature is backed by a named JS function embedded
    in the page. Asserting their presence guards against accidental removal
    during refactors of the f-string template.
    """

    @pytest.mark.parametrize("func", [
        "toggleNotConnected",      # not_connected marking (issue #11 race guard)
        "showNodeDetail",          # node detail panel
        "refreshGraph",            # graph data reload
        "filterNodes",             # search/filter box
        "searchNode",              # clickable connection links
        "toggleImagesOnly",        # images-only filter
        "togglePrecedesEdges",     # PRECEDES edge toggle
        "openLightbox",            # image lightbox
        "renderFallbackTable",     # Cytoscape-unavailable fallback
        "filterFallback",          # fallback table search
        "changeLayout",            # layout algorithm selector
    ])
    def test_function_defined(self, index_html, func):
        # Functions are declared as ``function name(`` in the f-string.
        assert re.search(rf"function\s+{func}\s*\(", index_html), \
            f"JS function '{func}' not found in served HTML"


# --- Tooltips (title attributes) on toolbar buttons ---

class TestTooltips:
    """Toolbar buttons carry ``title=`` tooltips that explain each control.
    These are the user-facing help text for the filters/toggles.
    """

    @pytest.mark.parametrize("button_id,keyword", [
        ("images-toggle", "Images only"),
        ("precedes-toggle", "PRECEDES"),
        ("filter-toggle", "Degree filter"),
        ("layout-select", "Layout algorithm"),
    ])
    def test_button_has_tooltip(self, index_html, button_id, keyword):
        # Find the element with the given id and verify it has a title attr
        # whose value mentions the keyword.
        m = re.search(
            rf'id="{button_id}"[^>]*\s+title="([^"]*)"', index_html)
        assert m, f"button #{button_id} missing a title= tooltip"
        assert keyword.lower() in m.group(1).lower(), \
            f"tooltip for #{button_id} does not mention '{keyword}': {m.group(1)!r}"

    def test_fit_button_has_tooltip(self, index_html):
        """The Fit button has no id but carries a tooltip and calls fitGraph()."""
        m = re.search(r'onclick="fitGraph\(\)"[^>]*\s+title="([^"]*)"', index_html)
        assert m, "Fit button missing a title= tooltip"
        assert "fit" in m.group(1).lower()


# --- Filters: images-only, PRECEDES toggle, degree/show-all ---

class TestFilters:
    def test_images_only_toggle_wired(self, index_html):
        """The images-only button calls toggleImagesOnly() and starts off."""
        assert 'id="images-toggle"' in index_html
        assert "onclick=\"toggleImagesOnly()\"" in index_html
        # State variable defaults to false (filter off)
        assert re.search(r"var\s+imagesOnlyMode\s*=\s*false", index_html)

    def test_precedes_toggle_wired(self, index_html):
        """The PRECEDES toggle calls togglePrecedesEdges() and defaults hidden."""
        assert 'id="precedes-toggle"' in index_html
        assert "onclick=\"togglePrecedesEdges()\"" in index_html
        assert re.search(r"var\s+hidePrecedesEdges\s*=\s*true", index_html)

    def test_precedes_edges_filtered_in_render(self, index_html):
        """PRECEDES edges are skipped during rendering when hidden."""
        assert "hidePrecedesEdges" in index_html
        assert "PRECEDES" in index_html

    def test_search_filter_wired(self, index_html):
        """The search box calls filterNodes() on input."""
        assert 'id="search"' in index_html
        assert "oninput=\"filterNodes()\"" in index_html


# --- Connection ranking (degree + temporal proximity) ---

class TestConnectionRanking:
    """showNodeDetail ranks a node's connections by degree (most connected
    first) with a temporal-proximity tie-break, then shows the top 20.
    """

    def test_degree_sort_present(self, index_html):
        # The sort comparator compares a.degree / b.degree
        assert re.search(r"aDeg\s*=\s*a\.degree\s*\|\|\s*0", index_html)
        assert re.search(r"bDeg\s*=\s*b\.degree\s*\|\|\s*0", index_html)
        assert "bDeg - aDeg" in index_html  # descending by degree

    def test_temporal_tiebreak_present(self, index_html):
        assert "_extractDate" in index_html
        assert "nodeDate" in index_html
        # temporal proximity diff comparison
        assert "Math.abs(aDate - nodeDate)" in index_html or \
               "Math.abs(aDate-nodeDate)" in index_html

    def test_top20_limit(self, index_html):
        assert "ranked.slice(0, 20)" in index_html
        assert "Showing top 20 of" in index_html


# --- Clickable links (data-search-node, no inline onclick) ---

class TestClickableLinks:
    """Connection links are clickable and navigate to the connected node via
    a data-attribute (data-search-node) wired up with addEventListener,
    avoiding inline onclick / XSS risk.
    """

    def test_conn_link_class_present(self, index_html):
        assert "class=\"conn-link\"" in index_html

    def test_data_search_node_attribute(self, index_html):
        assert 'data-search-node=' in index_html

    def test_search_node_wiring_via_add_event_listener(self, index_html):
        """The click handler is attached via addEventListener, not inline onclick."""
        assert "querySelectorAll('[data-search-node]')" in index_html
        assert "addEventListener('click'" in index_html
        assert "searchNode(this.getAttribute('data-search-node'))" in index_html

    def test_source_urls_open_in_new_tab(self, index_html):
        """Source URLs in the detail panel open in a new tab."""
        assert 'target="_blank"' in index_html


# --- not_connected marking (buttons + race guard) ---

class TestNotConnectedMarking:
    def test_mark_button_uses_data_action(self, index_html):
        assert 'data-action="mark-nc"' in index_html
        assert 'data-node-id=' in index_html

    def test_restore_button_uses_data_action(self, index_html):
        assert 'data-action="unmark-nc"' in index_html

    def test_action_wiring_via_add_event_listener(self, index_html):
        assert "querySelectorAll('[data-action]')" in index_html
        assert "toggleNotConnected(nid, true)" in index_html
        assert "toggleNotConnected(nid, false)" in index_html

    def test_race_guard_present(self, index_html):
        """Issue #11: an in-flight guard prevents overlapping toggles."""
        assert "_toggleNotConnectedInFlight" in index_html
        # Guard is checked at function entry and set true before the fetch.
        assert re.search(
            r"if\s*\(\s*_toggleNotConnectedInFlight\s*\)", index_html)
        # Guard + button released in a finally block.
        assert ".finally(" in index_html
        assert "_toggleNotConnectedInFlight = false" in index_html

    def test_refresh_then_detail_chain(self, index_html):
        """Issue #11: refreshGraph() completes before showNodeDetail()."""
        assert "refreshGraph().then" in index_html

    def test_not_connected_banner_css(self, index_html):
        assert "not-connected-banner" in index_html


# --- Fallback table (Cytoscape unavailable) ---

class TestFallbackView:
    def test_fallback_elements_present(self, index_html):
        assert 'id="fallback-view"' in index_html
        assert 'id="fallback-table"' in index_html
        assert 'id="fallback-search"' in index_html

    def test_fallback_filter_wired(self, index_html):
        assert "oninput=\"filterFallback()\"" in index_html

    def test_fallback_render_function(self, index_html):
        assert "function renderFallbackTable()" in index_html


# --- Node detail panel structure ---

class TestNodeDetailPanel:
    def test_detail_container_present(self, index_html):
        assert 'id="detail"' in index_html

    def test_node_detail_fetches_api(self, index_html):
        assert "/api/node/" in index_html
        assert "encodeURIComponent(nodeId)" in index_html

    def test_images_gallery_in_detail(self, index_html):
        assert "image-gallery" in index_html
        assert "openLightbox" in index_html

    def test_lightbox_elements_present(self, index_html):
        assert 'id="lightbox"' in index_html
        assert 'id="lightbox-img"' in index_html
        assert 'id="lightbox-caption"' in index_html


# --- Diagnostic panel ---

class TestDiagnosticPanel:
    def test_diag_elements_present(self, index_html):
        for did in ["diag-library", "diag-data", "diag-render", "diag-nodes"]:
            assert f'id="{did}"' in index_html, f"missing #{did}"
        # collapsible diagnostic log panel
        assert 'id="diag-panel"' in index_html
