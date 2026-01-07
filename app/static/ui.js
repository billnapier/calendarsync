/**
 * UI Enhancement Script
 * Handles button loading states and other global UX interactions.
 */

(function () {
    'use strict';

    function initSubmitButtons() {
        const forms = document.querySelectorAll('form');

        forms.forEach(form => {
            form.addEventListener('submit', function (e) {
                // Prevent double submission if already submitting
                if (form.dataset.submitting === "true") {
                    e.preventDefault();
                    return;
                }

                const submitBtn = form.querySelector('button[type="submit"]');
                if (!submitBtn) return;

                // Check for validation before disabling
                if (!form.checkValidity()) return;

                // Mark form as submitting
                form.dataset.submitting = "true";

                // Save original text and width to prevent layout jump
                const originalText = submitBtn.innerText;
                const width = submitBtn.offsetWidth;

                submitBtn.dataset.originalText = originalText;
                submitBtn.style.width = `${width}px`;

                // Set loading state
                const loadingText = submitBtn.dataset.loadingText || 'Loading...';
                submitBtn.innerText = loadingText;
                submitBtn.disabled = true;
                submitBtn.classList.add('btn-loading');

                // If it's a delete action (using onsubmit confirm), the confirm happens BEFORE this event
                // because inline handlers run first. So if we are here, the user said YES.
            });
        });
    }

    // Restore buttons when navigating back (bfcache)
    window.addEventListener('pageshow', function (event) {
        const forms = document.querySelectorAll('form');
        forms.forEach(form => {
            delete form.dataset.submitting;
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && submitBtn.disabled && submitBtn.dataset.originalText) {
                submitBtn.innerText = submitBtn.dataset.originalText;
                submitBtn.disabled = false;
                submitBtn.style.width = '';
                submitBtn.classList.remove('btn-loading');
            }
        });
    });

    document.addEventListener('DOMContentLoaded', initSubmitButtons);
})();