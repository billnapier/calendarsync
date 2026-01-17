## 2024-05-23 - Submit Button Loading States
**Learning:** Users lack feedback during async form submissions (sync/create/edit), leading to uncertainty and potential double-clicks. Adding a simple loading state ("Syncing...") significantly improves perceived performance and prevents double-clicks.
**Action:** Implemented a reusable `ui.js` script that intercepts form submissions, disables the submit button, and updates its text based on a `data-loading-text` attribute. Using `pageshow` event listener ensures buttons are reset when navigating back via browser history (bfcache), a critical detail for smooth UX. Always implement disabled/loading states for form submissions, especially for backend operations known to be slow. Use a centralized script to apply this pattern consistently across separate templates.

## 2024-05-24 - Destructive Actions in Forms
**Learning:** Users need a way to delete configurations, but it should be distinct from editing. Hiding destructive actions or mixing them with primary actions can lead to accidents or frustration when the feature is missing.
**Action:** Implemented a "Danger Zone" pattern in the `edit_sync` form. This separates the delete action visually (using color and spacing) from the main "Save" action, reducing the risk of accidental clicks while making the feature discoverable. Always confirm destructive actions with a dialog.

## 2024-05-24 - Focus Visible Indicators
**Learning:** Default browser focus rings are often suppressed by `outline: none` or lost in design, making navigation impossible for keyboard users.
**Action:** Added a global `:focus-visible` style in `style.css` using the primary color. This ensures all interactive elements (buttons, links, inputs) have a clear, consistent visual indicator when focused via keyboard, without affecting mouse users.

## 2024-05-25 - Empty State Delight
**Learning:** A plain text empty state ("You haven't created any syncs yet") is functional but uninspiring. It misses an opportunity to guide the user and reinforce the value proposition.
**Action:** Enhanced the dashboard empty state with a visual icon (using existing `feature-icon` styles), a clear heading, and a primary call-to-action button. This treats the "zero data" state as a first-class UI state, encouraging the user to take the first step. Always design empty states to be welcoming and actionable.
