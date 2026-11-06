"""Provider construction from the frozen model snapshot.

Phase 2 supports only the in-process mock; real providers arrive in
Phase 3 with metadata fetching. Unknown kinds fail per result so one
bad model cannot take down the run.
"""

from collections.abc import Mapping

from evalcore.mock_provider import MockProvider
from evalcore.providers import ProviderClient, ProviderError
from evalcore.runs import ModelSnapshot


def build_provider(
    model: ModelSnapshot, *, seed: int, answers: Mapping[str, str]
) -> ProviderClient:
    if model.provider_kind == "mock":
        return MockProvider(seed=seed, answers=answers)
    raise ProviderError(f"Provider kind {model.provider_kind} is not supported yet")
