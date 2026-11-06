"""Mock provider determinism, rates, truncation, and token counts."""

import asyncio

import pytest

from evalcore.mock_provider import MockProvider
from evalcore.providers import (
    GenerationRequest,
    GenerationResult,
    ProviderClient,
    ProviderError,
)


def make_request(**overrides: object) -> GenerationRequest:
    fields: dict[str, object] = {
        "model_name": "mock-1",
        "system_message": "sys",
        "prompt": "what is the capital of France?",
        "temperature": 0.0,
        "max_tokens": 64,
    }
    fields.update(overrides)
    return GenerationRequest(**fields)  # type: ignore[arg-type]


def generate(provider: MockProvider, request: GenerationRequest) -> GenerationResult:
    return asyncio.run(provider.generate(request))


def test_provider_client_protocol() -> None:
    client: ProviderClient = MockProvider()
    result = asyncio.run(client.generate(make_request()))
    assert isinstance(result, GenerationResult)


def test_identical_inputs_identical_output_across_instances() -> None:
    request = make_request()
    first = generate(MockProvider(seed=1), request)
    second = generate(MockProvider(seed=1), request)
    assert first == second


def test_different_model_name_changes_outcomes() -> None:
    provider = MockProvider(seed=3)
    outputs_a = {generate(provider, make_request(prompt=f"p{i}")).output for i in range(50)}
    outputs_b = {
        generate(provider, make_request(model_name="other", prompt=f"p{i}")).output
        for i in range(50)
    }
    assert outputs_a != outputs_b


def test_different_seed_changes_outcomes() -> None:
    outputs_a = {
        generate(MockProvider(seed=1), make_request(prompt=f"p{i}")).output for i in range(50)
    }
    outputs_b = {
        generate(MockProvider(seed=2), make_request(prompt=f"p{i}")).output for i in range(50)
    }
    assert outputs_a != outputs_b


def test_accuracy_one_returns_canned_answer() -> None:
    answers = {"what is the capital of France?": "Paris"}
    result = generate(MockProvider(seed=0, accuracy=1.0, answers=answers), make_request())
    assert result.output == "Paris"


def test_accuracy_zero_never_returns_canned_answer() -> None:
    answers = {"what is the capital of France?": "Paris"}
    provider = MockProvider(seed=0, accuracy=0.0, answers=answers)
    for _ in range(20):
        assert generate(provider, make_request()).output != "Paris"


def test_fail_rate_one_always_raises() -> None:
    provider = MockProvider(fail_rate=1.0)
    with pytest.raises(ProviderError, match="Mock provider failure"):
        generate(provider, make_request())


def test_fail_rate_zero_never_raises() -> None:
    provider = MockProvider(fail_rate=0.0)
    for _ in range(50):
        generate(provider, make_request())


def test_max_tokens_truncates_output_words() -> None:
    answers = {"what is the capital of France?": "one two three four five"}
    provider = MockProvider(accuracy=1.0, answers=answers)
    result = generate(provider, make_request(max_tokens=3))
    assert result.output == "one two three"


def test_max_tokens_does_not_pad_short_output() -> None:
    result = generate(MockProvider(), make_request(max_tokens=100))
    assert result.output.split() == result.output.split()[:100]


def test_token_counts() -> None:
    request = make_request(system_message="a b", prompt="c d e")
    result = generate(MockProvider(), request)
    assert result.input_tokens == 5
    assert result.output_tokens == max(1, len(result.output.split()))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accuracy": -0.1},
        {"accuracy": 1.1},
        {"fail_rate": -0.1},
        {"fail_rate": 1.1},
        {"latency_ms": -1},
    ],
)
def test_invalid_constructor_args(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MockProvider(**kwargs)  # type: ignore[arg-type]
