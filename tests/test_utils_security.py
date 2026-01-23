import unittest
from app.utils import clean_url_for_log

class TestUtilsSecurity(unittest.TestCase):
    def test_clean_url_simple(self):
        url = "https://example.com/calendar.ics"
        self.assertEqual(clean_url_for_log(url), "https://example.com/calendar.ics")

    def test_clean_url_with_query(self):
        url = "https://example.com/calendar.ics?token=secret123&other=param"
        expected = "https://example.com/calendar.ics?query=%5BREDACTED%5D"
        # Note: urlunparse might reconstruct query string differently depending on impl
        # Ideally we want query to be replaced or removed.
        # Let's see what my implementation will do.
        # If I replace query with "[REDACTED]", urlunparse will likely put it as ?[REDACTED]
        cleaned = clean_url_for_log(url)
        self.assertTrue("secret123" not in cleaned)
        self.assertTrue("[REDACTED]" in cleaned or "REDACTED" in cleaned)

    def test_clean_url_with_creds(self):
        url = "https://user:password@example.com/calendar.ics"
        cleaned = clean_url_for_log(url)
        self.assertEqual(cleaned, "https://example.com/calendar.ics")
        self.assertNotIn("user", cleaned)
        self.assertNotIn("password", cleaned)

    def test_clean_url_with_port(self):
        url = "https://user:pass@example.com:8080/cal"
        cleaned = clean_url_for_log(url)
        self.assertEqual(cleaned, "https://example.com:8080/cal")

    def test_clean_url_invalid(self):
        url = "not_a_url"
        # It might just return it as is if urlparse doesn't fail, or "INVALID_URL" if exception
        # urlparse("not_a_url") works (path="not_a_url").
        # My implementation will just return it.
        # But if I pass None or something that causes exception:
        self.assertEqual(clean_url_for_log(None), "")

    def test_clean_url_exception(self):
        # Pass an object that causes urlparse to fail (e.g. not a string)
        self.assertEqual(clean_url_for_log(123), "INVALID_URL")
