"""Group discovered AOV names into display categories (pure, name-heuristic)."""
from __future__ import annotations
import re

_DIFFSPEC = re.compile(r"^(diffuse|specular|subsurface)", re.IGNORECASE)
_UTILITY = {"a", "alpha", "albedo", "normal", "N", "P", "Pworld", "Oi", "sampleCount"}

# Ordered (group, predicate). First match wins; order is also the display order.
_RULES = [
    ("Beauty",             lambda n: n == "Ci"),
    ("Lighting",           lambda n: n.startswith("L_")),
    ("Diffuse / Specular", lambda n: _DIFFSPEC.match(n) is not None),
    ("Utility",            lambda n: n in _UTILITY),
    ("Diagnostic",         lambda n: n.endswith("_variance") or n.endswith("_mse") or n == "mse"),
]
_OTHER = "Other"
_ORDER = [g for g, _ in _RULES] + [_OTHER]


def category_of(name: str) -> str:
    for group, pred in _RULES:
        if pred(name):
            return group
    return _OTHER


def group_aovs(aovs: list[str]) -> list[tuple[str, list[str]]]:
    """Bucket *aovs* into ordered (group, [aov,...]) pairs, preserving input
    order within each group and dropping empty groups. Unmatched -> 'Other'."""
    buckets: dict[str, list[str]] = {g: [] for g in _ORDER}
    for a in aovs:
        buckets[category_of(a)].append(a)
    return [(g, buckets[g]) for g in _ORDER if buckets[g]]
