/**
 * Palette UX Enhancements
 * Handles loading states for form submissions to improve perceived performance
 * and prevent double-submissions.
 */

document.addEventListener('DOMContentLoaded', () => {
    // Select all forms that might need a loading state
    const forms = document.querySelectorAll('form');

    forms.forEach(form => {
        form.addEventListener('submit', (e) => {
            // Find the submitter (button or input that triggered the submit)
            // Note: e.submitter is supported in modern browsers
            const submitter = e.submitter || form.querySelector('button[type="submit"], input[type="submit"]');

            if (submitter && !submitter.disabled) {
                const loadingText = submitter.getAttribute('data-loading-text');

                if (loadingText) {
                    // Store original text/value to restore if needed (e.g. bfcache)
                    if (submitter.tagName === 'INPUT') {
                        submitter.dataset.originalValue = submitter.value;
                        submitter.value = loadingText;
                    } else {
                        submitter.dataset.originalText = submitter.textContent;
                        submitter.textContent = loadingText;
                    }

                    // Update UI state
                    submitter.disabled = true;
                    submitter.style.cursor = 'wait';
                }
            }
        });
    });

    // Handle Back/Forward Cache (bfcache)
    // If user navigates back to the page, ensure buttons are re-enabled.
    window.addEventListener('pageshow', (event) => {
        const buttons = document.querySelectorAll('button[type="submit"][disabled], input[type="submit"][disabled]');
        buttons.forEach(btn => {
            if (btn.tagName === 'INPUT' && btn.dataset.originalValue) {
                btn.disabled = false;
                btn.value = btn.dataset.originalValue;
                btn.style.cursor = '';
            } else if (btn.dataset.originalText) {
                btn.disabled = false;
                btn.textContent = btn.dataset.originalText;
                btn.style.cursor = '';
            }
        });
    });
});
