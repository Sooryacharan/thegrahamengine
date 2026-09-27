from engine.triage.rules import rules_prefilter


def test_passes_substantive_content():
    result = rules_prefilter(
        "OPEC+ signals surprise supply cut starting Q3",
        "Ministers agreed to reduce output quotas by 500kb/d effective July.",
    )
    assert result.passed is True
    assert result.reason is None


def test_fails_content_too_short():
    result = rules_prefilter("Oil", "up")
    assert result.passed is False
    assert "short" in result.reason


def test_fails_listicle_pattern():
    result = rules_prefilter("Top 10 stocks to watch this week", "A roundup of picks.")
    assert result.passed is False
    assert "noise pattern" in result.reason


def test_fails_celebrity_gossip():
    result = rules_prefilter("Celebrity investor makes surprise market call", "Gossip roundup.")
    assert result.passed is False


def test_fails_sports_score():
    result = rules_prefilter("Local team wins 3-1 in big Sunday result", "Recap of the match.")
    assert result.passed is False


def test_case_insensitive_matching():
    result = rules_prefilter("YOU WON'T BELIEVE what the Fed did next", "Clickbait headline.")
    assert result.passed is False
