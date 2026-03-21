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

    // Helper to handle source type change (iCal vs Google vs EasyCloud)
    function handleSourceTypeChange(select) {
        const entry = select.closest('.ical-entry');
        const typeInput = entry.querySelector('input[name="source_types"]');
        const googleInput = entry.querySelector('.google-input');
        const icalInput = entry.querySelector('.ical-input');
        const easycloudInput = entry.querySelector('.easycloud-input');
        const idInput = entry.querySelector('input[name="source_ids"]');
        const urlInput = entry.querySelector('input[name="source_urls"]');

        // Update hidden type input
        if (typeInput) typeInput.value = select.value;

        if (googleInput) googleInput.classList.add('hidden');
        if (icalInput) icalInput.classList.add('hidden');
        if (easycloudInput) easycloudInput.classList.add('hidden');

        if (select.value === 'google') {
            if (googleInput) googleInput.classList.remove('hidden');
            if (urlInput) urlInput.value = '';
        } else if (select.value === 'easycloud') {
            if (easycloudInput) easycloudInput.classList.remove('hidden');
            if (idInput) idInput.value = '';
            if (urlInput) urlInput.value = '';
        } else {
            if (icalInput) icalInput.classList.remove('hidden');
            if (idInput) idInput.value = '';
            const visibleSelect = entry.querySelector('select[name="source_ids_visible"]');
            if (visibleSelect) visibleSelect.value = "";
            const easycloudSelect = entry.querySelector('select[name="easycloud_ids_visible"]');
            if (easycloudSelect) easycloudSelect.value = "";
        }
    }

    // Helper to handle google calendar selection
    function handleGoogleCalChange(select) {
        const entry = select.closest('.ical-entry');
        const idInput = entry.querySelector('input[name="source_ids"]');
        if (idInput) idInput.value = select.value;
    }

    // Helper to handle easycloud calendar selection
    function handleEasyCloudChange(select) {
        const entry = select.closest('.ical-entry');
        const idInput = entry.querySelector('input[name="source_ids"]');
        const urlInput = entry.querySelector('input[name="source_urls"]');
        if (idInput) idInput.value = select.value;
        const selectedOption = select.options[select.selectedIndex];
        if (urlInput && selectedOption) {
            urlInput.value = selectedOption.dataset.url || "";
        }
    }

    // Add new source entry
    function addSourceEntry() {
        const container = document.getElementById('ical-container');
        const template = document.getElementById('source-entry-template');
        if (!container || !template) return;

        const clone = template.content.cloneNode(true);
        container.appendChild(clone);
        updateRemoveButtons();

        // Focus the first input of the new entry for better UX
        const newEntry = container.lastElementChild;
        if (newEntry) {
            newEntry.classList.add('adding');
            // Find the first visible/interactive input or select
            // We skip hidden inputs to ensure we focus on the user-facing "Type" select
            const firstInput = newEntry.querySelector('select, input:not([type="hidden"])');
            if (firstInput) {
                firstInput.focus();
            }
        }
    }

    // Remove source entry
    function removeSourceEntry(btn) {
        const entry = btn.closest('.ical-entry');
        // Prevent removing the last entry
        if (document.querySelectorAll('.ical-entry').length > 1) {
            entry.classList.add('removing');
            // Wait for transition to finish (matches CSS 0.2s)
            setTimeout(() => {
                entry.remove();
                updateRemoveButtons();
            }, 200);
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
                
                // Handle EasyCloud Change
                if (e.target.name === 'easycloud_ids_visible') {
                    handleEasyCloudChange(e.target);
                }
            });
        }
    });
})();
