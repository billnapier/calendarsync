import unittest
from werkzeug.datastructures import MultiDict
from app.main.routes import _get_sources_from_form


class TestSourceValidation(unittest.TestCase):
    def test_rejects_invalid_url(self):
        # Validation should reject invalid URLs
        form = MultiDict(
            [
                ("source_types", "ical"),
                ("source_urls", "invalid-url"),
                ("source_prefixes", ""),
                ("source_ids", ""),
            ]
        )

        with self.assertRaises(ValueError) as cm:
            _get_sources_from_form(form)
        self.assertIn("Invalid scheme", str(cm.exception))

    def test_rejects_private_ip(self):
        # Validation should reject private IPs
        form = MultiDict(
            [
                ("source_types", "ical"),
                ("source_urls", "http://192.168.1.1/cal.ics"),
                ("source_prefixes", ""),
                ("source_ids", ""),
            ]
        )

        with self.assertRaises(ValueError) as cm:
            _get_sources_from_form(form)
        self.assertIn("Restricted IP address", str(cm.exception))

    def test_accepts_valid_url(self):
        # Validation should accept valid URLs (that don't resolve to private IPs)
        # Note: validate_url passes if DNS resolution fails, so we can use a dummy domain
        form = MultiDict(
            [
                ("source_types", "ical"),
                ("source_urls", "https://example.com/cal.ics"),
                ("source_prefixes", ""),
                ("source_ids", ""),
            ]
        )

        sources = _get_sources_from_form(form)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], "https://example.com/cal.ics")


if __name__ == "__main__":
    unittest.main()
