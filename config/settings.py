"""
Centralized configuration loader.
Reads from .env and provides typed access to settings.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseModel):
    """Typed settings loaded from environment variables."""

    # Crawling
    crawl_delay_seconds: float = Field(
        default_factory=lambda: float(os.getenv("CRAWL_DELAY_SECONDS", "3"))
    )
    crawl_max_depth: int = Field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_DEPTH", "2"))
    )
    crawl_max_pages: int = Field(
        default_factory=lambda: int(os.getenv("CRAWL_MAX_PAGES", "200"))
    )
    crawl_user_agent: str = Field(
        default_factory=lambda: os.getenv(
            "CRAWL_USER_AGENT", "story-graph-bot/0.1 (+research)"
        )
    )
    crawl_timeout: int = Field(
        default_factory=lambda: int(os.getenv("CRAWL_TIMEOUT", "30"))
    )

    # NLP
    spacy_model: str = Field(
        default_factory=lambda: os.getenv("SPACY_MODEL", "en_core_web_sm")
    )

    # Gemini (Google Gen AI SDK) — used for seed discovery, structured
    # entity/claim extraction, and graph Q&A. Optional: features degrade
    # gracefully when GEMINI_API_KEY is unset.
    gemini_api_key: str = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    gemini_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )

    # Additional AI Studio API keys for free-tier round-robin (each has its
    # own daily quota). Only keys that are set and non-empty are used.
    google_api_key: str = Field(
        default_factory=lambda: os.getenv("GOOGLE_API_KEY", "")
    )
    movement_arts_google_api_key: str = Field(
        default_factory=lambda: os.getenv("MOVEMENT_ARTS_GOOGLE_API_KEY", "")
    )

    # Vertex AI (paid tier) fallback — used when all free-tier AI Studio
    # keys are exhausted (429). Authenticates via Application Default
    # Credentials (e.g. a service account key file set via
    # GOOGLE_APPLICATION_CREDENTIALS or gcloud auth).
    gemini_vertexai_enabled: bool = Field(
        default_factory=lambda: os.getenv("GEMINI_VERTEXAI_ENABLED", "true").lower()
        in ("true", "1", "yes")
    )
    gemini_vertexai_project: str = Field(
        default_factory=lambda: os.getenv("GEMINI_VERTEXAI_PROJECT", "")
    )
    gemini_vertexai_location: str = Field(
        default_factory=lambda: os.getenv("GEMINI_VERTEXAI_LOCATION", "us-central1")
    )
    # Model to use on Vertex AI (may differ from the AI Studio model —
    # e.g. gemini-3.6-flash is available on AI Studio but not yet on
    # Vertex AI for some projects; gemini-2.5-flash is the stable Vertex
    # default).
    gemini_vertexai_model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_VERTEXAI_MODEL", "gemini-2.5-flash")
    )

    # Storage
    graph_db_path: str = Field(
        default_factory=lambda: os.getenv("GRAPH_DB_PATH", "data/graph.db")
    )
    raw_pages_dir: str = Field(
        default_factory=lambda: os.getenv("RAW_PAGES_DIR", "data/raw")
    )
    # Tracked/version-controlled JSON snapshot of the graph (source of
    # truth) — data/graph.db above is only the local SQLite working copy
    # rebuilt from this at pipeline startup. See src/storage/json_export.py.
    graph_snapshot_dir: str = Field(
        default_factory=lambda: os.getenv("GRAPH_SNAPSHOT_DIR", "graph_snapshot")
    )

    # Seed URLs
    seed_urls: list[str] = Field(
        default_factory=lambda: [
            "https://lifeinthesourcefamily.blogspot.com/",
            "https://cultnews.com/2016/08/documentary-about-source-family-cult-doesnt-tell-the-whole-story/",
            "https://sourcerestaurants.com/",
            "https://en.wikipedia.org/wiki/Father_Yod",
            "https://pleasekillme.com/father-yod/",
        ]
    )

    # Allowed crawl domains
    allowed_domains: set[str] = Field(
        default_factory=lambda: {
            "cultnews.com",
            "lifeinthesourcefamily.blogspot.com",
            "blogspot.com",
            "yahowha.org",
            "youtube.com",
            "wordpress.com",
            "sourcerestaurants.com",
            "en.wikipedia.org",
            "pleasekillme.com",
            "latimes.com",
        }
    )

    @property
    def graph_db_abs_path(self) -> Path:
        p = Path(self.graph_db_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def raw_pages_abs_dir(self) -> Path:
        p = Path(self.raw_pages_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p

    @property
    def graph_snapshot_abs_dir(self) -> Path:
        p = Path(self.graph_snapshot_dir)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p


settings = Settings()
