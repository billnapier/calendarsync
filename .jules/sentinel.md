# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2024-05-24 - DoS Protection via Resource Limits
**Vulnerability:** Users could create an unlimited number of sync configurations, leading to potential storage exhaustion and resource depletion during sync operations.
**Learning:** Even if individual resources (like sync sources) are limited, the aggregate number of resource containers (syncs) must also be capped to prevent horizontal scaling attacks.
**Prevention:** Implement limits on the number of resource instances a user can create (e.g., `MAX_SYNCS_PER_USER = 10`).
