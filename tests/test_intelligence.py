"""Tests for the intelligence module."""

from datetime import date
from unittest.mock import patch

from monitor.intelligence import (
    DAYS_BEFORE_RELEASE,
    KNOWN_UPCOMING_SETS,
    _match_terms_in_text,
    get_upcoming_sets,
)


def test_get_upcoming_sets():
    results = get_upcoming_sets()
    assert isinstance(results, list)
    assert len(results) == len(KNOWN_UPCOMING_SETS)
    for item in results:
        assert "days_until_release" in item
        assert "is_within_window" in item
        assert "is_released" in item
        assert "name" in item
        assert "release_date" in item


def test_match_terms_in_text():
    # Exact substring match (term is substring of text)
    assert _match_terms_in_text(
        "Pokemon Perfect Order Elite Trainer Box",
        ["perfect order"],
    )
    assert _match_terms_in_text(
        "Mega Zygarde EX Premium Collection",
        ["mega zygarde ex"],
    )
    assert not _match_terms_in_text(
        "Pokemon Prismatic Evolutions",
        ["perfect order", "chaos rising"],
    )
    # Case insensitive
    assert _match_terms_in_text("PERFECT ORDER BOX", ["perfect order"])


@patch("monitor.intelligence.date")
def test_set_within_window(mock_date):
    """A set 10 days from release should be within the monitoring window."""
    first_set = KNOWN_UPCOMING_SETS[0]
    release = date.fromisoformat(first_set["release_date"])
    fake_today = date.fromordinal(release.toordinal() - 10)
    mock_date.today.return_value = fake_today
    mock_date.fromisoformat = date.fromisoformat
    mock_date.side_effect = lambda *a, **k: date(*a, **k)

    results = get_upcoming_sets()
    target = next(r for r in results if r["name"] == first_set["name"])
    assert target["days_until_release"] == 10
    assert target["is_within_window"] is True
    assert target["is_released"] is False


@patch("monitor.intelligence.date")
def test_set_outside_window(mock_date):
    """A set 30 days from release should NOT be within the monitoring window."""
    first_set = KNOWN_UPCOMING_SETS[0]
    release = date.fromisoformat(first_set["release_date"])
    fake_today = date.fromordinal(release.toordinal() - 30)
    mock_date.today.return_value = fake_today
    mock_date.fromisoformat = date.fromisoformat
    mock_date.side_effect = lambda *a, **k: date(*a, **k)

    results = get_upcoming_sets()
    target = next(r for r in results if r["name"] == first_set["name"])
    assert target["days_until_release"] == 30
    assert 30 > DAYS_BEFORE_RELEASE  # sanity check
    assert target["is_within_window"] is False
    assert target["is_released"] is False
