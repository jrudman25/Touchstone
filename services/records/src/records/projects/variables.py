"""Extraction of {{name}} placeholders from prompt text."""

import re

VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


def extract_variables(*texts: str) -> list[str]:
    """Return placeholder names in first-appearance order across the texts."""
    seen: dict[str, None] = {}
    for text in texts:
        for match in VARIABLE_RE.finditer(text):
            seen.setdefault(match.group(1))
    return list(seen)
