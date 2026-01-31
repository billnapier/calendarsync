# Sentinel Journal

## 2024-05-24 - Journal Inited
**Vulnerability:** N/A
**Learning:** Initialized the journal.
**Prevention:** N/A

## 2024-05-24 - Validation Timing for SSRF
**Vulnerability:** User input for external URLs was not validated at configuration time, only at usage time.
**Learning:** While runtime protection (SSRF checks in `safe_requests_get`) prevents exploitation, allowing invalid data to be stored degrades data integrity and user experience.
**Prevention:** Validate inputs (like URLs) at the boundary (API/Form submission) to fail fast, even if runtime checks are also present (defense in depth).

## 2024-05-25 - Unbounded Download DoS
**Vulnerability:** `requests.get` without `stream=True` was used to fetch external iCal files, allowing an attacker to cause an Out-Of-Memory (OOM) crash by serving a very large file.
**Learning:** Default behavior of HTTP clients often loads full response into memory. When dealing with user-supplied URLs, explicit streaming and size limits are mandatory.
**Prevention:** Use `stream=True`, iterate over chunks, and enforce a maximum byte limit (e.g., 10MB) for all external fetches.
