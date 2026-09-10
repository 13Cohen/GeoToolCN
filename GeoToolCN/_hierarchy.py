"""Administrative hierarchy rules shared by every module.

Kept dependency-free on purpose: ``admin_tree`` must not pull in geopandas, and
these rules are the one thing it and ``core`` must agree on.  When they drifted
apart, ``get_administrative_tree()`` listed all 15 of Hainan's county-level
cities under each of the other 14.
"""
from __future__ import annotations

# Municipalities (直辖市) and SARs (特别行政区).  Districts sit directly under
# the province; the city node reuses the province code.
MERGED_PREFIXES = frozenset({"11", "12", "31", "50", "81", "82"})


def parent_city_code(district_code: str, city_codes) -> str | None:
    """Resolve a district's parent city adcode.

    ``adcode[:4] + "00"`` looks like the rule and is wrong for the 30
    province-directly-governed county-level divisions (省直辖县级行政区) in
    adcode blocks 4190 (济源), 4290 (仙桃/潜江/天门/神农架), 4690 (海南) and
    6590 (新疆).  For those it yields codes such as ``419000`` that name no
    real division — and because they all share a 4-digit prefix, grouping by
    that prefix cross-multiplies them.  They are published in the city layer
    under their own code, so fall back to that.

    Parameters
    ----------
    district_code : str
        6-digit adcode of a district-level division.
    city_codes : container of str
        Every adcode present in the city layer.

    Returns
    -------
    str or None
        The parent city adcode, or *None* when none can be resolved.
    """
    prefix2 = district_code[:2]
    if prefix2 in MERGED_PREFIXES:
        return prefix2 + "0000"
    by_prefix = district_code[:4] + "00"
    if by_prefix in city_codes:
        return by_prefix
    if district_code in city_codes:
        return district_code
    return None
