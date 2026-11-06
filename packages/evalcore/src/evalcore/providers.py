"""Provider client interface shared by the worker and the playground.

Every provider kind (mock, ollama, openai_compatible) speaks through
``ProviderClient.generate``. A failure the worker should store on the
result's ``error`` field is raised as ``ProviderError``. Latency is measured
by the caller around the call.
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class GenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_name: str
    system_message: str
    prompt: str
    temperature: float
    max_tokens: int


class GenerationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    output: str
    input_tokens: int
    output_tokens: int


class ProviderError(Exception):
    """A generation failure stored on the result's error field."""


class ProviderClient(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
