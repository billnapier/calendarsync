## 2024-05-23 - Submit Button Loading States
**Learning:** Users lack feedback during async form submissions (sync/create/edit), leading to uncertainty and potential double-clicks. Adding a simple loading state ("Syncing...") significantly improves perceived performance and prevents double-clicks.
**Action:** Implemented a reusable `ui.js` script that intercepts form submissions, disables the submit button, and updates its text based on a `data-loading-text` attribute. Using `pageshow` event listener ensures buttons are reset when navigating back via browser history (bfcache), a critical detail for smooth UX. Always implement disabled/loading states for form submissions, especially for backend operations known to be slow. Use a centralized script to apply this pattern consistently across separate templates.

## 2024-05-24 - Destructive Actions in Forms
**Learning:** Users need a way to delete configurations, but it should be distinct from editing. Hiding destructive actions or mixing them with primary actions can lead to accidents or frustration when the feature is missing.
**Action:** Implemented a "Danger Zone" pattern in the `edit_sync` form. This separates the delete action visually (using color and spacing) from the main "Save" action, reducing the risk of accidental clicks while making the feature discoverable. Always confirm destructive actions with a dialog.

## 2024-05-25 - Form Input Types and Validation
**Learning:** Using `type="text"` for URL inputs forces users on mobile devices to switch keyboards manually, increasing friction. Additionally, failing to mark essential fields as `required` allows for empty submissions that break backend logic or require server-side error handling which disrupts the user flow.
**Action:** Updated `source_urls` to use `type="url"` to trigger the correct mobile keyboard and leverage browser validation for protocol checks. Added `required` attributes to both `source_urls` and `source_ids_visible` to ensure data integrity before submission. Using browser-native constraint validation improves accessibility and provides immediate feedback without round-trips to the server.
