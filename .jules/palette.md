## 2024-05-23 - [Loading States for Sync Operations]
**Learning:** Users lack confidence when long-running operations (like syncing calendars) have no immediate feedback. Adding a simple loading state ("Syncing...") significantly improves perceived performance and prevents double-clicks.
**Action:** Always implement disabled/loading states for form submissions, especially for backend operations known to be slow. Use a centralized script to apply this pattern consistently across separate templates.
