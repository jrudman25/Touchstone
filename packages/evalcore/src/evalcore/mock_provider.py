"""In-process mock provider implementing the ProviderClient interface.

Deterministic: each call seeds ``random.Random`` from
``"{seed}:{model_name}:{system_message}:{prompt}"``, so identical inputs
always produce identical results while different models or seeds diverge.
``answers`` are canned outputs keyed by rendered prompt; the worker builds
them from dataset ``expected`` values so mock runs produce mixed scores.
"""

import asyncio
import hashlib
import random
from collections.abc import Mapping

from evalcore.providers import (
    GenerationRequest,
    GenerationResult,
    ProviderClient,
    ProviderError,
)


class MockProvider(ProviderClient):
    def __init__(
        self,
        *,
        seed: int = 0,
        accuracy: float = 0.7,
        answers: Mapping[str, str] | None = None,
        latency_ms: int = 0,
        fail_rate: float = 0.0,
    ) -> None:
        if not 0 <= accuracy <= 1:
            raise ValueError("accuracy must be between 0 and 1")
        if not 0 <= fail_rate <= 1:
            raise ValueError("fail_rate must be between 0 and 1")
        if latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        self.seed = seed
        self.accuracy = accuracy
        self.answers = dict(answers or {})
        self.latency_ms = latency_ms
        self.fail_rate = fail_rate

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        seed_string = f"{self.seed}:{request.model_name}:{request.system_message}:{request.prompt}"
        rng = random.Random(seed_string)  # noqa: S311 deterministic by design
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)
        if rng.random() < self.fail_rate:
            raise ProviderError("Mock provider failure")
        if rng.random() < self.accuracy and request.prompt in self.answers:
            output = self.answers[request.prompt]
        else:
            output = "Mock answer " + hashlib.sha256(seed_string.encode()).hexdigest()[:8]
        words = output.split()
        if len(words) > request.max_tokens:
            output = " ".join(words[: request.max_tokens])
        input_tokens = max(1, len((request.system_message + " " + request.prompt).split()))
        return GenerationResult(
            output=output,
            input_tokens=input_tokens,
            output_tokens=max(1, len(output.split())),
        )
