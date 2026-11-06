"""Prompt placeholder rendering."""

import pytest

from evalcore.prompts import (
    MissingVariablesError,
    extract_variables,
    render_prompt,
    render_template,
)


def test_whitespace_inside_braces() -> None:
    assert render_template("hi {{ name }}!", {"name": "jo"}) == "hi jo!"


def test_repeated_variable_replaced_each_time() -> None:
    assert render_template("{{a}} and {{a}}", {"a": "x"}) == "x and x"


def test_all_missing_names_in_first_appearance_order() -> None:
    with pytest.raises(MissingVariablesError) as exc_info:
        render_prompt("{{a}} {{c}}", "{{b}} {{a}}", {})
    assert exc_info.value.missing == ["a", "c", "b"]


def test_missing_names_deduped_across_occurrences() -> None:
    with pytest.raises(MissingVariablesError) as exc_info:
        render_template("{{x}} {{x}} {{y}}", {})
    assert exc_info.value.missing == ["x", "y"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "plain"),
        (True, "true"),
        (False, "false"),
        (7, "7"),
        (1.5, "1.5"),
    ],
)
def test_value_formatting(value: str | int | float | bool, expected: str) -> None:
    assert render_template("[{{v}}]", {"v": value}) == f"[{expected}]"


def test_inserted_values_are_not_re_rendered() -> None:
    assert render_template("{{a}}", {"a": "{{b}}", "b": "x"}) == "{{b}}"


def test_text_without_placeholders_is_unchanged() -> None:
    assert render_template("no vars here", {}) == "no vars here"


def test_render_prompt_returns_both_texts() -> None:
    assert render_prompt("sys {{a}}", "body {{b}}", {"a": "1", "b": "2"}) == (
        "sys 1",
        "body 2",
    )


def test_extract_variables_order_and_dedup() -> None:
    assert extract_variables("{{ a }} {{b}} {{a}}", "{{c}} {{ b }}") == ["a", "b", "c"]


def test_extract_variables_skips_invalid() -> None:
    assert extract_variables("{{1x}} {{ }} {{}} {{_ok}}", "") == ["_ok"]
