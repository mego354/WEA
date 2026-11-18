/**
 * WEA Pharma ERP - Unified List Smart Search Suggestions
 * Enhances any <input data-smart-search-module="..."> with debounced,
 * strictly-scoped backend suggestions, keyboard navigation, and instant submit.
 */
(function () {
    'use strict';

    const DEBOUNCE_MS = 220;

    function escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text == null ? '' : String(text);
        return d.innerHTML;
    }

    function enhanceInput(input) {
        if (!input || input._erpListSmartSearch) return;
        input._erpListSmartSearch = true;

        const moduleName = input.getAttribute('data-smart-search-module');
        if (!moduleName) return;

        const form = input.closest('form');
        const wrapper = input.parentElement;
        if (wrapper && getComputedStyle(wrapper).position === 'static') {
            wrapper.style.position = 'relative';
        }

        const dropdown = document.createElement('div');
        dropdown.className = 'hidden absolute right-0 left-0 top-full mt-1 z-[70] bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden max-h-64 overflow-y-auto text-right';
        dropdown.setAttribute('dir', 'rtl');
        wrapper.appendChild(dropdown);

        let timer = null;
        let controller = null;
        let activeIdx = -1;
        let items = [];

        function hide() {
            dropdown.classList.add('hidden');
            activeIdx = -1;
        }

        function selectSuggestion(item) {
            if (!item) return;
            input.value = item.value || '';
            hide();
            if (form) {
                form.submit();
            }
        }

        function render(results) {
            items = results || [];
            activeIdx = -1;
            if (!items.length) {
                hide();
                return;
            }
            dropdown.innerHTML = '';
            items.forEach((item, idx) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'w-full text-right px-3 py-2 hover:bg-teal-50/70 border-b border-slate-50 last:border-0 flex flex-col gap-0.5 transition-colors';
                btn.innerHTML = `
                    <span class="text-xs font-bold text-slate-800 truncate">${escapeHtml(item.label)}</span>
                    ${item.subtext ? `<span class="text-[10px] text-slate-400 truncate font-mono">${escapeHtml(item.subtext)}</span>` : ''}
                `;
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    selectSuggestion(item);
                });
                dropdown.appendChild(btn);
            });
            dropdown.classList.remove('hidden');
        }

        async function fetchSuggestions(q) {
            if (!q) {
                hide();
                return;
            }
            if (controller) controller.abort();
            controller = new AbortController();
            try {
                const url = `/api/list-suggestions/?module=${encodeURIComponent(moduleName)}&q=${encodeURIComponent(q)}&limit=10`;
                const resp = await fetch(url, {
                    signal: controller.signal,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-Skip-Global-Loader': '1',
                        'Accept': 'application/json',
                    },
                });
                if (!resp.ok) {
                    hide();
                    return;
                }
                const data = await resp.json();
                render(data.results || []);
            } catch (err) {
                if (err && err.name !== 'AbortError') hide();
            }
        }

        input.addEventListener('input', () => {
            const q = input.value.trim();
            if (timer) clearTimeout(timer);
            if (!q) {
                hide();
                return;
            }
            timer = setTimeout(() => fetchSuggestions(q), DEBOUNCE_MS);
        });

        input.addEventListener('keydown', (e) => {
            if (dropdown.classList.contains('hidden')) return;
            const btns = dropdown.querySelectorAll('button');
            if (!btns.length) return;
            if (e.key === 'Escape') {
                hide();
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                activeIdx = (activeIdx + 1) % btns.length;
                btns.forEach((b, i) => b.classList.toggle('bg-teal-50', i === activeIdx));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                activeIdx = (activeIdx - 1 + btns.length) % btns.length;
                btns.forEach((b, i) => b.classList.toggle('bg-teal-50', i === activeIdx));
            } else if (e.key === 'Enter' && activeIdx >= 0 && items[activeIdx]) {
                e.preventDefault();
                selectSuggestion(items[activeIdx]);
            }
        });

        document.addEventListener('click', (e) => {
            if (!wrapper.contains(e.target)) hide();
        });
    }

    function initAll(root) {
        (root || document).querySelectorAll('input[data-smart-search-module]').forEach(enhanceInput);
    }

    window.ERPListSmartSearch = { initAll };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initAll(document));
    } else {
        initAll(document);
    }
})();
