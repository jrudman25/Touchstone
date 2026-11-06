"""Rule-based scorers: exact, contains, and regex.

Normalization is NFKC + casefold + whitespace collapse. A ``value`` of
None means "not scored": rows without an ``expected`` value and invalid
regex patterns score null, and nulls are excluded from score means later,
matching the treatment of unparseable judge output.
"""

import re
import unicodedata
from typing import Literal

from pydantic import BaseModel


class Score(BaseModel):
    scorer_id: int
    value: float | None
    reason: str | None = None


def normalize_text(s: str) -> str:
    """NFKC + casefold, whitespace runs collapsed to one space, stripped."""
    return " ".join(unicodedata.normalize("NFKC", s).casefold().split())


def score_rule(
    kind: Literal["exact", "contains", "regex"],
    scorer_id: int,
    output: str,
    expected: str | None,
) -> Score:
    """Score one output against the row's expected value."""
    if expected is None:
        return Score(scorer_id=scorer_id, value=None, reason="No expected value for this row")
    if kind == "exact":
        matched = normalize_text(output) == normalize_text(expected)
    elif kind == "contains":
        matched = normalize_text(expected) in normalize_text(output)
    else:
        try:
            matched = re.search(expected, output) is not None
        except re.error as exc:
            return Score(scorer_id=scorer_id, value=None, reason=f"Invalid regex: {exc}")
    return Score(scorer_id=scorer_id, value=1.0 if matched else 0.0)
