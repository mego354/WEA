/**
 * Shared Reusable Area & Brick Multiselect Component (Requirements C & D)
 * - Immediately displays authorized options on focus/click (no typing required).
 * - Search input filters/narrows suggestions cleanly without blocking browsing.
 * - Preserves multi-selection via chips + checkbox toggle inside dropdown.
 * - Enforces Area -> Brick dependency and clears orphaned bricks on area removal.
 */
(function (global) {
    'use strict';

    function escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function initAreaBrickMultiselect(config) {
        const prefix = config.componentId;
        const areaFieldName = config.areaFieldName || 'main_area';
        const brickFieldName = config.brickFieldName || 'area';
        const areasApiUrl = config.areasApiUrl;
        const bricksApiUrl = config.bricksApiUrl;
        const onChangeCallback = config.onChangeCallback;

        const areaInput = document.getElementById(`${prefix}_search_main_area_input`);
        const areaDropdown = document.getElementById(`${prefix}_search_main_area_dropdown`);
        const areaChips = document.getElementById(`${prefix}_selected_main_areas_chips`);
        const areaContainer = document.getElementById(`${prefix}_main_area_search_container`);
        const areaSpinner = document.getElementById(`${prefix}_main_area_spinner`);
        const areaIcon = document.getElementById(`${prefix}_main_area_icon`);

        const brickInput = document.getElementById(`${prefix}_search_brick_input`);
        const brickDropdown = document.getElementById(`${prefix}_search_brick_dropdown`);
        const brickChips = document.getElementById(`${prefix}_selected_bricks_chips`);
        const brickContainer = document.getElementById(`${prefix}_brick_search_container`);
        const brickSpinner = document.getElementById(`${prefix}_brick_spinner`);
        const brickIcon = document.getElementById(`${prefix}_brick_icon`);

        let areaTimer = null;
        let brickTimer = null;

        function notifyChange() {
            if (typeof onChangeCallback === 'string' && typeof global[onChangeCallback] === 'function') {
                global[onChangeCallback]();
            } else if (typeof onChangeCallback === 'function') {
                onChangeCallback();
            }
        }

        function getSelectedAreaIds() {
            if (!areaChips) return [];
            return Array.from(areaChips.querySelectorAll(`input[name="${areaFieldName}"]`)).map(el => String(el.value));
        }

        function getSelectedBrickIds() {
            if (!brickChips) return [];
            return Array.from(brickChips.querySelectorAll(`input[name="${brickFieldName}"]`)).map(el => String(el.value));
        }

        function setSpinner(spinner, icon, loading) {
            if (spinner) spinner.classList.toggle('hidden', !loading);
            if (icon) icon.classList.toggle('hidden', loading);
        }

        function addAreaChip(id, name, silent) {
            id = String(id);
            if (!areaChips || areaChips.querySelector(`[data-area-id="${id}"]`)) return;
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-teal-50 text-teal-800 border border-teal-200 text-xs font-semibold shadow-2xs';
            chip.setAttribute('data-area-id', id);
            chip.innerHTML = `
                <input type="hidden" name="${escapeHtml(areaFieldName)}" value="${escapeHtml(id)}">
                <span>${escapeHtml(name)}</span>
                <button type="button" data-remove-area="${escapeHtml(id)}" class="text-teal-500 hover:text-rose-600 focus:outline-hidden inline-flex items-center" title="إزالة">
                    <span class="material-symbols-outlined text-[13px] leading-none">close</span>
                </button>
            `;
            areaChips.appendChild(chip);
            if (!silent) {
                if (brickDropdown && !brickDropdown.classList.contains('hidden')) {
                    fetchAndRenderBricks();
                }
                notifyChange();
            }
        }

        function removeAreaChip(id, silent) {
            id = String(id);
            const chip = areaChips && areaChips.querySelector(`[data-area-id="${id}"]`);
            if (chip) chip.remove();
            if (brickChips) {
                brickChips.querySelectorAll(`[data-parent-id="${id}"]`).forEach(b => b.remove());
            }
            if (!silent) {
                if (areaDropdown && !areaDropdown.classList.contains('hidden')) {
                    fetchAndRenderAreas();
                }
                if (brickDropdown && !brickDropdown.classList.contains('hidden')) {
                    fetchAndRenderBricks();
                }
                notifyChange();
            }
        }

        function addBrickChip(id, name, parentId, parentName, silent) {
            id = String(id);
            if (!brickChips || brickChips.querySelector(`[data-brick-id="${id}"]`)) return;
            const chip = document.createElement('span');
            chip.className = 'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-teal-50 text-teal-800 border border-teal-200 text-xs font-semibold shadow-2xs';
            chip.setAttribute('data-brick-id', id);
            chip.setAttribute('data-parent-id', parentId ? String(parentId) : '');
            chip.innerHTML = `
                <input type="hidden" name="${escapeHtml(brickFieldName)}" value="${escapeHtml(id)}">
                <span>${escapeHtml(name)}${parentName ? ` <span class="text-[10px] text-teal-600 font-normal">(${escapeHtml(parentName)})</span>` : ''}</span>
                <button type="button" data-remove-brick="${escapeHtml(id)}" class="text-teal-500 hover:text-rose-600 focus:outline-hidden inline-flex items-center" title="إزالة">
                    <span class="material-symbols-outlined text-[13px] leading-none">close</span>
                </button>
            `;
            brickChips.appendChild(chip);
            if (!silent) notifyChange();
        }

        function removeBrickChip(id, silent) {
            id = String(id);
            const chip = brickChips && brickChips.querySelector(`[data-brick-id="${id}"]`);
            if (chip) chip.remove();
            if (!silent) {
                if (brickDropdown && !brickDropdown.classList.contains('hidden')) {
                    fetchAndRenderBricks();
                }
                notifyChange();
            }
        }

        async function fetchAndRenderAreas() {
            if (!areaInput || !areaDropdown || !areasApiUrl) return;
            const query = areaInput.value.trim();
            setSpinner(areaSpinner, areaIcon, true);
            try {
                const params = new URLSearchParams();
                if (query) params.set('q', query);
                const resp = await fetch(`${areasApiUrl}?${params.toString()}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-Skip-Global-Loader': '1' }
                });
                const data = await resp.json();
                const results = data.results || [];
                const selectedIds = new Set(getSelectedAreaIds());

                areaDropdown.innerHTML = '';
                if (results.length === 0) {
                    areaDropdown.innerHTML = `<div class="p-2.5 text-center text-slate-400 text-xs">${query ? `لا توجد مناطق مطابقة لـ "${escapeHtml(query)}"` : 'لا توجد مناطق متاحة ضمن نطاقك.'}</div>`;
                } else {
                    results.forEach(r => {
                        const isSelected = selectedIds.has(String(r.id));
                        const row = document.createElement('button');
                        row.type = 'button';
                        row.className = `ab-suggestion-item w-full text-right px-2.5 py-2 hover:bg-teal-50/70 cursor-pointer flex items-center justify-between text-slate-700 transition-colors min-h-[36px] ${isSelected ? 'bg-teal-50/60 font-bold text-teal-900' : ''}`;
                        row.innerHTML = `
                            <span class="flex items-center gap-2 min-w-0">
                                <input type="checkbox" tabindex="-1" ${isSelected ? 'checked' : ''} class="pointer-events-none w-3.5 h-3.5 rounded border-slate-300 text-[#27bebe]">
                                <span class="truncate text-xs">${escapeHtml(r.name)}</span>
                            </span>
                            ${r.code ? `<span class="text-[10px] text-slate-400 font-mono shrink-0 ms-2">${escapeHtml(r.code)}</span>` : ''}
                        `;
                        row.addEventListener('click', (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (selectedIds.has(String(r.id))) {
                                removeAreaChip(r.id);
                            } else {
                                addAreaChip(r.id, r.name);
                            }
                            fetchAndRenderAreas();
                        });
                        areaDropdown.appendChild(row);
                    });
                }
                areaDropdown.classList.remove('hidden');
            } catch (err) {
                console.error('Error loading areas:', err);
                areaDropdown.innerHTML = '<div class="p-2.5 text-center text-rose-500 text-xs">تعذر تحميل المناطق.</div>';
                areaDropdown.classList.remove('hidden');
            } finally {
                setSpinner(areaSpinner, areaIcon, false);
            }
        }

        async function fetchAndRenderBricks() {
            if (!brickInput || !brickDropdown || !bricksApiUrl) return;
            const query = brickInput.value.trim();
            const selectedAreaIds = getSelectedAreaIds();
            setSpinner(brickSpinner, brickIcon, true);
            try {
                const params = new URLSearchParams();
                if (query) params.set('q', query);
                selectedAreaIds.forEach(aid => params.append('main_area', aid));
                const resp = await fetch(`${bricksApiUrl}?${params.toString()}`, {
                    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-Skip-Global-Loader': '1' }
                });
                const data = await resp.json();
                const results = data.results || [];
                const selectedIds = new Set(getSelectedBrickIds());

                brickDropdown.innerHTML = '';
                if (results.length === 0) {
                    brickDropdown.innerHTML = `<div class="p-2.5 text-center text-slate-400 text-xs">${query ? `لا توجد خطوط مطابقة لـ "${escapeHtml(query)}"` : 'لا توجد خطوط جغرافية متاحة.'}</div>`;
                } else {
                    results.forEach(r => {
                        const isSelected = selectedIds.has(String(r.id));
                        const row = document.createElement('button');
                        row.type = 'button';
                        row.className = `ab-suggestion-item w-full text-right px-2.5 py-2 hover:bg-teal-50/70 cursor-pointer flex items-center justify-between text-slate-700 transition-colors min-h-[36px] ${isSelected ? 'bg-teal-50/60 font-bold text-teal-900' : ''}`;
                        row.innerHTML = `
                            <span class="flex items-center gap-2 min-w-0">
                                <input type="checkbox" tabindex="-1" ${isSelected ? 'checked' : ''} class="pointer-events-none w-3.5 h-3.5 rounded border-slate-300 text-[#27bebe] shrink-0">
                                <span class="min-w-0 truncate text-xs">
                                    ${escapeHtml(r.name)}
                                    ${r.parent_name ? `<span class="text-[10px] text-slate-400 font-normal"> (${escapeHtml(r.parent_name)})</span>` : ''}
                                </span>
                            </span>
                            ${r.code ? `<span class="text-[10px] text-slate-400 font-mono shrink-0 ms-2">${escapeHtml(r.code)}</span>` : ''}
                        `;
                        row.addEventListener('click', (e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            if (selectedIds.has(String(r.id))) {
                                removeBrickChip(r.id);
                            } else {
                                addBrickChip(r.id, r.name, r.parent_id, r.parent_name);
                            }
                            fetchAndRenderBricks();
                        });
                        brickDropdown.appendChild(row);
                    });
                }
                brickDropdown.classList.remove('hidden');
            } catch (err) {
                console.error('Error loading bricks:', err);
                brickDropdown.innerHTML = '<div class="p-2.5 text-center text-rose-500 text-xs">تعذر تحميل الخطوط الجغرافية.</div>';
                brickDropdown.classList.remove('hidden');
            } finally {
                setSpinner(brickSpinner, brickIcon, false);
            }
        }

        function attachKeyNav(inputEl, dropdownEl) {
            if (!inputEl || !dropdownEl) return;
            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    dropdownEl.classList.add('hidden');
                    return;
                }
                if (dropdownEl.classList.contains('hidden')) return;
                const items = dropdownEl.querySelectorAll('.ab-suggestion-item');
                if (!items.length) return;
                let idx = Array.from(items).findIndex(it => it.classList.contains('bg-teal-100/80'));
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
        }

        if (areaInput) {
            areaInput.addEventListener('focus', () => {
                if (brickDropdown) brickDropdown.classList.add('hidden');
                fetchAndRenderAreas();
            });
            areaInput.addEventListener('click', () => {
                if (brickDropdown) brickDropdown.classList.add('hidden');
                fetchAndRenderAreas();
            });
            areaInput.addEventListener('input', () => {
                clearTimeout(areaTimer);
                areaTimer = setTimeout(fetchAndRenderAreas, 180);
            });
            attachKeyNav(areaInput, areaDropdown);
        }

        if (brickInput) {
            brickInput.addEventListener('focus', () => {
                if (areaDropdown) areaDropdown.classList.add('hidden');
                fetchAndRenderBricks();
            });
            brickInput.addEventListener('click', () => {
                if (areaDropdown) areaDropdown.classList.add('hidden');
                fetchAndRenderBricks();
            });
            brickInput.addEventListener('input', () => {
                clearTimeout(brickTimer);
                brickTimer = setTimeout(fetchAndRenderBricks, 180);
            });
            attachKeyNav(brickInput, brickDropdown);
        }

        if (areaChips) {
            areaChips.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-remove-area]');
                if (btn) removeAreaChip(btn.getAttribute('data-remove-area'));
            });
        }
        if (brickChips) {
            brickChips.addEventListener('click', (e) => {
                const btn = e.target.closest('[data-remove-brick]');
                if (btn) removeBrickChip(btn.getAttribute('data-remove-brick'));
            });
        }

        document.addEventListener('click', (e) => {
            if (areaContainer && !areaContainer.contains(e.target) && areaDropdown) {
                areaDropdown.classList.add('hidden');
            }
            if (brickContainer && !brickContainer.contains(e.target) && brickDropdown) {
                brickDropdown.classList.add('hidden');
            }
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (areaDropdown) areaDropdown.classList.add('hidden');
                if (brickDropdown) brickDropdown.classList.add('hidden');
            }
        });

        return {
            clearAll() {
                if (areaChips) areaChips.innerHTML = '';
                if (brickChips) brickChips.innerHTML = '';
                if (areaInput) areaInput.value = '';
                if (brickInput) brickInput.value = '';
                if (areaDropdown) areaDropdown.classList.add('hidden');
                if (brickDropdown) brickDropdown.classList.add('hidden');
            },
            getSelectedAreaIds,
            getSelectedBrickIds,
        };
    }

    global.ERPMultiselectInstances = global.ERPMultiselectInstances || {};
    global.initAreaBrickMultiselect = function (config) {
        const inst = initAreaBrickMultiselect(config);
        global.ERPMultiselectInstances[config.componentId] = inst;
        return inst;
    };
})(window);

