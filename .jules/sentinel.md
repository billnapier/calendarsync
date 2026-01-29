# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2026-02-18 - Missing Enforcement of Available Data
**Vulnerability:** The manual sync endpoint tracked `last_synced_at` but failed to check it, allowing unlimited sync requests despite the data being available for rate limiting.
**Learning:** Presence of audit fields (like timestamps) often creates a false sense of security; developers might assume "we track it, so we control it."
**Prevention:** Explicitly verify that security-relevant data (timestamps, counters) is actually used in decision logic (if statements), not just written to the database.
