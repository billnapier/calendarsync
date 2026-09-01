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

                // Disable interactions via pointer-events (handled by .btn-loading CSS usually)
                // We rely on the dataset.submitting flag to prevent double submissions.
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
                if (submitBtn.dataset.originalContent) {
                    submitBtn.innerHTML = submitBtn.dataset.originalContent;
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

    // Initialize Copy to Clipboard buttons
    function initCopyButtons() {
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.btn-copy');
            if (!btn) return;

            const textToCopy = btn.dataset.copyText;
            if (!textToCopy) return;

            e.preventDefault();

            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalText = btn.textContent;
                // Store original text if not already stored (to handle rapid clicks)
                if (!btn.dataset.originalText) {
                    btn.dataset.originalText = originalText;
                }

                btn.textContent = 'Copied!';
                btn.classList.add('btn-copy-success');

                setTimeout(() => {
                    // Restore original text
                    if (btn.dataset.originalText) {
                        btn.textContent = btn.dataset.originalText;
                        delete btn.dataset.originalText;
                    }
                    btn.classList.remove('btn-copy-success');
                }, 2000);
            }).catch(err => {
                console.error('Failed to copy: ', err);
            });
        });
    }

    // Initialize Keyboard Shortcuts (Ctrl+Enter to submit)
    function initKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                const activeElement = document.activeElement;
                if (!activeElement) return;

                const form = activeElement.closest('form');
                if (!form) return;

                // Find the primary submit button
                // We prioritize buttons with type="submit" that are NOT hidden
                const submitBtn = Array.from(form.querySelectorAll('button[type="submit"]'))
                    .find(btn => btn.offsetParent !== null && !btn.disabled);

                if (submitBtn) {
                    e.preventDefault(); // Prevent default browser behavior (if any)
                    submitBtn.click();
                }
            }
        });
    }

    // Alert close button handler
    function initAlertCloseButtons() {
        document.addEventListener('click', function(e) {
            const closeBtn = e.target.closest('.alert-close');
            if (closeBtn && closeBtn.parentElement) {
                closeBtn.parentElement.remove();
            }
        });
    }

    // Preset chips handler
    function initPresetChips() {
        document.addEventListener('click', function(e) {
            const chip = e.target.closest('.preset-chips .chip');
            if (!chip) return;
            const presetText = chip.dataset.preset || chip.getAttribute('data-preset');
            if (!presetText) return;
            const textarea = document.getElementById('filterPrompt');
            if (textarea) {
                textarea.value = presetText;
                textarea.focus();
            }
        });
    }

    // Modal & tab handlers
    function initModalsAndTabs() {
        document.addEventListener('click', function(e) {
            // Open Subscribe Modal
            if (e.target.closest('.btn-open-subscribe-modal')) {
                const modal = document.getElementById('subscribeModal');
                if (modal) modal.classList.remove('hidden');
                return;
            }
            // Close Subscribe Modal
            if (e.target.closest('.modal-close, [data-action="close-subscribe-modal"]')) {
                const modal = document.getElementById('subscribeModal');
                if (modal) modal.classList.add('hidden');
                return;
            }
            // Switch Subscribe Tab
            const tabBtn = e.target.closest('.tab-nav .tab-btn');
            if (tabBtn) {
                const tabId = tabBtn.dataset.tabId;
                if (!tabId) return;
                document.querySelectorAll('.tab-nav .tab-btn').forEach(btn => btn.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(content => content.classList.add('hidden'));

                tabBtn.classList.add('active');
                const selected = document.getElementById(tabId);
                if (selected) selected.classList.remove('hidden');
            }
        });
    }

    function escapeHtml(text) {
        if (!text) return '';
        return text.replace(/&/g, "&amp;")
                   .replace(/</g , "&lt;")
                   .replace(/>/g, "&gt;")
                   .replace(/"/g, "&quot;")
                   .replace(/'/g, "&#039;");
    }

    // Prompt Preview handler
    function initPromptPreview() {
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('#btnTestPrompt');
            if (!btn) return;

            const sourceUrlInput = document.getElementById('sourceUrl');
            const filterPromptInput = document.getElementById('filterPrompt');
            const csrfTokenInput = document.getElementById('csrfToken');

            if (!sourceUrlInput || !filterPromptInput) return;

            const sourceUrl = sourceUrlInput.value.trim();
            const filterPrompt = filterPromptInput.value.trim();
            const csrfToken = csrfTokenInput ? csrfTokenInput.value : '';

            const loading = document.getElementById('previewLoading');
            const resultsDiv = document.getElementById('previewResults');

            if (!sourceUrl || !filterPrompt) {
                if (resultsDiv) {
                    resultsDiv.classList.remove('hidden');
                    resultsDiv.innerHTML = `<div class="alert alert-warning">⚠️ Please enter both a <strong>Source iCal URL</strong> and a <strong>Filter Prompt</strong> before testing.</div>`;
                }
                return;
            }

            btn.disabled = true;
            if (loading) loading.classList.remove('hidden');
            if (resultsDiv) {
                resultsDiv.classList.add('hidden');
                resultsDiv.innerHTML = '';
            }

            const testUrl = btn.dataset.testUrl || '/smart_filter/test';

            fetch(testUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    source_url: sourceUrl,
                    filter_prompt: filterPrompt,
                    csrf_token: csrfToken
                })
            })
            .then(res => res.json())
            .then(data => {
                btn.disabled = false;
                if (loading) loading.classList.add('hidden');
                if (resultsDiv) resultsDiv.classList.remove('hidden');

                if (!data.success) {
                    if (resultsDiv) resultsDiv.innerHTML = `<div class="alert alert-danger">Preview Error: ${data.error}</div>`;
                    return;
                }

                const evals = data.evaluations || [];
                if (evals.length === 0) {
                    if (resultsDiv) resultsDiv.innerHTML = `<div class="alert alert-info">No candidate events found in source feed preview.</div>`;
                    return;
                }

                let html = `<div class="preview-header"><h4>Preview Results (${evals.length} events evaluated)</h4></div><div class="preview-grid">`;

                evals.forEach(ev => {
                    const isInc = ev.include;
                    const statusClass = isInc ? 'preview-included' : 'preview-excluded';
                    const icon = isInc ? '✅ INCLUDED' : '❌ EXCLUDED';
                    html += `
                        <div class="preview-item ${statusClass}">
                            <div class="preview-item-header">
                                <span class="preview-status-badge">${icon}</span>
                                <strong class="preview-item-title">${escapeHtml(ev.summary)}</strong>
                            </div>
                            <div class="preview-reason">${escapeHtml(ev.reason)}</div>
                        </div>
                    `;
                });

                html += `</div>`;
                if (resultsDiv) resultsDiv.innerHTML = html;
            })
            .catch(err => {
                btn.disabled = false;
                if (loading) loading.classList.add('hidden');
                if (resultsDiv) {
                    resultsDiv.classList.remove('hidden');
                    resultsDiv.innerHTML = `<div class="alert alert-danger">Network Error: ${err.message}</div>`;
                }
            });
        });
    }

    document.addEventListener('DOMContentLoaded', function() {
        initSubmitButtons();
        initAutoDismissAlerts();
        initCopyButtons();
        initKeyboardShortcuts();
        initAlertCloseButtons();
        initPresetChips();
        initModalsAndTabs();
        initPromptPreview();
    });
})();

