# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2024-05-25 - Sensitive Data in Logs
**Vulnerability:** Raw URLs containing query parameters (tokens) or Basic Auth credentials were being logged in error messages.
**Learning:** External inputs, especially URLs from users, often contain secrets. Logging them raw creates a persistent leak in log storage.
**Prevention:** Sanitize all URLs before logging using a dedicated utility like `clean_url_for_log` that strips credentials and query parameters.
