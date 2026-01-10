/**
 * Sync Form Logic
 * Handles dynamic source addition/removal and type toggling.
 * Replaces inline event handlers to support strict CSP.
 */

(function () {
    'use strict';

    // Helper to update remove buttons visibility
    // We only hide the remove button if there is exactly one entry.
    function updateRemoveButtons() {
        const entries = document.querySelectorAll('.ical-entry');
        entries.forEach((entry) => {
            const btn = entry.querySelector('.btn-danger'); // Remove button
            if (!btn) return;

            if (entries.length === 1) {
                btn.style.display = 'none';
            } else {
                btn.style.display = 'inline-flex';
            }
        });
    }

    // Helper to handle source type change (iCal vs Google)
    function handleSourceTypeChange(select) {
        const entry = select.closest('.ical-entry');
        const typeInput = entry.querySelector('input[name="source_types"]');
        const googleInput = entry.querySelector('.google-input');
        const icalInput = entry.querySelector('.ical-input');
        const idInput = entry.querySelector('input[name="source_ids"]');
        const urlInput = entry.querySelector('input[name="source_urls"]');

        // Update hidden type input
        if (typeInput) typeInput.value = select.value;

        if (select.value === 'google') {
            googleInput.classList.remove('hidden');
            icalInput.classList.add('hidden');
            // Clear iCal URL when switching to Google
            if (urlInput) urlInput.value = '';
        } else {
            googleInput.classList.add('hidden');
            icalInput.classList.remove('hidden');
            // Clear Google ID when switching to iCal
            if (idInput) idInput.value = '';
            const visibleSelect = entry.querySelector('select[name="source_ids_visible"]');
            if (visibleSelect) visibleSelect.value = "";
        }
    }

    // Helper to handle google calendar selection
    function handleGoogleCalChange(select) {
        const entry = select.closest('.ical-entry');
        const idInput = entry.querySelector('input[name="source_ids"]');
        if (idInput) idInput.value = select.value;
    }

    // Add new source entry
    function addSourceEntry() {
        const container = document.getElementById('ical-container');
        const template = document.getElementById('source-entry-template');
        if (!container || !template) return;

        const clone = template.content.cloneNode(true);
        container.appendChild(clone);
        updateRemoveButtons();
    }

    // Remove source entry
    function removeSourceEntry(btn) {
        const entry = btn.closest('.ical-entry');
        // Prevent removing the last entry
        if (document.querySelectorAll('.ical-entry').length > 1) {
            entry.remove();
            updateRemoveButtons();
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        const container = document.getElementById('ical-container');
        const addBtn = document.getElementById('add-source-btn');

        // Initial update in case of page reload or edit mode
        updateRemoveButtons();

        // Event listener for Add button
        if (addBtn) {
            addBtn.addEventListener('click', addSourceEntry);
        }

        // Event delegation for interactions within the list
        if (container) {
            container.addEventListener('click', function(e) {
                // Handle Remove Button
                // We check for .btn-danger or closest .btn-danger
                const removeBtn = e.target.closest('.btn-danger');
                if (removeBtn && container.contains(removeBtn)) {
                    removeSourceEntry(removeBtn);
                }
            });

            container.addEventListener('change', function(e) {
                // Handle Source Type Change
                // The select for type is inside .source-type-group
                if (e.target.closest('.source-type-group') && e.target.tagName === 'SELECT') {
                    handleSourceTypeChange(e.target);
                }

                // Handle Google Calendar Select Change
                // This select has name="source_ids_visible"
                if (e.target.name === 'source_ids_visible') {
                    handleGoogleCalChange(e.target);
                }
            });
        }
    });
})();
