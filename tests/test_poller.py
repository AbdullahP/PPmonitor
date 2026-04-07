"""Tests for poller functions: get_poll_interval, challenge tracking."""

from datetime import date, timedelta

from monitor.poller import get_poll_interval


def test_poll_interval_no_release_date():
    product = {"product_id": "123", "poll_priority": "normal"}
    assert get_poll_interval(product) == 0  # use default


def test_poll_interval_critical_priority():
    product = {"product_id": "123", "poll_priority": "critical"}
    assert get_poll_interval(product) == 5


def test_poll_interval_release_day():
    product = {"product_id": "123", "release_date": date.today(), "poll_priority": "normal"}
    assert get_poll_interval(product) == 5


def test_poll_interval_tomorrow():
    product = {"product_id": "123", "release_date": date.today() + timedelta(days=1), "poll_priority": "normal"}
    assert get_poll_interval(product) == 5


def test_poll_interval_3_days():
    product = {"product_id": "123", "release_date": date.today() + timedelta(days=3), "poll_priority": "normal"}
    assert get_poll_interval(product) == 10


def test_poll_interval_14_days():
    product = {"product_id": "123", "release_date": date.today() + timedelta(days=14), "poll_priority": "normal"}
    assert get_poll_interval(product) == 30


def test_poll_interval_60_days():
    product = {"product_id": "123", "release_date": date.today() + timedelta(days=60), "poll_priority": "normal"}
    assert get_poll_interval(product) == 0  # use default


def test_poll_interval_past_release():
    product = {"product_id": "123", "release_date": date.today() - timedelta(days=5), "poll_priority": "normal"}
    assert get_poll_interval(product) == 5  # past release = days_until negative = <=1
