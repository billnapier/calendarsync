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

## 2024-05-25 - Feedback Loop & Template Constraints
**Learning:** The application lacks a shared base template, making global UI elements (like flash messages) difficult to implement DRYly. However, since most actions (create, edit, delete, run) redirect to the dashboard (`index.html`), placing the feedback container solely on the dashboard is an effective, lightweight solution that avoids code duplication across independent templates.
**Action:** Implemented a Flask flash message system rendered only on `index.html`. For future features, prioritize redirect-to-dashboard flows to leverage this centralized feedback mechanism, or consider a larger refactor to introduce a `base.html` if local feedback becomes necessary.

## 2026-01-19 - Visual Feedback for Loading States
**Learning:** While changing button text to "Loading..." is helpful, it lacks the immediate visual dynamism that confirms an active process. Users associate spinning indicators with "working" states more strongly than static text changes.
**Action:** Enhanced the existing loading state pattern by injecting a CSS-only spinner alongside the loading text. This was achieved by modifying the reusable `ui.js` script to use `innerHTML` injection, ensuring a consistent and polished experience across all forms without requiring changes to individual templates.

## 2026-01-20 - Focus Management in Dynamic Forms
**Learning:** In forms where users add items dynamically (like "Add Source"), the default browser behavior leaves focus on the "Add" button. This forces users to manually tab or click into the new fields, slowing down data entry and breaking flow.
**Action:** Updated `app/static/sync_form.js` to programmatically move focus to the first interactive element of a newly added row. Additionally, added `autofocus` to the primary field on the Create page. This "invisible" UX improvement significantly speeds up repeated actions and supports power users/keyboard navigation. Note: When querying for focus targets, always exclude hidden inputs (`input:not([type="hidden"])`) to ensure focus lands on a visible control.

## 2026-01-20 - List Item Animations
**Learning:** Instantaneous removal or appearance of list items feels abrupt and can be jarring. It lacks "physicality" and makes the interface feel less polished.
**Action:** Implemented CSS transitions and animations (`fade-in` and `fade-out`) for adding and removing dynamic rows. Used `setTimeout` (matching CSS duration) to ensure reliable DOM removal after the visual effect completes, avoiding potential issues with `transitionend` firing. This adds a sense of weight and quality to the interaction.

## 2026-01-21 - Auto-dismiss Alerts
**Learning:** Success and info messages (toasts) should be transient to keep the interface clean, while errors must remain until dismissed by the user to ensure they are seen.
**Action:** Implemented auto-dismiss logic in `ui.js` for `.alert-success` and `.alert-info` with a 5-second delay and smooth fade-out transition. Ensure error alerts (`.alert-danger`) are excluded from auto-dismiss.
