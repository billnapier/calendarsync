/**
 * Palette UX Enhancements
 * Handles loading states for form submissions to improve perceived performance
 * and prevent double-submissions.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Select all forms that might need a loading state
    const forms = document.querySelectorAll('form');

    forms.forEach(form => {
        const action = form.getAttribute('action');
        if (!action) return;

        let loadingText = null;

        // Determine loading text based on action
        if (action.includes('/run_sync')) {
            loadingText = 'Syncing...';
        } else if (action === '/create_sync') {
            loadingText = 'Creating...';
        } else if (action.includes('/edit_sync')) {
            loadingText = 'Saving...';
        }

        if (loadingText) {
            form.addEventListener('submit', (e) => {
                // Find the submit button
                const btn = form.querySelector('button[type="submit"]');

                // Only proceed if button exists and isn't already disabled
                if (btn && !btn.disabled) {
                    // Store original text to restore if needed (e.g. bfcache)
                    btn.dataset.originalText = btn.textContent;

                    // Update UI state
                    btn.disabled = true;
                    btn.textContent = loadingText;
                    btn.style.cursor = 'wait';

                    // Note: We do not prevent default here, allowing the form to submit.
                }
            });
        }
    });

    // Handle Back/Forward Cache (bfcache)
    // If user navigates back to the page, ensure buttons are re-enabled.
    window.addEventListener('pageshow', (event) => {
        // event.persisted is true if the page was restored from bfcache
        // However, some browsers might not reset the DOM even if persisted is false
        // if it's a simple history navigation. We check all buttons just in case.

        const buttons = document.querySelectorAll('button[type="submit"][disabled]');
        buttons.forEach(btn => {
            if (btn.dataset.originalText) {
                btn.disabled = false;
                btn.textContent = btn.dataset.originalText;
                btn.style.cursor = '';
            }
        });
    });
});
