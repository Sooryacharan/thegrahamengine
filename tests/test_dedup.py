from engine.scan.dedup import compute_dedup_key, normalize_title


def test_normalize_title_lowercases_and_strips_punctuation():
    assert normalize_title("OPEC+ Signals Supply Cut!") == "opec signals supply cut"


def test_normalize_title_collapses_whitespace():
    assert normalize_title("  too   many   spaces  ") == "too many spaces"


def test_dedup_key_is_deterministic():
    a = compute_dedup_key("Reuters", "Fed holds rates", "https://x.com/a")
    b = compute_dedup_key("Reuters", "Fed holds rates", "https://x.com/a")
    assert a == b


def test_dedup_key_ignores_title_case_and_punctuation():
    a = compute_dedup_key("Reuters", "Fed Holds Rates!", "https://x.com/a")
    b = compute_dedup_key("Reuters", "fed holds rates", "https://x.com/a")
    assert a == b


def test_dedup_key_differs_by_source():
    a = compute_dedup_key("Reuters", "Fed holds rates", "https://x.com/a")
    b = compute_dedup_key("Bloomberg", "Fed holds rates", "https://x.com/a")
    assert a != b


def test_dedup_key_differs_by_url():
    a = compute_dedup_key("Reuters", "Fed holds rates", "https://x.com/a")
    b = compute_dedup_key("Reuters", "Fed holds rates", "https://x.com/b")
    assert a != b
