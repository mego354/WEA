/**
 * Table Column Manager & Preferences Persistence
 * Supports dynamic show/hide of table columns, persistent storage in localStorage,
 * safe fallback to defaults, required column locking, and mobile responsive table handling.
 */
window.TableColumnManager = (function () {
    const registry = {};

    function getStorageKey(tableId, customKey) {
        return customKey || ('erp_table_cols_' + tableId + '_v1');
    }

    function safeLoadPreferences(storageKey) {
        try {
            const raw = localStorage.getItem(storageKey);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed) && parsed.every(item => typeof item === 'string')) {
                return parsed;
            }
        } catch (e) {
            console.warn('[TableColumnManager] Failed to read localStorage key:', storageKey, e);
        }
        return null;
    }

    function safeSavePreferences(storageKey, visibleCols) {
        try {
            localStorage.setItem(storageKey, JSON.stringify(visibleCols));
        } catch (e) {
            console.warn('[TableColumnManager] Failed to write to localStorage:', storageKey, e);
        }
    }

    function init(tableId, options = {}) {
        const table = document.getElementById(tableId);
        if (!table) return null;

        const storageKey = getStorageKey(tableId, options.storageKey);
        const thead = table.querySelector('thead');
        if (!thead) return null;

        const thList = thead.querySelectorAll('tr:last-child th');
        if (!thList.length) return null;

        const columns = [];
        thList.forEach((th, index) => {
            const colId = th.getAttribute('data-col') || ('col_' + index);
            th.setAttribute('data-col', colId);
            th.setAttribute('data-col-index', index);

            const isRequired = th.getAttribute('data-required') === 'true' ||
                               colId === 'actions' ||
                               colId === 'checkbox' ||
                               th.classList.contains('col-required');

            const isDefaultHidden = th.getAttribute('data-default-hidden') === 'true';

            // Extract readable label
            let label = th.getAttribute('data-col-label');
            if (!label) {
                // Clone node and remove icons/inputs to get text
                const clone = th.cloneNode(true);
                clone.querySelectorAll('.material-symbols-outlined, input, button').forEach(el => el.remove());
                label = clone.innerText.trim() || ('عمود ' + (index + 1));
            }

            columns.push({
                id: colId,
                index: index,
                label: label,
                isRequired: isRequired,
                isDefaultHidden: isDefaultHidden
            });
        });

        // Load saved preferences or compute defaults
        const saved = safeLoadPreferences(storageKey);
        let visibleCols;

        if (saved && Array.isArray(saved)) {
            // Reconcile saved columns with existing columns
            visibleCols = new Set(saved);
            // Ensure all required columns are visible
            columns.forEach(c => {
                if (c.isRequired) visibleCols.add(c.id);
            });
        } else {
            // Default visibility
            visibleCols = new Set();
            columns.forEach(c => {
                if (!c.isDefaultHidden || c.isRequired) {
                    visibleCols.add(c.id);
                }
            });
        }

        registry[tableId] = {
            tableId: tableId,
            storageKey: storageKey,
            columns: columns,
            visibleCols: visibleCols
        };

        renderPickerUI(tableId);
        apply(tableId);
        return registry[tableId];
    }

    function renderPickerUI(tableId) {
        const meta = registry[tableId];
        if (!meta) return;

        const container = document.getElementById('col-picker-list-' + tableId);
        if (!container) return;

        container.innerHTML = '';
        meta.columns.forEach(col => {
            // Don't show technical checkbox columns in picker
            if (col.id === 'checkbox') return;

            const isChecked = meta.visibleCols.has(col.id);
            const labelEl = document.createElement('label');
            labelEl.className = 'flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs hover:bg-slate-50 cursor-pointer select-none transition-colors';

            const rightSide = document.createElement('div');
            rightSide.className = 'flex items-center gap-2 min-w-0';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.checked = isChecked;
            checkbox.disabled = col.isRequired;
            checkbox.className = 'rounded text-brand-600 focus:ring-brand-500 cursor-pointer border-slate-300';
            checkbox.addEventListener('change', (e) => {
                toggleColumn(tableId, col.id, e.target.checked);
            });

            const textSpan = document.createElement('span');
            textSpan.className = 'truncate text-slate-700 ' + (col.isRequired ? 'font-semibold text-slate-900' : 'font-normal');
            textSpan.textContent = col.label;
            textSpan.title = col.label;

            rightSide.appendChild(checkbox);
            rightSide.appendChild(textSpan);
            labelEl.appendChild(rightSide);

            if (col.isRequired) {
                const lockSpan = document.createElement('span');
                lockSpan.className = 'text-[10px] text-slate-400 bg-slate-100 px-1.5 py-0.5 rounded font-mono';
                lockSpan.textContent = 'مطلوب';
                labelEl.appendChild(lockSpan);
            }

            container.appendChild(labelEl);
        });
    }

    function apply(tableId) {
        const meta = registry[tableId];
        if (!meta) return;

        const table = document.getElementById(tableId);
        if (!table) return;

        const colMap = {};
        meta.columns.forEach(c => {
            colMap[c.id] = meta.visibleCols.has(c.id);
        });

        // 1. Update thead headers
        const thList = table.querySelectorAll('thead tr:last-child th');
        thList.forEach((th, idx) => {
            const colId = th.getAttribute('data-col') || ('col_' + idx);
            const isVis = colMap[colId] !== false;
            if (isVis) {
                th.classList.remove('hidden');
                th.style.display = '';
            } else {
                th.classList.add('hidden');
                th.style.display = 'none';
            }
        });

        // 2. Update tbody rows
        const rows = table.querySelectorAll('tbody tr');
        rows.forEach(tr => {
            // If row is a full-width empty state or colspan row, skip column hiding
            if (tr.children.length === 1 && tr.children[0].hasAttribute('colspan')) {
                return;
            }

            Array.from(tr.children).forEach((td, idx) => {
                const colId = td.getAttribute('data-col') || (meta.columns[idx] ? meta.columns[idx].id : ('col_' + idx));
                const isVis = colMap[colId] !== false;
                if (isVis) {
                    td.classList.remove('hidden');
                    td.style.display = '';
                } else {
                    td.classList.add('hidden');
                    td.style.display = 'none';
                }
            });
        });

        // Trigger custom event for external listeners
        table.dispatchEvent(new CustomEvent('tableColumnsChanged', {
            detail: {
                tableId: tableId,
                visibleCols: Array.from(meta.visibleCols)
            }
        }));
    }

    function toggleColumn(tableId, colId, isVisible) {
        const meta = registry[tableId];
        if (!meta) return;

        const col = meta.columns.find(c => c.id === colId);
        if (!col || col.isRequired) return; // Cannot hide required columns

        if (isVisible) {
            meta.visibleCols.add(colId);
        } else {
            // Prevent hiding all columns
            const nonTechnicalCount = meta.columns.filter(c => meta.visibleCols.has(c.id) && c.id !== 'checkbox').length;
            if (nonTechnicalCount <= 1) {
                // Revert checkbox state
                renderPickerUI(tableId);
                return;
            }
            meta.visibleCols.delete(colId);
        }

        safeSavePreferences(meta.storageKey, Array.from(meta.visibleCols));
        apply(tableId);
    }

    function showAll(tableId) {
        const meta = registry[tableId];
        if (!meta) return;

        meta.columns.forEach(c => meta.visibleCols.add(c.id));
        safeSavePreferences(meta.storageKey, Array.from(meta.visibleCols));
        renderPickerUI(tableId);
        apply(tableId);
    }

    function resetDefaults(tableId) {
        const meta = registry[tableId];
        if (!meta) return;

        try {
            localStorage.removeItem(meta.storageKey);
        } catch (e) {
            console.warn(e);
        }

        meta.visibleCols = new Set();
        meta.columns.forEach(c => {
            if (!c.isDefaultHidden || c.isRequired) {
                meta.visibleCols.add(c.id);
            }
        });

        renderPickerUI(tableId);
        apply(tableId);
    }

    function toggleDropdown(tableId) {
        const dropdown = document.getElementById('col-picker-dropdown-' + tableId);
        if (!dropdown) return;

        const isHidden = dropdown.classList.contains('hidden');
        // Close all other open dropdowns first
        document.querySelectorAll('[id^="col-picker-dropdown-"]').forEach(d => d.classList.add('hidden'));

        if (isHidden) {
            dropdown.classList.remove('hidden');
        }
    }

    // Global outside click listener to close open column dropdowns
    document.addEventListener('click', function (e) {
        if (!e.target.closest('[data-table-column-picker]')) {
            document.querySelectorAll('[id^="col-picker-dropdown-"]').forEach(d => d.classList.add('hidden'));
        }
    });

    // Auto-init tables on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('table[data-col-table]').forEach(tbl => {
            const id = tbl.id || tbl.getAttribute('data-col-table');
            if (id) {
                init(id);
            }
        });
    });

    return {
        init: init,
        toggleDropdown: toggleDropdown,
        toggleColumn: toggleColumn,
        showAll: showAll,
        resetDefaults: resetDefaults,
        apply: apply,
        getRegistry: () => registry
    };
})();
