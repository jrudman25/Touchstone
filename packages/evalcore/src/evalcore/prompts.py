"""Prompt placeholders: extraction and rendering.

The single definition of the ``{{name}}`` pattern shared by records
(version variables), FastAPI, and the worker. Rendering is plain
substitution with no logic, filters, or escaping; a missing variable is
always an error, never an empty string.
"""

import json
import re
from collections.abc import Mapping

VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

TemplateValues = Mapping[str, str | int | float | bool]


def extract_variables(*texts: str) -> list[str]:
    """Return placeholder names in first-appearance order across the texts."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in VARIABLE_RE.finditer(text):
            seen.setdefault(match.group(1))
    return list(seen)


class MissingVariablesError(Exception):
    """Raised when a template needs values the caller did not provide."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(f"Missing variables: {', '.join(missing)}")
        self.missing = missing


def _format_value(value: str | int | float | bool) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value)


def render_template(text: str, values: TemplateValues) -> str:
    """Substitute every ``{{name}}`` with its formatted value.

    All missing names across the text are collected and reported in one
    ``MissingVariablesError`` (first-appearance order). Inserted values are
    literal: ``{{x}}`` inside a value is never re-rendered.
    """
    missing: dict[str, None] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            missing.setdefault(name)
            return match.group(0)
        return _format_value(values[name])

    rendered = VARIABLE_RE.sub(replace, text)
    if missing:
        raise MissingVariablesError(list(missing))
    return rendered


def render_prompt(system_message: str, body: str, values: TemplateValues) -> tuple[str, str]:
    """Render both texts, raising one error covering all missing names."""
    missing: dict[str, None] = {}

    def render_one(text: str) -> str:
        try:
            return render_template(text, values)
        except MissingVariablesError as exc:
            for name in exc.missing:
                missing.setdefault(name)
            return text

    rendered_system = render_one(system_message)
    rendered_body = render_one(body)
    if missing:
        raise MissingVariablesError(list(missing))
    return rendered_system, rendered_body
