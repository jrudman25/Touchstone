"""Rule-based scorer behavior: normalization, matching, and null scores."""

from evalcore.scorers import normalize_text, score_rule


def test_normalize_text_case_whitespace_and_nfkc() -> None:
    assert normalize_text("  PARIS   city ") == "paris city"
    # Full-width letters normalize to ASCII under NFKC.
    assert normalize_text("Ｐａｒｉｓ") == "paris"  # noqa: RUF001
    assert normalize_text("a\t\nb") == "a b"


def test_exact_ignores_case_and_whitespace() -> None:
    assert score_rule("exact", 1, "  PARIS ", "paris").value == 1.0
    assert score_rule("exact", 1, "Lyon", "Paris").value == 0.0


def test_contains_normalized_substring() -> None:
    assert score_rule("contains", 2, "The answer is PARIS, France.", "paris").value == 1.0
    assert score_rule("contains", 2, "no match here", "paris").value == 0.0


def test_regex_match_and_no_match_on_raw_text() -> None:
    assert score_rule("regex", 3, "order #1234", r"#\d+").value == 1.0
    assert score_rule("regex", 3, "no digits", r"#\d+").value == 0.0
    # Raw strings: case matters unless the pattern says otherwise.
    assert score_rule("regex", 3, "PARIS", r"paris").value == 0.0


def test_invalid_regex_scores_null_with_reason() -> None:
    score = score_rule("regex", 4, "anything", "[unclosed")
    assert score.value is None
    assert score.reason is not None and score.reason.startswith("Invalid regex:")


def test_missing_expected_scores_null_for_all_kinds() -> None:
    for kind in ("exact", "contains", "regex"):
        score = score_rule(kind, 5, "output", None)
        assert score.value is None
        assert score.reason == "No expected value for this row"
