"""GeoToolCN — Offline geocoding toolkit for Chinese administrative regions."""

from __future__ import annotations

__version__ = "1.0.1"

from .core import GeoTool, Region, ReverseResult

__all__ = [
    "GeoTool",
    "Region",
    "ReverseResult",
    "reverse",
    "reverse_batch",
    "search",
    "list_regions",
    "get_region",
]

# ---------------------------------------------------------------------------
# Module-level convenience functions (lazy singleton)
# ---------------------------------------------------------------------------

_instance: GeoTool | None = None


def _get_instance() -> GeoTool:
    global _instance
    if _instance is None:
        _instance = GeoTool()
    return _instance


def reverse(lat: float, lng: float) -> ReverseResult:
    """Shortcut for ``GeoTool().reverse(lat, lng)``."""
    return _get_instance().reverse(lat, lng)


def reverse_batch(
    coords: list[tuple[float, float]],
) -> list[ReverseResult]:
    """Shortcut for ``GeoTool().reverse_batch(coords)``."""
    return _get_instance().reverse_batch(coords)


def search(
    query: str,
    *,
    level: str | None = None,
    province: str | None = None,
    city: str | None = None,
    fuzzy: bool = True,
) -> list[Region]:
    """Shortcut for ``GeoTool().search(query, ...)``."""
    return _get_instance().search(
        query, level=level, province=province, city=city, fuzzy=fuzzy
    )


def list_regions(level: str) -> list[Region]:
    """Shortcut for ``GeoTool().list_regions(level)``."""
    return _get_instance().list_regions(level)


def get_region(code: str) -> Region | None:
    """Shortcut for ``GeoTool().get_region(code)``."""
    return _get_instance().get_region(code)
