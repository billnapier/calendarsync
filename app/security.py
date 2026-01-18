"""
Security utilities for the application.
"""

import socket
import ipaddress
from urllib.parse import urlparse, urljoin
import os
import logging
import requests
from flask import request
import google.auth.transport.requests
from google.oauth2 import id_token

logger = logging.getLogger(__name__)


def validate_url(url):
    """
    Validates a URL to prevent SSRF.
    Ensures scheme is http/https and hostname does not resolve to private IPs.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL format: {e}") from e

    if parsed.scheme not in ("http", "https"):
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

    def check_redirect(resp, *args, **kwargs):  # pylint: disable=unused-argument
        if resp.is_redirect and "Location" in resp.headers:
            new_url = urljoin(resp.url, resp.headers["Location"])
            validate_url(new_url)

    def check_ip(resp, *args, **kwargs):  # pylint: disable=unused-argument
        """Verify the connected IP address is not restricted."""
        try:
            # Try to get the IP address from the connection
            # pylint: disable=protected-access
            if hasattr(resp.raw, "_connection") and resp.raw._connection:
                sock = getattr(resp.raw._connection, "sock", None)
                if sock:
                    ip_str = sock.getpeername()[0]
                    ip = ipaddress.ip_address(ip_str)

                    if ip.is_private or ip.is_loopback or ip.is_link_local:
                        raise ValueError(f"Restricted IP address connected: {ip_str}")
        except AttributeError:
            # Handle cases where socket/connection is not available (e.g. mocks)
            pass
        except ValueError as e:
            # Re-raise security violation
            raise e
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Log specific error but don't crash unless it's the security violation
            logger.warning("Could not verify connected IP: %s", e)

    # Add our hook to existing hooks if any, or create new dict
    hooks = kwargs.get("hooks", {})
    if "response" not in hooks:
        hooks["response"] = []
    elif not isinstance(hooks["response"], list):
        hooks["response"] = [hooks["response"]]

    hooks["response"].append(check_redirect)
    hooks["response"].append(check_ip)
    kwargs["hooks"] = hooks

    timeout = kwargs.pop("timeout", 10)
    return requests.get(url, timeout=timeout, **kwargs)


def verify_task_auth():
    """Verifies that the request is authorized by a service account."""
    if os.environ.get("FLASK_ENV") == "development":
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise ValueError("Missing Authorization header")

    parts = auth_header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise ValueError("Invalid Authorization header format")

    token = parts[1]

    try:
        request_obj = google.auth.transport.requests.Request()
        # Verify the token.
        # Note: We are not verifying audience here because it depends on the
        # dynamic service URL which is not always known in this context.
        # However, we rely on strict allow-listing of the invoker email.
        id_info = id_token.verify_oauth2_token(token, request_obj)

        email = id_info.get("email")
        allowed_email = os.environ.get("SCHEDULER_INVOKER_EMAIL")

        # Fail closed: If no allow-list email is configured, deny everything.
        if not allowed_email:
            logger.error("SCHEDULER_INVOKER_EMAIL not set. Denying task access.")
            raise ValueError("Configuration error: SCHEDULER_INVOKER_EMAIL not set")

        if email != allowed_email:
            raise ValueError(f"Unauthorized email: {email}")

    except Exception as e:
        raise ValueError(f"Invalid token: {e}") from e
