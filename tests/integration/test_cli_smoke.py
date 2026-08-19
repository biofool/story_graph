"""Smoke tests for the ``scripts/01_crawl_and_build_graph.py`` CLI entrypoint.

Nothing previously invoked this script's ``main()`` at all -- only its
helper functions were covered (via ``scripts._pipeline_helpers``), which is
exactly how a crash on the very first ``console.print()`` call (a missing
``console = Console()`` instantiation) could ship without any test catching
it. These tests run ``main()`` for real, through Click's ``CliRunner``, and
assert it exits cleanly with no unhandled exception.

The module filename starts with a digit, so it can't be imported with a
normal dotted import (``scripts.01_crawl_and_build_graph`` is not a valid
identifier) -- it's loaded via ``importlib.util`` instead, the same way the
script itself would be invoked as ``python scripts/01_crawl_and_build_graph.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "01_crawl_and_build_graph.py"


def _load_pipeline_module():
    """Load scripts/01_crawl_and_build_graph.py as a module and return it."""
    spec = importlib.util.spec_from_file_location(
        "_cli_smoke_pipeline_module", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_help_exits_cleanly():
    """Baseline sanity check: --help doesn't need any components at all."""
    module = _load_pipeline_module()
    runner = CliRunner()
    result = runner.invoke(module.main, ["--help"])
    assert result.exit_code == 0, result.output
    assert result.exception is None


def test_cli_skip_crawl_runs_cleanly(tmp_path):
    """--skip-crawl exercises the full pipeline (all the console.print calls,
    entity/claim extraction over zero pages, contradiction detection, and the
    summary table) with zero network access."""
    module = _load_pipeline_module()
    runner = CliRunner()
    db_path = tmp_path / "smoke_graph.db"

    result = runner.invoke(
        module.main,
        ["--skip-crawl", "--db-path", str(db_path)],
    )

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert db_path.exists()


def test_cli_crawl_phase_runs_cleanly_with_mocked_crawler(tmp_path):
    """Exercise the (normally network-hitting) crawl phase too, but with
    WebCrawler.crawl mocked out so the test stays fast and fully offline."""
    module = _load_pipeline_module()
    runner = CliRunner()
    db_path = tmp_path / "smoke_graph_crawl.db"

    with patch.object(module.WebCrawler, "crawl", return_value=[]):
        result = runner.invoke(
            module.main,
            ["--max-depth", "0", "--max-pages", "1", "--db-path", str(db_path)],
        )

    assert result.exit_code == 0, result.output
    assert result.exception is None
