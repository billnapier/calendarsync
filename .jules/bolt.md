# Bolt's Journal - Critical Learnings

## 2024-05-22 - Parallelizing iCal Name Resolution
**Learning:** Python's `concurrent.futures` is a powerful tool for I/O-bound tasks like fetching multiple URLs. When refactoring synchronous loops to parallel ones, always ensure necessary imports are present and handle exceptions per-task to prevent one failure from blocking the entire batch.
**Action:** When introducing parallelism, verify imports and ensure robust per-item error handling.

## 2024-05-24 - Batching Google Calendar Lookups
**Learning:** Google Calendar API's `events().list()` returns a full page of events, which is inefficient when checking for the existence of a small number of specific UIDs (e.g., during incremental sync). Batching individual `list(iCalUID=...)` requests is significantly more efficient for small N (< 100) as it fetches only the required data, avoiding the download of potentially thousands of irrelevant historical events.
**Action:** Use batch requests for specific item lookups when N is small, but maintain a fallback to full list fetching for large N to avoid exceeding batch limits or rate quotas.
