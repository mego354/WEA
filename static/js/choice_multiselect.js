/**
 * Shared Reusable Choice Multiselect Component
 * - Works with any list of {value, label} options rendered in choice_multiselect.html
 * - Instant Arabic-normalized & case-insensitive filtering
 * - Chip-based selection with individual removal, Clear All, and keyboard navigation
 * - Touch-friendly min-h-[38px] targets and RTL-safe dropdowns
 */
(function (global) {
    'use strict';

    if (!global.ERPChoiceMultiselectInstances) {
        global.ERPChoiceMultiselectInstances = {};
    }

    function escapeHtml(text) {
        if (text == null) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function cssEscape(val) {
        if (global.CSS && typeof global.CSS.escape === 'function') {
            return global.CSS.escape(String(val));
        }
        return String(val).replace(/["\\]/g, '\\$&');
    }

    function normalizeText(value) {
        if (!value) return '';
        if (typeof global.normalizeArabicSearch === 'function') {
            return global.normalizeArabicSearch(String(value));
        }
        return String(value)
            .toLowerCase()
            .replace(/[\u064B-\u065F\u0670\u0640]/g, '')
            .replace(/[\u0622\u0623\u0625\u0671]/g, '\u0627')
            .replace(/\u0629/g, '\u0647')
            .replace(/\u0649/g, '\u064A')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function matchesQuery(candidate, query) {
        if (typeof global.matchesNormalizedArabic === 'function') {
            return global.matchesNormalizedArabic(candidate, query);
        }
        const nq = normalizeText(query);
        if (!nq) return true;
        const nc = normalizeText(candidate);
        return nq.split(' ').filter(Boolean).every(t => nc.includes(t));
    }

    function initChoiceMultiselect(config) {
        const prefix = config.componentId;
        const fieldName = config.fieldName || 'choice';
        const onChangeCallback = config.onChangeCallback;

        const input = document.getElementById(`${prefix}_search_choice_input`);
        const dropdown = document.getElementById(`${prefix}_search_choice_dropdown`);
        const chipsContainer = document.getElementById(`${prefix}_selected_choices_chips`);
        const container = document.getElementById(`${prefix}_choice_container`);
        const clearBtn = document.getElementById(`${prefix}_choice_clear_btn`);
        const emptyState = document.getElementById(`${prefix}_choice_empty_state`);

        if (!input || !dropdown || !chipsContainer) return;

        function notifyChange() {
            if (typeof onChangeCallback === 'string' && typeof global[onChangeCallback] === 'function') {
                global[onChangeCallback]();
            } else if (typeof onChangeCallback === 'function') {
                onChangeCallback();
            }
        }

        function getSelectedValues() {
            return Array.from(chipsContainer.querySelectorAll(`input[name="${cssEscape(fieldName)}"]`)).map(el => String(el.value));
        }

        function syncState() {
            const selected = new Set(getSelectedValues());
            if (clearBtn) {
                clearBtn.classList.toggle('hidden', selected.size === 0);
            }
            dropdown.querySelectorAll('.choice-ms-option').forEach(opt => {
                const val = String(opt.getAttribute('data-value') || '');
                const check = opt.querySelector('.option-check');
                const isSel = selected.has(val);
                opt.classList.toggle('bg-teal-50/70', isSel);
                opt.classList.toggle('font-bold', isSel);
                if (check) check.classList.toggle('hidden', !isSel);
            });
        }

        function addChip(val, label, silent) {
            val = String(val).trim();
            if (!val) return;
            if (chipsContainer.querySelector(`[data-choice-val="${cssEscape(val)}"]`)) return;

            const displayLabel = label || val;
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-teal-50 text-teal-800 border border-teal-200 text-xs font-semibold shadow-2xs max-w-full';
            chip.setAttribute('data-choice-val', val);
            chip.innerHTML = `
                <input type="hidden" name="${escapeHtml(fieldName)}" value="${escapeHtml(val)}">
                <span class="truncate max-w-[160px]">${escapeHtml(displayLabel)}</span>
                <button type="button" data-remove-choice="${escapeHtml(val)}" class="text-teal-500 hover:text-rose-600 focus:outline-hidden inline-flex items-center shrink-0" title="إزالة">
                    <span class="material-symbols-outlined text-[13px] leading-none">close</span>
                </button>
            `;
            chipsContainer.appendChild(chip);
            syncState();
            if (!silent) notifyChange();
        }

        function removeChip(val, silent) {
            val = String(val).trim();
            const chip = chipsContainer.querySelector(`[data-choice-val="${cssEscape(val)}"]`);
            if (chip) {
                chip.remove();
                syncState();
                if (!silent) notifyChange();
            }
        }

        function clearAll(silent) {
            chipsContainer.innerHTML = '';
            input.value = '';
            filterOptions('');
            syncState();
            if (!silent) notifyChange();
        }

        function filterOptions(query) {
            let visibleCount = 0;
            dropdown.querySelectorAll('.choice-ms-option').forEach(opt => {
                const label = opt.getAttribute('data-label') || opt.getAttribute('data-value') || '';
                const val = opt.getAttribute('data-value') || '';
                const match = matchesQuery(`${label} ${val}`, query);
                opt.classList.toggle('hidden', !match);
                if (match) visibleCount += 1;
            });
            if (emptyState) {
                emptyState.classList.toggle('hidden', visibleCount > 0);
            }
        }

        input.addEventListener('focus', function () {
            filterOptions(input.value);
            syncState();
            dropdown.classList.remove('hidden');
        });

        input.addEventListener('click', function () {
            filterOptions(input.value);
            syncState();
            dropdown.classList.remove('hidden');
        });

        input.addEventListener('input', function () {
            filterOptions(input.value);
            dropdown.classList.remove('hidden');
        });

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                dropdown.classList.add('hidden');
                return;
            }
            if (dropdown.classList.contains('hidden')) return;
            const items = Array.from(dropdown.querySelectorAll('.choice-ms-option:not(.hidden)'));
            if (!items.length) return;
            let idx = items.findIndex(it => it.classList.contains('bg-teal-100/80'));
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                idx = (idx + 1) % items.length;
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                idx = (idx - 1 + items.length) % items.length;
            } else if (e.key === 'Enter' && idx >= 0) {
                e.preventDefault();
                items[idx].click();
                return;
            } else {
                return;
            }
            items.forEach((it, i) => {
                it.classList.toggle('bg-teal-100/80', i === idx);
                if (i === idx) it.scrollIntoView({ block: 'nearest' });
            });
        });

        dropdown.addEventListener('click', function (e) {
            const opt = e.target.closest('.choice-ms-option');
            if (!opt) return;
            e.preventDefault();
            e.stopPropagation();
            const val = String(opt.getAttribute('data-value') || '');
            const label = opt.getAttribute('data-label') || val;
            if (getSelectedValues().includes(val)) {
                removeChip(val);
            } else {
                addChip(val, label);
            }
            input.value = '';
            filterOptions('');
        });

        chipsContainer.addEventListener('click', function (e) {
            const btn = e.target.closest('button[data-remove-choice]');
            if (!btn) return;
            e.preventDefault();
            e.stopPropagation();
            removeChip(btn.getAttribute('data-remove-choice'));
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                clearAll();
            });
        }

        document.addEventListener('click', function (e) {
            if (container && !container.contains(e.target) && !chipsContainer.contains(e.target)) {
                dropdown.classList.add('hidden');
            }
        });

        syncState();

        global.ERPChoiceMultiselectInstances[prefix] = {
            addChip,
            removeChip,
            clearAll,
            getSelectedValues,
        };
    }

    global.initChoiceMultiselect = initChoiceMultiselect;
})(window);
