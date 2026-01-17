import pytest
from app.utils import clean_url_for_log

def test_clean_url_for_log_no_query():
    url = "https://example.com/calendar.ics"
    assert clean_url_for_log(url) == "https://example.com/calendar.ics"

def test_clean_url_for_log_with_query():
    url = "https://example.com/calendar.ics?token=SECRET_VALUE&foo=bar"
    expected = "https://example.com/calendar.ics"
    assert clean_url_for_log(url) == expected

def test_clean_url_for_log_invalid_url():
    # Should return original if parsing fails or handle gracefully
    # urlparse is very lenient, so "not_a_url" is actually parsed with path="not_a_url"
    url = "not_a_url"
    assert clean_url_for_log(url) == "not_a_url"

def test_clean_url_for_log_empty():
    assert clean_url_for_log("") == ""

def test_clean_url_for_log_none():
    assert clean_url_for_log(None) is None
