# Coding Patterns & Conventions

All patterns below are **OBSERVED** from source code analysis.

## Module Structure

### Strongly recurring (25/25 Python files):
- `from __future__ import annotations` as first import
- Module-level docstring (`"""..."""`)
- `import logging` + `_log = logging.getLogger(__name__)`
- `__init__.py` files present in all packages (empty or minimal)

### Naming
- **Classes:** PascalCase (`EntityExtractor`, `GraphDB`, `GeminiClient`)
- **Functions/methods:** snake_case (`process_page`, `extract_claims`)
- **Constants:** UPPER_SNAKE (`PERSON_PATTERNS`, `CLAIM_TRIGGERS`, `SCHEMA_SQL`)
- **Private methods:** `_prefix` (`_fetch`, `_parse_page`, `_extract_persons`)
- **Enums:** UPPER_SNAKE values (`PERSON`, `GROUP`, `CRITICAL`, `SUPPORTIVE`)

### File Organization
- One primary class per file (with supporting helpers)
- Constants and patterns at module top, class below
- Helper functions at module bottom (e.g. `_response_text`, `_normalize`)

## Feature Placement

### Documented convention (README.md project structure):
- `config/` — settings
- `src/storage/` — models, graph DB
- `src/crawler/` — web crawler (README says `scrapers/`, actual is `crawler/`)
- `src/extractor/` — entity, alias, claim, contradiction
- `src/utils/` — text utilities
- `scripts/` — pipeline entry points
- `tests/` — unit and integration tests

### Actual structure (OBSERVED):
- `src/llm/` — Gemini layer (not in README's project structure section)

## Dependency Rules

### Strongly recurring (OBSERVED in all files):
- `scripts/` may import from `src/` and `config/`
- `src/extractor/` may import from `src/utils/` and `src/extractor/alias_resolver.py`
- `src/llm/` may import from `src/extractor/alias_resolver.py`, `src/storage/`, `config/`
- `src/storage/` may only import from `src/storage/models.py` (no cross-package)
- `src/crawler/` may import from `src/utils/text_utils.py`
- `config/` is standalone (Pydantic + dotenv only)
- **No circular dependencies observed**

## Data Models

### Strongly recurring:
- Pydantic v2 `BaseModel` for all data structures
- `str` enums (not IntEnum) for all controlled vocabularies
- `Field(default_factory=...)` for mutable defaults
- `dict[str, Any]` for flexible metadata fields
- JSON serialization for metadata in SQLite (`json.dumps`/`json.loads`)

## ID Generation

### Strongly recurring (OBSERVED):
- Type-prefixed slug IDs: `person:{slug}`, `group:{slug}`, `place:{slug}`
- Hash-based IDs for works and claims: `work:{hash16}`, `claim:{hash16}`
- Slug = `slugify(normalize(name))` — lowercase, hyphenated
- Canonical names = `normalize(name)` — lowercase, no punctuation

## Testing Conventions

### Documented (pyproject.toml):
- `testpaths = ["tests"]`
- `python_files = "test_*.py"`
- `python_functions = "test_*"`
- `python_classes = "Test*"`
- Markers: `unit`, `integration`, `slow`
- `addopts = "-v --tb=short"`

### Strongly recurring (OBSERVED in all test files):
- Test classes group related tests: `TestPersonExtraction`, `TestEdgeOperations`
- `@pytest.fixture` for shared setup (especially `db` fixture for temp GraphDB)
- Unit tests use `EntityExtractor(spacy_model_name="nonexistent_model")` to
  force rule-based mode (no spaCy dependency)
- LLM tests use fake clients (`FakeGeminiClient`, `_FakeGeminiClient`)
  that override `generate_*` methods — no real API calls
- Integration tests use `tempfile.NamedTemporaryFile` for temp DBs
- `CliRunner` from Click for CLI smoke tests
- `importlib.util` for loading scripts with digit-starting filenames

## CLI Conventions

### Strongly recurring:
- Click for CLI framework (`@click.command()`, `@click.group()`)
- Rich for console output (`Console`, `Table`)
- `console = Console()` at module level
- Colored output: `[bold cyan]`, `[dim]`, `[yellow]`, `[green]`, `[red]`
- `--db-path` option to override DB location
- `PROJECT_ROOT = Path(__file__).resolve().parent.parent` + `sys.path.insert`

## Lint/Format

### Documented (pyproject.toml):
- Ruff: `line-length = 100`, `target-version = "py310"`
- No formatter config (ruff format not explicitly configured)
