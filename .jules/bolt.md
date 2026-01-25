# Bolt's Journal - Critical Learnings

## 2024-05-22 - Parallelizing iCal Name Resolution
**Learning:** Python's `concurrent.futures` is a powerful tool for I/O-bound tasks like fetching multiple URLs. When refactoring synchronous loops to parallel ones, always ensure necessary imports are present and handle exceptions per-task to prevent one failure from blocking the entire batch.
**Action:** When introducing parallelism, verify imports and ensure robust per-item error handling.

## 2024-05-23 - Early Filtering in Parallel Data Processing
**Learning:** When processing large external datasets in parallel (e.g., iCal feeds), filtering data as early as possible—inside the worker threads—significantly reduces memory overhead and serialization costs compared to filtering the aggregated results later.
**Action:** Push filtering logic down into individual data fetch/parse functions, especially when using `ThreadPoolExecutor` or `ProcessPoolExecutor`.
