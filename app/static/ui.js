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

                // Handle Delete Confirmation (data-confirm attribute)
                const submitBtn = e.submitter;
                if (submitBtn && submitBtn.dataset.confirm) {
                    if (!confirm(submitBtn.dataset.confirm)) {
                        e.preventDefault();
                        return;
                    }
                }

                if (!(submitBtn instanceof HTMLButtonElement) || submitBtn.type !== 'submit') return;

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
            });
        });
    }

    // Restore buttons when navigating back (bfcache)
    window.addEventListener('pageshow', function (event) {
        const forms = document.querySelectorAll('form');
        forms.forEach(form => {
            delete form.dataset.submitting;
            form.querySelectorAll('button[type="submit"]').forEach(submitBtn => {
                if (submitBtn.disabled && submitBtn.dataset.originalText) {
                    submitBtn.innerText = submitBtn.dataset.originalText;
                    submitBtn.disabled = false;
                    submitBtn.style.width = '';
                    submitBtn.classList.remove('btn-loading');
                    delete submitBtn.dataset.originalText;
                }
            });
        });
    });

    document.addEventListener('DOMContentLoaded', initSubmitButtons);
})();
