/**
 * Shared Reusable Account Type Multiselect Component
 * Matches the UX of area_brick_multiselect.js:
 * - Shows chips for selected items with remove buttons
 * - Toggles dropdown on click/focus
 * - Filters options when typing
 * - Handles adding/removing chips
 * - Calls onChangeCallback
 */
(function (global) {
    'use strict';

    if (!global.ERPAccountTypeInstances) {
        global.ERPAccountTypeInstances = {};
    }

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function initAccountTypeMultiselect(config) {
        const prefix = config.componentId;
        const fieldName = config.fieldName || 'account_type';
        const onChangeCallback = config.onChangeCallback;

        const input = document.getElementById(`${prefix}_search_account_type_input`);
        const dropdown = document.getElementById(`${prefix}_search_account_type_dropdown`);
        const chipsContainer = document.getElementById(`${prefix}_selected_account_types_chips`);
        const container = document.getElementById(`${prefix}_account_type_container`);

        if (!input || !dropdown || !chipsContainer) return;

        function notifyChange() {
            if (typeof onChangeCallback === 'string' && typeof global[onChangeCallback] === 'function') {
                global[onChangeCallback]();
            } else if (typeof onChangeCallback === 'function') {
                onChangeCallback();
            }
        }

        function getSelectedValues() {
            return Array.from(chipsContainer.querySelectorAll(`input[name="${fieldName}"]`)).map(el => el.value);
        }

        function syncOptionChecks() {
            const selected = getSelectedValues();
            dropdown.querySelectorAll('.account-type-option').forEach(opt => {
                const val = opt.getAttribute('data-value');
                const check = opt.querySelector('.option-check');
                if (check) {
                    if (selected.includes(val)) {
                        check.classList.remove('hidden');
                        opt.classList.add('bg-teal-50/70', 'font-bold');
                    } else {
                        check.classList.add('hidden');
                        opt.classList.remove('bg-teal-50/70', 'font-bold');
                    }
                }
            });
        }

        function addChip(val) {
            val = String(val).trim();
            if (!val || chipsContainer.querySelector(`[data-account-type="${val}"]`)) return;

            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-teal-50 text-teal-800 border border-teal-200 text-xs font-semibold shadow-2xs';
            chip.setAttribute('data-account-type', val);
            chip.innerHTML = `
                <input type="hidden" name="${escapeHtml(fieldName)}" value="${escapeHtml(val)}">
                <span>${escapeHtml(val)}</span>
                <button type="button" data-remove-account-type="${escapeHtml(val)}" class="text-teal-500 hover:text-rose-600 focus:outline-hidden inline-flex items-center" title="إزالة">
                    <span class="material-symbols-outlined text-[13px] leading-none">close</span>
                </button>
            `;
            chipsContainer.appendChild(chip);
            syncOptionChecks();
            notifyChange();
        }

        function removeChip(val) {
            val = String(val).trim();
            const chip = chipsContainer.querySelector(`[data-account-type="${val}"]`);
            if (chip) {
                chip.remove();
                syncOptionChecks();
                notifyChange();
            }
        }

        function clearAll() {
            chipsContainer.innerHTML = '';
            syncOptionChecks();
            notifyChange();
        }

        function filterOptions(query) {
            const q = (query || '').toLowerCase().trim();
            dropdown.querySelectorAll('.account-type-option').forEach(opt => {
                const val = (opt.getAttribute('data-value') || '').toLowerCase();
                if (!q || val.includes(q)) {
                    opt.classList.remove('hidden');
                } else {
                    opt.classList.add('hidden');
                }
            });
        }

        // Event listeners
        input.addEventListener('focus', function () {
            filterOptions(input.value);
            syncOptionChecks();
            dropdown.classList.remove('hidden');
        });

        input.addEventListener('input', function () {
            filterOptions(input.value);
            dropdown.classList.remove('hidden');
        });

        dropdown.addEventListener('click', function (e) {
            const opt = e.target.closest('.account-type-option');
            if (!opt) return;
            const val = opt.getAttribute('data-value');
            const selected = getSelectedValues();
            if (selected.includes(val)) {
                removeChip(val);
            } else {
                addChip(val);
            }
            input.value = '';
            filterOptions('');
        });

        chipsContainer.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-remove-account-type]');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            const val = btn.getAttribute('data-remove-account-type');
            removeChip(val);
        });

        document.addEventListener('click', function (e) {
            if (container && !container.contains(e.target) && !chipsContainer.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });

        // Initialize state
        syncOptionChecks();

        global.ERPAccountTypeInstances[prefix] = {
            addChip,
            removeChip,
            clearAll,
            getSelectedValues
        };
    }

    global.initAccountTypeMultiselect = initAccountTypeMultiselect;
})(window);
