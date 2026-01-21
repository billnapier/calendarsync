# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2024-05-27 - Sensitive Data in Logs
**Vulnerability:** Raw iCal URLs, which may contain authentication tokens or credentials in query parameters, were being written to application logs on fetch failures.
**Learning:** Logging raw input URLs for debugging is dangerous when those URLs can act as credentials. The application frequently handles user-provided external URLs.
**Prevention:** Always sanitize URLs (remove query params/auth) before logging them. Implemented and enforced usage of `clean_url_for_log`.
