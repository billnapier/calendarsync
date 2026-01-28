# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2025-01-26 - Inline Event Handlers and CSP
**Vulnerability:** An inline `onclick` handler was found in `index.html` which conflicted with the strict `script-src` Content Security Policy (missing `'unsafe-inline'`), rendering the functionality (alert dismissal) broken.
**Learning:** Strict CSP is effective at blocking inline scripts, but can silently break UI features if they rely on legacy inline handlers. Manual verification or frontend tests are crucial when tightening CSP.
**Prevention:** Use event delegation in external JavaScript files for all user interactions. Avoid `on*` attributes in HTML.
