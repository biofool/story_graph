#!/usr/bin/env python3
"""
Geocode NZ hot springs using the WorldStudioFinder geocoding algorithm.

Uses the same Google Geocoding API + googlemaps package + disk cache pattern
as src/scrapers/geocoding_client.py from WorldStudioFinder, adapted for
POI-style queries (spring name + region + country) instead of city+country.

Outputs GeoJSON (RFC 7946) compatible with OpenLayers, Leaflet, QGIS, etc.

Usage:
    # Source the WorldStudioFinder .env to get GOOGLE_API_KEY
    set -a; . ~/projects/github/WorldStudioFinder/.env; set +a
    python scripts/geocode_nz_hot_springs.py
    python scripts/geocode_nz_hot_springs.py --dry-run          # preview, no API calls
    python scripts/geocode_nz_hot_springs.py --limit 10         # first 10 only
    python scripts/geocode_nz_hot_springs.py --no-cache        # ignore cache, re-geocode all
"""

import argparse
import json
import logging
import math
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- WorldStudioFinder geocoding algorithm (adapted) -------------------------

CACHE_DIR = Path("data/cache")
CACHE_FILE = CACHE_DIR / "nz_springs_geocache.json"
DATA_FILE = Path("data/nz_hot_springs.json")
OUTPUT_FILE = Path("data/nz_hot_springs.geojson")

_AMBIGUOUS_SENTINEL = "__ambiguous__"
_ERROR_SENTINEL = "__error__"

try:
    import googlemaps
    _GOOGLEMAPS_AVAILABLE = True
except ImportError:
    _GOOGLEMAPS_AVAILABLE = False


class SpringGeocoder:
    """
    Geocodes hot spring POIs using Google Geocoding API.

    Mirrors the WorldStudioFinder GeocodingClient pattern:
    - googlemaps.Client for API calls
    - disk cache (data/cache/) to avoid re-paying for the same query
    - fuzzy matching for result validation
    - status tracking: ok / no_result / ambiguous / error / ref_coords

    Key adaptation: queries are "{spring_name}, {region}, New Zealand"
    instead of "{city}, {country}" since these are POIs, not cities.
    """

    def __init__(self, api_key: Optional[str] = None, no_cache: bool = False):
        if not _GOOGLEMAPS_AVAILABLE:
            raise ImportError(
                "googlemaps package required. Install: pip install googlemaps"
            )

        self.api_key = (
            api_key
            or os.environ.get("GOOGLE_GEOCODE_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        if not self.api_key:
            raise ValueError(
                "Google Maps API key required. Set GOOGLE_API_KEY env var."
            )

        self._client = googlemaps.Client(key=self.api_key)
        self._no_cache = no_cache
        self._cache: dict = {} if no_cache else self._load_cache()
        self.request_count = 0

    def _load_cache(self) -> dict:
        if CACHE_FILE.exists():
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    parsed = {}
                    for k, v in raw.items():
                        if v is None:
                            parsed[k] = None
                        elif isinstance(v, str):
                            parsed[k] = v
                        elif isinstance(v, (list, tuple)):
                            parsed[k] = tuple(v)
                        else:
                            parsed[k] = None
                    return parsed
            except Exception as e:
                logger.warning("Failed to load geocache: %s", e)
        return {}

    def _save_cache(self) -> None:
        if self._no_cache:
            return
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save geocache: %s", e)

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value.lower().strip())
        normalized = re.sub(r"\bst\.", "saint", normalized)
        normalized = re.sub(r"\bst\b", "saint", normalized)
        return normalized

    @staticmethod
    def _fuzzy_match(expected: str, candidates: set, threshold: float = 0.75) -> bool:
        for candidate in candidates:
            ratio = SequenceMatcher(None, expected, candidate).ratio()
            if ratio >= threshold:
                return True
            if expected in candidate or candidate in expected:
                return True
        return False

    @staticmethod
    def _component_values(result: dict, component_type: str) -> list:
        values = []
        for comp in result.get("address_components", []):
            types = comp.get("types", [])
            if component_type in types:
                long_name = comp.get("long_name")
                short_name = comp.get("short_name")
                if isinstance(long_name, str) and long_name:
                    values.append(long_name)
                if isinstance(short_name, str) and short_name:
                    values.append(short_name)
        return values

    def geocode_spring(
        self,
        name: str,
        region: str,
        address: str = "",
        country: str = "New Zealand",
    ) -> tuple[Optional[tuple[float, float]], str]:
        """
        Geocode a hot spring POI. Returns ((lat, lng), status).

        Status values: "ok", "no_result", "ambiguous", "error".
        Query format: "{name}, {region}, {country}" or "{address}, {country}".
        """
        # Build query — prefer address if it has specific street info,
        # otherwise use name + region
        if address and any(c.isdigit() for c in address.split(",")[0]):
            query = f"{address}, {country}"
        else:
            query = f"{name}, {region}, {country}"

        cache_key = query.lower().strip()

        if not self._no_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            if cached == _AMBIGUOUS_SENTINEL:
                return None, "ambiguous"
            if cached == _ERROR_SENTINEL:
                return None, "error"
            return (cached, "ok") if cached else (None, "no_result")

        try:
            results = self._client.geocode(query)
            self.request_count += 1

            if not results:
                # Try alternate query: just name + country
                alt_query = f"{name}, {country}"
                if alt_query != query:
                    results = self._client.geocode(alt_query)
                    self.request_count += 1
                    if results:
                        logger.debug("Found via alternate query: %s", alt_query)

            if not results:
                logger.warning("No geocode results for: %s", query)
                if not self._no_cache:
                    self._cache[cache_key] = None
                    self._save_cache()
                return None, "no_result"

            top = results[0]
            loc = top["geometry"]["location"]
            coords = (loc["lat"], loc["lng"])

            # Validate result is in New Zealand (lat -48 to -34, lng 165 to 179)
            if not (-48 <= coords[0] <= -34 and 165 <= coords[1] <= 179):
                logger.warning(
                    "Geocode for '%s' returned coords outside NZ: %s", query, coords
                )
                if not self._no_cache:
                    self._cache[cache_key] = _AMBIGUOUS_SENTINEL
                    self._save_cache()
                return None, "ambiguous"

            if not self._no_cache:
                self._cache[cache_key] = coords
                self._save_cache()

            logger.debug("Geocoded '%s' -> %s", query, coords)
            return coords, "ok"

        except Exception as e:
            logger.warning("Geocoding failed for '%s': %s", query, e)
            if not self._no_cache:
                self._cache[cache_key] = _ERROR_SENTINEL
                self._save_cache()
            return None, "error"


# --- GeoJSON output ---------------------------------------------------------


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lng points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def build_geojson(springs: list, geocoder: Optional[SpringGeocoder], dry_run: bool, limit: Optional[int]):
    """Build GeoJSON FeatureCollection from springs list."""
    features = []
    stats = {"ok": 0, "no_result": 0, "ambiguous": 0, "error": 0, "ref_coords": 0, "skipped": 0}
    coord_comparison = []

    if limit:
        springs = springs[:limit]

    for s in springs:
        coords = None
        geocode_status = "skipped"
        source_of_coords = None

        if dry_run:
            # In dry-run, use ref_coords if available, otherwise mark as skipped
            if s.get("ref_coords"):
                coords = tuple(s["ref_coords"])
                geocode_status = "ref_coords"
                source_of_coords = "hotspringsguides"
            else:
                geocode_status = "skipped"
        else:
            # Use geocoder
            coords, geocode_status = geocoder.geocode_spring(
                s["name"], s["region"], s.get("address", "")
            )
            source_of_coords = "google_geocode"

            # If geocoding failed but we have ref_coords, use those as fallback
            if coords is None and s.get("ref_coords"):
                coords = tuple(s["ref_coords"])
                geocode_status = "ref_coords"
                source_of_coords = "hotspringsguides"
                logger.info("Using ref_coords fallback for: %s", s["name"])

            # Compare geocoded coords with ref_coords if both available
            if coords and s.get("ref_coords"):
                ref = tuple(s["ref_coords"])
                dist = haversine_km(coords[0], coords[1], ref[0], ref[1])
                coord_comparison.append({
                    "name": s["name"],
                    "google": [round(coords[0], 6), round(coords[1], 6)],
                    "ref": [ref[0], ref[1]],
                    "distance_km": round(dist, 2),
                })

        stats[geocode_status] = stats.get(geocode_status, 0) + 1

        if coords is None:
            # Still include in GeoJSON but without geometry
            geometry = None
        else:
            # GeoJSON uses [lng, lat] order
            geometry = {
                "type": "Point",
                "coordinates": [round(coords[1], 6), round(coords[0], 6)],
            }

        properties = {
            "id": s["id"],
            "name": s["name"],
            "region": s["region"],
            "island": s["island"],
            "type": s["type"],
            "status": s["status"],
            "address": s.get("address", ""),
            "geocode_status": geocode_status,
            "coord_source": source_of_coords,
        }

        # Add optional fields
        for field in ["rating", "votes", "temperature", "price", "description"]:
            if field in s and s[field] is not None:
                properties[field] = s[field]

        properties["sources"] = s.get("sources", [])

        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        }
        features.append(feature)

    geojson = {
        "type": "FeatureCollection",
        "metadata": {
            "title": "New Zealand Hot Springs and Thermal Pools",
            "description": "Consolidated from NZHotPools, Wikipedia, Newswire, HotSpringsGuides, and the Hot Springs of NZ guidebook",
            "source_urls": {
                "nzhotpools": "https://nzhotpools.co.nz/hot-pools/",
                "wikipedia": "https://en.wikipedia.org/wiki/Hot_springs_in_New_Zealand",
                "newswire": "https://newswire.co.nz/data/hot-springs-nz/",
                "hotspringsguides": "https://www.hotspringsguides.com/country/new-zealand",
            },
            "geocode_method": "Google Geocoding API (WorldStudioFinder algorithm)",
            "total_features": len(features),
            "features_with_coords": sum(1 for f in features if f["geometry"] is not None),
        },
        "features": features,
    }

    return geojson, stats, coord_comparison


def main():
    parser = argparse.ArgumentParser(description="Geocode NZ hot springs to GeoJSON")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API calls (uses ref_coords only)")
    parser.add_argument("--limit", type=int, help="Process only first N springs")
    parser.add_argument("--no-cache", action="store_true", help="Ignore disk cache, re-geocode all")
    parser.add_argument("--output", type=str, default=str(OUTPUT_FILE), help="Output GeoJSON file path")
    args = parser.parse_args()

    # Load data
    if not DATA_FILE.exists():
        logger.error("Data file not found: %s", DATA_FILE)
        sys.exit(1)

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    springs = data["springs"]
    logger.info("Loaded %d springs from %s", len(springs), DATA_FILE)

    # Initialize geocoder (unless dry-run)
    geocoder = None
    if not args.dry_run:
        try:
            geocoder = SpringGeocoder(no_cache=args.no_cache)
            logger.info("Geocoder initialized (API key loaded)")
        except (ImportError, ValueError) as e:
            logger.error("Geocoder init failed: %s", e)
            logger.error("Set GOOGLE_API_KEY env var or use --dry-run")
            sys.exit(1)

    # Build GeoJSON
    logger.info("Geocoding %d springs (dry_run=%s)...", len(springs), args.dry_run)
    geojson, stats, comparisons = build_geojson(springs, geocoder, args.dry_run, args.limit)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson, f, indent=2, ensure_ascii=False)

    # Report
    total = sum(stats.values())
    with_coords = geojson["metadata"]["features_with_coords"]
    logger.info("--- Results ---")
    logger.info("Total springs: %d", total)
    logger.info("With coordinates: %d", with_coords)
    logger.info("Without coordinates: %d", total - with_coords)
    logger.info("Status breakdown: %s", stats)
    if not args.dry_run and geocoder:
        logger.info("API calls made: %d", geocoder.request_count)
    logger.info("Output written to: %s", output_path)

    # Coordinate comparison report
    if comparisons:
        logger.info("--- Coordinate comparison (Google vs HotSpringsGuides) ---")
        large_diffs = [c for c in comparisons if c["distance_km"] > 5]
        if large_diffs:
            logger.warning("Large discrepancies (>5km):")
            for c in large_diffs:
                logger.warning("  %s: Google %s vs ref %s = %.1f km apart",
                               c["name"], c["google"], c["ref"], c["distance_km"])
        else:
            max_dist = max(c["distance_km"] for c in comparisons)
            logger.info("All %d comparisons within 5km (max: %.2f km)", len(comparisons), max_dist)

    # Write comparison report
    if comparisons:
        comp_path = output_path.parent / "nz_hot_springs_coord_comparison.json"
        with open(comp_path, "w", encoding="utf-8") as f:
            json.dump(comparisons, f, indent=2)
        logger.info("Comparison report: %s", comp_path)


if __name__ == "__main__":
    main()
