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
                const originalContent = submitBtn.innerHTML;
                const width = submitBtn.offsetWidth;

                submitBtn.dataset.originalContent = originalContent;
                submitBtn.style.width = `${width}px`;

                // Set loading state
                const loadingText = submitBtn.dataset.loadingText || 'Loading...';

                submitBtn.textContent = '';

                const spinner = document.createElement('span');
                spinner.className = 'spinner';
                spinner.setAttribute('aria-hidden', 'true');

                submitBtn.appendChild(spinner);
                submitBtn.appendChild(document.createTextNode(' ' + loadingText));

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
                if (submitBtn.disabled && submitBtn.dataset.originalContent) {
                    submitBtn.innerHTML = submitBtn.dataset.originalContent;
                    submitBtn.disabled = false;
                    submitBtn.style.width = '';
                    submitBtn.classList.remove('btn-loading');
                    delete submitBtn.dataset.originalContent;
                }
            });
        });
    });

    // Auto-dismiss success/info alerts
    function initAutoDismissAlerts() {
        const alerts = document.querySelectorAll('.alert-success, .alert-info');
        alerts.forEach(alert => {
            setTimeout(() => {
                alert.classList.add('fade-out');
                // Remove from DOM after transition matches CSS duration (0.5s)
                setTimeout(() => {
                    alert.remove();
                }, 500);
            }, 5000); // 5 seconds delay
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        initSubmitButtons();
        initAutoDismissAlerts();
    });
})();
