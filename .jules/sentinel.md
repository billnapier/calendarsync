# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2026-01-27 - Missing Rate Limiting on Sync
**Vulnerability:** The manual sync endpoint (`/sync/<id>`) lacked rate limiting, allowing authenticated users to trigger resource-intensive background jobs repeatedly.
**Learning:** Even if an operation is backgrounded or asynchronous, the *trigger* itself must be rate-limited if the backend work is expensive. Assuming "authenticated users are trusted" is dangerous for resource consumption.
**Prevention:** Implement rate limiting (e.g., using `last_synced_at` timestamps) on all endpoints that trigger expensive operations, even for authenticated users.
