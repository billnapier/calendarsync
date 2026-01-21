import pytest
from app.utils import clean_url_for_log

def test_clean_url_simple():
    url = "https://example.com/calendar.ics"
    assert clean_url_for_log(url) == "https://example.com/calendar.ics"

def test_clean_url_with_query_params():
    url = "https://example.com/calendar.ics?token=SECRET123&foo=bar"
    cleaned = clean_url_for_log(url)
    assert "SECRET123" not in cleaned
    assert cleaned == "https://example.com/calendar.ics"

def test_clean_url_with_basic_auth():
    url = "https://user:password@example.com/calendar.ics"
    cleaned = clean_url_for_log(url)
    assert "password" not in cleaned
    assert "user" not in cleaned  # Usually good to hide user too if it's part of auth
    # It might result in https://example.com/calendar.ics or https://***@example.com/calendar.ics
    # Let's target stripping it completely for safety
    assert cleaned == "https://example.com/calendar.ics"

def test_clean_url_invalid():
    # handling invalid URLs gracefully
    url = "not a url"
    assert clean_url_for_log(url) == "not a url"
