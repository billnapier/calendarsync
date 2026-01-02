"""
Security utilities for the application.
"""
import socket
import ipaddress
from urllib.parse import urlparse, urljoin
import requests

def validate_url(url):
    """
    Validates a URL to prevent SSRF.
    Ensures scheme is http/https and hostname does not resolve to private IPs.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}") from e

    if parsed.scheme not in ('http', 'https'):
        raise ValueError("Invalid scheme: Only HTTP and HTTPS are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid hostname")

    try:
        # Resolve hostname to IPs.
        # using proto=socket.IPPROTO_TCP to filter irrelevant results
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)

        for res in addr_info:
            # res[4] is sockaddr, res[4][0] is the IP string
            ip_str = res[4][0]
            ip = ipaddress.ip_address(ip_str)

            if ip.is_private:
                raise ValueError(f"Restricted IP address: {ip_str}")

            if ip.is_loopback:
                raise ValueError(f"Restricted IP address: {ip_str}")

            if ip.is_link_local:
                raise ValueError(f"Restricted IP address: {ip_str}")

    except socket.gaierror:
        # DNS resolution failed. We treat this as safe-ish (can't connect)
        # but requests will fail later anyway.
        pass

def safe_requests_get(url, **kwargs):
    """
    Drop-in replacement for requests.get that validates the URL and any redirects.
    """
    validate_url(url)

    def check_redirect(resp, *args, **kwargs): # pylint: disable=unused-argument
        if resp.is_redirect and 'Location' in resp.headers:
            new_url = urljoin(resp.url, resp.headers['Location'])
            validate_url(new_url)

    # Add our hook to existing hooks if any, or create new dict
    hooks = kwargs.get('hooks', {})
    if 'response' not in hooks:
        hooks['response'] = []
    elif not isinstance(hooks['response'], list):
        hooks['response'] = [hooks['response']]

    hooks['response'].append(check_redirect)
    kwargs['hooks'] = hooks

    return requests.get(url, **kwargs)
