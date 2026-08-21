"""Provider helpers for Shady."""

from .base import EntityRef, ProviderBase, assemble_series_tuples, state_to_three_state_value
from .discovery import ForecastCandidate, ShadyBaselineForecastProvider, discover_candidates, rank_candidates, score_candidate
from .normalize import canonical_series, normalize_series
from .temperature import ShadyTemperatureProvider

__all__ = [
    "EntityRef",
    "ForecastCandidate",
    "ProviderBase",
    "ShadyBaselineForecastProvider",
    "ShadyTemperatureProvider",
    "assemble_series_tuples",
    "canonical_series",
    "discover_candidates",
    "normalize_series",
    "rank_candidates",
    "score_candidate",
    "state_to_three_state_value",
]
