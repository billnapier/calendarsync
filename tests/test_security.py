import unittest
from unittest.mock import patch, MagicMock
import socket
from app.security import validate_url, safe_requests_get
import requests

class TestSecurity(unittest.TestCase):
    def test_validate_url_success(self):
        # We need to mock getaddrinfo to return a public IP
        with patch('socket.getaddrinfo') as mock_dns:
            # 8.8.8.8 is Google DNS (Public)
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 80))]
            try:
                validate_url('http://example.com')
            except ValueError:
                self.fail("validate_url raised ValueError unexpectedly!")

    def test_validate_url_private_ip(self):
        with patch('socket.getaddrinfo') as mock_dns:
            # 127.0.0.1 is Loopback/Private
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))]
            with self.assertRaises(ValueError) as cm:
                validate_url('http://localhost')
            self.assertIn("Restricted IP", str(cm.exception))

        with patch('socket.getaddrinfo') as mock_dns:
            # 10.0.0.1 is Private
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 80))]
            with self.assertRaises(ValueError):
                validate_url('http://internal-service')

        with patch('socket.getaddrinfo') as mock_dns:
            # 169.254.169.254 is Link-Local/Private (Metadata service)
            mock_dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('169.254.169.254', 80))]
            with self.assertRaises(ValueError):
                validate_url('http://169.254.169.254')

    def test_validate_url_scheme(self):
        with self.assertRaises(ValueError) as cm:
            validate_url('ftp://example.com')
        self.assertIn("Invalid scheme", str(cm.exception))

    @patch('app.security.requests.get')
    @patch('app.security.validate_url')
    def test_safe_requests_get(self, mock_validate, mock_get):
        # Setup
        url = 'http://example.com'

        # execution
        safe_requests_get(url)

        # Verify validate_url called
        mock_validate.assert_called_with(url)

        # Verify requests.get called with hooks
        mock_get.assert_called()
        args, kwargs = mock_get.call_args
        self.assertIn('hooks', kwargs)
        self.assertIn('response', kwargs['hooks'])

    @patch('app.security.validate_url')
    def test_safe_requests_get_redirect_hook(self, mock_validate):
        # We need to simulate the hook execution
        # safe_requests_get returns the result of requests.get
        # The hook is inside safe_requests_get.
        # We can't easily unit test the inner function without invoking it via requests or extracting it.
        # But we can verify that if we pass a redirect response, validate_url is called again.

        # Let's use a real requests.get with a mock response?
        # No, that makes network calls.

        # We'll extract the hook logic by using a side_effect on requests.get
        # to invoke the hook manually.

        def side_effect(url, **kwargs):
            hooks = kwargs.get('hooks', {}).get('response', [])
            # Create a mock redirect response
            mock_resp = MagicMock()
            mock_resp.is_redirect = True
            mock_resp.headers = {'Location': 'http://redirected.com'}
            mock_resp.url = 'http://original.com'

            # Invoke hooks
            for hook in hooks:
                hook(mock_resp)

            return mock_resp

        with patch('app.security.requests.get', side_effect=side_effect):
            safe_requests_get('http://original.com')

            # validate_url should be called for original and redirected
            self.assertEqual(mock_validate.call_count, 2)
            mock_validate.assert_any_call('http://original.com')
            mock_validate.assert_any_call('http://redirected.com')

if __name__ == '__main__':
    unittest.main()
