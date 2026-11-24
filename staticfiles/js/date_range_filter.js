/**
 * WEA Pharma ERP — Unified Compact Date Range Filter Controller (Option A)
 * - Collapsible predefined date presets section (clean & mobile-friendly)
 * - Displays vertical "من تاريخ" / "إلى تاريخ" inputs ONLY when "فترة مخصصة" is active
 * - Never auto-submits unexpectedly inside filter drawers (opt-in via data-auto-submit="true")
 * - Preserves selected values across drawer close/reopen and syncs preset <-> custom dates bidirectionally
 */
(function (global) {
    'use strict';

    const PRESET_LABELS = {
        all_time: 'كل الوقت',
        today: 'اليوم',
        yesterday: 'أمس',
        last_7_days: 'آخر 7 أيام',
        last_30_days: 'آخر 30 يوم',
        this_month: 'هذا الشهر',
        last_month: 'الشهر الماضي',
        quarter: 'هذا الربع',
        this_year: 'هذه السنة',
        year: 'هذه السنة',
        custom: 'فترة مخصصة',
    };

    function pad(n) {
        return String(n).padStart(2, '0');
    }

    function fmt(d) {
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    }

    function computePresetDates(val) {
        const now = new Date();
        let s = '';
        let e = '';
        if (val === 'today') {
            s = e = fmt(now);
        } else if (val === 'yesterday') {
            const y = new Date(now);
            y.setDate(y.getDate() - 1);
            s = e = fmt(y);
        } else if (val === 'last_7_days') {
            const d = new Date(now);
            d.setDate(d.getDate() - 6);
            s = fmt(d);
            e = fmt(now);
        } else if (val === 'last_30_days') {
            const d = new Date(now);
            d.setDate(d.getDate() - 29);
            s = fmt(d);
            e = fmt(now);
        } else if (val === 'this_month') {
            s = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
            e = fmt(now);
        } else if (val === 'last_month') {
            const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
            const last = new Date(now.getFullYear(), now.getMonth(), 0);
            s = fmt(first);
            e = fmt(last);
        } else if (val === 'quarter') {
            const qStartMonth = Math.floor(now.getMonth() / 3) * 3;
            s = fmt(new Date(now.getFullYear(), qStartMonth, 1));
            e = fmt(now);
        } else if (val === 'this_year' || val === 'year') {
            s = `${now.getFullYear()}-01-01`;
            e = fmt(now);
        }
        return { s, e };
    }

    function updateSummary(root) {
        const selectEl = root.querySelector('[data-drf-preset]');
        const fromInput = root.querySelector('[data-drf-from]');
        const toInput = root.querySelector('[data-drf-to]');
        const summaryEl = root.querySelector('[data-drf-summary]');
        const clearBtn = root.querySelector('[data-drf-clear]');
        const customBox = root.querySelector('[data-drf-custom-box]');
        if (!selectEl) return;

        const val = selectEl.value || 'all_time';
        const fromVal = fromInput ? fromInput.value : '';
        const toVal = toInput ? toInput.value : '';
        const isCustom = val === 'custom';

        if (customBox) {
            customBox.classList.toggle('hidden', !isCustom);
        }

        // Highlight active quick-preset pill buttons if present
        root.querySelectorAll('[data-drf-pill]').forEach((btn) => {
            const match = btn.getAttribute('data-drf-pill') === val;
            btn.classList.toggle('bg-brand-500', match);
            btn.classList.toggle('text-white', match);
            btn.classList.toggle('border-brand-500', match);
            btn.classList.toggle('bg-white', !match);
            btn.classList.toggle('text-slate-700', !match);
            btn.classList.toggle('border-slate-200', !match);
        });

        if (summaryEl) {
            if (isCustom && (fromVal || toVal)) {
                summaryEl.textContent = `${fromVal || '...'} ⟵ ${toVal || '...'}`;
            } else if (val !== 'all_time' && (fromVal || toVal)) {
                const lbl = PRESET_LABELS[val] || selectEl.options[selectEl.selectedIndex]?.textContent || val;
                summaryEl.textContent = `${lbl} (${fromVal || '...'} ⟵ ${toVal || '...'})`;
            } else {
                const lbl = PRESET_LABELS[val] || selectEl.options[selectEl.selectedIndex]?.textContent || 'كل الوقت';
                summaryEl.textContent = lbl;
            }
        }

        if (clearBtn) {
            const defaultPreset = root.getAttribute('data-drf-default') || 'all_time';
            const hasSelection = (val && val !== defaultPreset) || Boolean(fromVal) || Boolean(toVal);
            clearBtn.classList.toggle('hidden', !hasSelection);
        }
    }

    function initRoot(root) {
        if (!root || root._erpDateRangeInit) return;
        root._erpDateRangeInit = true;

        const selectEl = root.querySelector('[data-drf-preset]');
        const fromInput = root.querySelector('[data-drf-from]');
        const toInput = root.querySelector('[data-drf-to]');
        const toggleBtn = root.querySelector('[data-drf-toggle]');
        const panel = root.querySelector('[data-drf-panel]');
        const chevron = root.querySelector('[data-drf-chevron]');
        const clearBtn = root.querySelector('[data-drf-clear]');
        const autoSubmit = root.getAttribute('data-auto-submit') === 'true';

        if (!selectEl) return;

        function setExpanded(open) {
            if (!panel) return;
            panel.classList.toggle('hidden', !open);
            if (toggleBtn) toggleBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            if (chevron) chevron.classList.toggle('rotate-180', open);
        }

        if (toggleBtn && panel) {
            toggleBtn.addEventListener('click', () => {
                setExpanded(panel.classList.contains('hidden'));
            });
        }

        function applyPreset(val, allowSubmit) {
            selectEl.value = val;
            if (val === 'custom') {
                updateSummary(root);
                if (panel && panel.classList.contains('hidden')) setExpanded(true);
                if (fromInput) fromInput.focus();
                return;
            }
            if (val === 'all_time' || val === '') {
                if (fromInput) fromInput.value = '';
                if (toInput) toInput.value = '';
            } else {
                const { s, e } = computePresetDates(val);
                if (fromInput) fromInput.value = s;
                if (toInput) toInput.value = e;
            }
            updateSummary(root);
            if (allowSubmit && autoSubmit) {
                const form = root.closest('form');
                if (form) form.submit();
            }
        }

        selectEl.addEventListener('change', () => {
            applyPreset(selectEl.value, true);
        });

        root.querySelectorAll('[data-drf-pill]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const val = btn.getAttribute('data-drf-pill');
                applyPreset(val, true);
            });
        });

        function onManualDateInput() {
            if (selectEl.value !== 'custom') {
                selectEl.value = 'custom';
            }
            updateSummary(root);
        }

        if (fromInput) fromInput.addEventListener('change', onManualDateInput);
        if (toInput) toInput.addEventListener('change', onManualDateInput);

        if (clearBtn) {
            clearBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const defaultPreset = root.getAttribute('data-drf-default') || 'all_time';
                if (defaultPreset === 'all_time') {
                    applyPreset('all_time', false);
                } else {
                    applyPreset(defaultPreset, false);
                }
                if (autoSubmit) {
                    const form = root.closest('form');
                    if (form) form.submit();
                }
            });
        }

        // Initial state: if custom range is active, make sure panel & custom box are visible
        if (selectEl.value === 'custom') {
            setExpanded(true);
        }
        updateSummary(root);
    }

    function initAll(container) {
        (container || document).querySelectorAll('[data-erp-date-range]').forEach(initRoot);
    }

    // Backward-compatible global helper if any legacy onchange calls applyDatePreset
    global.applyDatePreset = function (selectEl) {
        const root = selectEl && selectEl.closest('[data-erp-date-range]');
        if (root) {
            initRoot(root);
            selectEl.dispatchEvent(new Event('change'));
        }
    };

    global.ERPDateRangeFilter = { initAll, initRoot };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initAll(document));
    } else {
        initAll(document);
    }
})(window);
