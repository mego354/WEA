/**
 * WEA Pharma ERP - Reusable Smart Select (RTL Searchable Combobox)
 * Progressively enhances <select data-smart-select="true"> elements with:
 * - Instant Arabic-normalized & whitespace-collapsed local filtering
 * - Optional async backend search (data-search-url) with debounce & AbortController
 * - Full preservation of native <select> name/value/required/change events
 * - Viewport collision flipping and mobile-safe RTL rendering inside forms/drawers/modals
 */
(function () {
    'use strict';

    const DEFAULT_DEBOUNCE_MS = 220;

    function normalizeText(value) {
        if (!value || typeof value !== 'string') return '';
        if (typeof window.normalizeArabicSearch === 'function') {
            return window.normalizeArabicSearch(value);
        }
        return value
            .toLowerCase()
            .replace(/[\u064B-\u065F\u0670\u0640]/g, '')
            .replace(/[\u0622\u0623\u0625\u0671]/g, '\u0627')
            .replace(/\u0629/g, '\u0647')
            .replace(/\u0649/g, '\u064A')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function matchesQuery(candidateText, query) {
        if (typeof window.matchesNormalizedArabic === 'function') {
            return window.matchesNormalizedArabic(candidateText, query);
        }
        const normQuery = normalizeText(query);
        if (!normQuery) return true;
        const normTarget = normalizeText(candidateText);
        const tokens = normQuery.split(' ').filter(Boolean);
        return tokens.every((tok) => normTarget.includes(tok));
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    }

    function isOptionVisible(opt) {
        if (!opt) return false;
        if (opt.hidden) return false;
        if (opt.style && opt.style.display === 'none') return false;
        return true;
    }

    function readLocalOptions(selectEl) {
        const list = [];
        for (let i = 0; i < selectEl.options.length; i++) {
            const opt = selectEl.options[i];
            if (!isOptionVisible(opt)) continue;
            // Skip placeholder empty value from options list (handled via Clear / placeholder)
            if (opt.value === '') continue;
            list.push({
                id: String(opt.value),
                text: opt.textContent.trim(),
                subtext: opt.getAttribute('data-subtext') || '',
                searchExtra: [
                    opt.textContent.trim(),
                    opt.getAttribute('data-search') || '',
                    opt.getAttribute('data-subtext') || '',
                ].join(' '),
                disabled: !!opt.disabled,
            });
        }
        return list;
    }

    function getPlaceholderText(selectEl) {
        const explicit = selectEl.getAttribute('data-placeholder');
        if (explicit) return explicit;
        for (let i = 0; i < selectEl.options.length; i++) {
            const opt = selectEl.options[i];
            if (opt.value === '') {
                return opt.textContent.trim() || 'اختر...';
            }
        }
        return 'اختر...';
    }

    class SmartSelectInstance {
        constructor(selectEl) {
            this.select = selectEl;
            this.searchUrl = selectEl.getAttribute('data-search-url') || '';
            this.placeholder = getPlaceholderText(selectEl);
            this.searchPlaceholder = selectEl.getAttribute('data-search-placeholder') || 'ابحث بالاسم أو الكود أو الرقم...';
            this.minChars = parseInt(selectEl.getAttribute('data-min-chars') || '0', 10) || 0;
            this.isOpen = false;
            this.activeIndex = -1;
            this.debounceTimer = null;
            this.abortController = null;
            this.remoteCache = new Map();
            this.renderedItems = [];
            this.isLoading = false;
            this.loadError = '';
            this.suppressNextSelectSync = false;
            this.lastTotalCount = null;

            this._buildDOM();
            this._bindEvents();
            this.syncFromSelect();
        }

        _buildDOM() {
            const select = this.select;

            // Preserve sizing clues from original select classes
            const origClass = select.className || '';
            const isCompact = /\b(text-xs|py-1\.5|py-1|h-9)\b/.test(origClass);

            this.wrapper = document.createElement('div');
            this.wrapper.className = 'erp-smart-select relative w-full';
            this.wrapper.setAttribute('dir', 'rtl');

            // Insert wrapper before select and move select inside wrapper
            select.parentNode.insertBefore(this.wrapper, select);
            this.wrapper.appendChild(select);

            // Keep native select in layout geometry so browser required-validation never throws "not focusable"
            select.setAttribute('tabindex', '-1');
            select.setAttribute('aria-hidden', 'true');
            select.classList.remove('hidden');
            select.style.position = 'absolute';
            select.style.inset = '0';
            select.style.width = '100%';
            select.style.height = '100%';
            select.style.opacity = '0';
            select.style.pointerEvents = 'none';
            select.style.zIndex = '0';

            // Visible trigger button
            this.trigger = document.createElement('button');
            this.trigger.type = 'button';
            this.trigger.className = [
                'erp-smart-select-trigger relative z-[1] w-full flex items-center justify-between gap-2 text-right',
                'rounded-lg border border-slate-300 bg-white transition-colors',
                'focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-500',
                isCompact ? 'px-2.5 py-1.5 text-xs min-h-[34px]' : 'px-3 py-2 text-sm min-h-[40px]',
                select.disabled ? 'bg-slate-100 text-slate-500 cursor-not-allowed' : 'hover:border-slate-400 cursor-pointer',
            ].join(' ');
            if (select.disabled) {
                this.trigger.disabled = true;
            }
            this.trigger.setAttribute('aria-haspopup', 'listbox');
            this.trigger.setAttribute('aria-expanded', 'false');

            this.triggerLabel = document.createElement('span');
            this.triggerLabel.className = 'truncate flex-1 text-right text-slate-400';
            this.triggerLabel.textContent = this.placeholder;

            this.triggerActions = document.createElement('span');
            this.triggerActions.className = 'flex items-center gap-1 shrink-0';

            this.clearBtn = document.createElement('span');
            this.clearBtn.className = 'erp-smart-select-clear hidden text-slate-400 hover:text-rose-500 p-0.5 rounded transition-colors';
            this.clearBtn.setAttribute('role', 'button');
            this.clearBtn.setAttribute('title', 'مسح الاختيار');
            this.clearBtn.innerHTML = '<span class="material-symbols-outlined text-[16px] leading-none">close</span>';

            this.chevron = document.createElement('span');
            this.chevron.className = 'material-symbols-outlined text-[18px] text-slate-400 transition-transform duration-150 leading-none';
            this.chevron.textContent = 'expand_more';

            this.triggerActions.appendChild(this.clearBtn);
            this.triggerActions.appendChild(this.chevron);
            this.trigger.appendChild(this.triggerLabel);
            this.trigger.appendChild(this.triggerActions);

            // Dropdown panel
            this.dropdown = document.createElement('div');
            this.dropdown.className = [
                'erp-smart-select-dropdown hidden absolute right-0 left-0 z-[70]',
                'bg-white border border-slate-200 rounded-xl shadow-xl overflow-hidden',
            ].join(' ');

            // Search box inside dropdown
            const searchWrap = document.createElement('div');
            searchWrap.className = 'p-2 border-b border-slate-100 bg-slate-50/80';

            const inputWrap = document.createElement('div');
            inputWrap.className = 'relative flex items-center';

            const searchIcon = document.createElement('span');
            searchIcon.className = 'material-symbols-outlined text-[17px] text-slate-400 absolute right-2.5 pointer-events-none';
            searchIcon.textContent = 'search';

            this.searchInput = document.createElement('input');
            this.searchInput.type = 'search';
            this.searchInput.autocomplete = 'off';
            this.searchInput.className = 'w-full pr-8 pl-7 py-1.5 text-sm bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-teal-500/30 focus:border-teal-500 text-slate-800 placeholder:text-slate-400';
            this.searchInput.placeholder = this.searchPlaceholder;
            this.searchInput.setAttribute('aria-label', this.searchPlaceholder);

            this.spinner = document.createElement('span');
            this.spinner.className = 'hidden absolute left-2 w-4 h-4 border-2 border-teal-500 border-t-transparent rounded-full animate-spin';

            inputWrap.appendChild(searchIcon);
            inputWrap.appendChild(this.searchInput);
            inputWrap.appendChild(this.spinner);
            searchWrap.appendChild(inputWrap);

            // Results listbox
            this.listbox = document.createElement('ul');
            this.listbox.className = 'max-h-60 overflow-y-auto divide-y divide-slate-50 p-1 text-right';
            this.listbox.setAttribute('role', 'listbox');

            this.statusFooter = document.createElement('div');
            this.statusFooter.className = 'hidden px-3 py-1.5 text-[11px] text-slate-500 bg-slate-50 border-t border-slate-100 flex items-center justify-between font-medium select-none';

            this.dropdown.appendChild(searchWrap);
            this.dropdown.appendChild(this.listbox);
            this.dropdown.appendChild(this.statusFooter);

            this.wrapper.appendChild(this.trigger);
            this.wrapper.appendChild(this.dropdown);
        }

        _bindEvents() {
            this.trigger.addEventListener('click', (e) => {
                if (this.select.disabled) return;
                if (this.clearBtn.contains(e.target)) return;
                e.preventDefault();
                if (this.isOpen) {
                    this.close();
                } else {
                    this.open();
                }
            });

            this.clearBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (this.select.disabled) return;
                this.clearSelection();
            });

            this.trigger.addEventListener('keydown', (e) => {
                if (this.select.disabled) return;
                if (['Enter', ' ', 'ArrowDown', 'ArrowUp'].includes(e.key)) {
                    e.preventDefault();
                    if (!this.isOpen) {
                        this.open();
                    }
                }
            });

            this.searchInput.addEventListener('input', () => {
                this._handleSearchInput();
            });

            this.searchInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    this.close(true);
                } else if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    this._moveActive(1);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    this._moveActive(-1);
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (this.activeIndex >= 0 && this.renderedItems[this.activeIndex]) {
                        this.selectItem(this.renderedItems[this.activeIndex]);
                    } else if (this.renderedItems.length === 1 && !this.renderedItems[0].disabled) {
                        this.selectItem(this.renderedItems[0]);
                    }
                } else if (e.key === 'Tab') {
                    this.close(false);
                }
            });

            // Sync if another script changes select.value
            this.select.addEventListener('change', () => {
                if (this.suppressNextSelectSync) {
                    this.suppressNextSelectSync = false;
                    return;
                }
                this.syncFromSelect();
            });

            // Show custom invalid styling + open dropdown on failed HTML5 validation
            this.select.addEventListener('invalid', (e) => {
                e.preventDefault();
                this.trigger.classList.add('border-rose-500', 'ring-2', 'ring-rose-200');
                if (!this.select.disabled) {
                    this.open();
                }
            });

            // Close when clicking outside
            this._onDocClick = (e) => {
                if (this.isOpen && !this.wrapper.contains(e.target)) {
                    this.close(false);
                }
            };
            document.addEventListener('click', this._onDocClick);

            // Watch dynamic <option> changes / visibility toggles (coalesced per animation frame)
            if (typeof MutationObserver !== 'undefined') {
                this._observerRaf = null;
                this._observer = new MutationObserver(() => {
                    if (this._observerRaf) return;
                    const flush = () => {
                        this._observerRaf = null;
                        this.syncFromSelect();
                        if (this.isOpen) {
                            this._renderCurrentResults(this.searchInput.value);
                        }
                    };
                    if (typeof requestAnimationFrame === 'function') {
                        this._observerRaf = requestAnimationFrame(flush);
                    } else {
                        flush();
                    }
                });
                this._observer.observe(this.select, {
                    childList: true,
                    subtree: true,
                    attributes: true,
                    attributeFilter: ['style', 'disabled', 'hidden'],
                });
            }
        }

        syncFromSelect() {
            const val = this.select.value;
            const hasEmptyOption = Array.from(this.select.options).some((o) => o.value === '');
            let selectedOpt = null;
            if (val !== '') {
                selectedOpt = Array.from(this.select.options).find((o) => o.value === val && isOptionVisible(o))
                    || Array.from(this.select.options).find((o) => o.value === val);
            }

            if (selectedOpt && selectedOpt.value !== '') {
                this.triggerLabel.textContent = selectedOpt.textContent.trim();
                this.triggerLabel.classList.remove('text-slate-400');
                this.triggerLabel.classList.add('text-slate-800', 'font-medium');
                this.trigger.classList.remove('border-rose-500', 'ring-2', 'ring-rose-200');
                if (!this.select.disabled && (!this.select.required || hasEmptyOption)) {
                    this.clearBtn.classList.remove('hidden');
                } else {
                    this.clearBtn.classList.add('hidden');
                }
            } else {
                this.triggerLabel.textContent = this.placeholder;
                this.triggerLabel.classList.add('text-slate-400');
                this.triggerLabel.classList.remove('text-slate-800', 'font-medium');
                this.clearBtn.classList.add('hidden');
            }

            if (this.select.disabled) {
                this.trigger.disabled = true;
                this.trigger.classList.add('bg-slate-100', 'text-slate-500', 'cursor-not-allowed');
            } else {
                this.trigger.disabled = false;
                this.trigger.classList.remove('bg-slate-100', 'text-slate-500', 'cursor-not-allowed');
            }
        }

        _positionDropdown() {
            const rect = this.trigger.getBoundingClientRect();
            const spaceBelow = window.innerHeight - rect.bottom;
            const spaceAbove = rect.top;

            this.dropdown.classList.remove('top-full', 'mt-1', 'bottom-full', 'mb-1');
            if (spaceBelow < 260 && spaceAbove > spaceBelow) {
                this.dropdown.classList.add('bottom-full', 'mb-1');
            } else {
                this.dropdown.classList.add('top-full', 'mt-1');
            }
        }

        open() {
            if (this.select.disabled) return;
            // Close any other open smart selects cleanly
            document.querySelectorAll('.erp-smart-select-dropdown:not(.hidden)').forEach((el) => {
                if (el !== this.dropdown && el._instance) {
                    el._instance.close(false);
                }
            });

            this.isOpen = true;
            this.loadError = '';
            this.searchInput.value = '';
            this.dropdown.classList.remove('hidden');
            this.dropdown._instance = this;
            this._positionDropdown();
            this.trigger.setAttribute('aria-expanded', 'true');
            this.chevron.classList.add('rotate-180');

            this._renderCurrentResults('');
            // Trigger initial remote refresh if remote URL is available and no query needed
            if (this.searchUrl && this.minChars === 0 && !this.remoteCache.has('')) {
                this._fetchRemote('');
            }
            setTimeout(() => this.searchInput.focus(), 10);
        }

        close(restoreFocus) {
            if (!this.isOpen) return;
            this.isOpen = false;
            this.dropdown.classList.add('hidden');
            this.trigger.setAttribute('aria-expanded', 'false');
            this.chevron.classList.remove('rotate-180');
            if (this.debounceTimer) {
                clearTimeout(this.debounceTimer);
                this.debounceTimer = null;
            }
            if (this.abortController) {
                this.abortController.abort();
                this.abortController = null;
            }
            this._setLoading(false);
            if (restoreFocus) {
                this.trigger.focus();
            }
        }

        clearSelection() {
            this.select.value = '';
            this.syncFromSelect();
            this.suppressNextSelectSync = true;
            this.select.dispatchEvent(new Event('change', { bubbles: true }));
            if (this.isOpen) {
                this._renderCurrentResults(this.searchInput.value);
            }
        }

        selectItem(item) {
            if (!item || item.disabled) return;
            const targetVal = String(item.id);

            let opt = Array.from(this.select.options).find((o) => o.value === targetVal);
            if (!opt) {
                opt = new Option(item.text, targetVal, true, true);
                if (item.subtext) {
                    opt.setAttribute('data-subtext', item.subtext);
                }
                this.select.add(opt);
            } else if (item.text && opt.textContent.trim() !== item.text) {
                opt.textContent = item.text;
            }

            const prevValue = this.select.value;
            this.select.value = targetVal;
            this.syncFromSelect();
            this.close(true);

            if (prevValue !== targetVal || this.select.getAttribute('onchange')) {
                this.suppressNextSelectSync = true;
                this.select.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }

        _setLoading(flag) {
            this.isLoading = flag;
            if (flag) {
                this.spinner.classList.remove('hidden');
            } else {
                this.spinner.classList.add('hidden');
            }
        }

        _handleSearchInput() {
            const query = this.searchInput.value.trim();
            this.loadError = '';

            // Always show instant Arabic-normalized local matches immediately
            this._renderCurrentResults(query);

            if (!this.searchUrl) return;

            if (this.debounceTimer) {
                clearTimeout(this.debounceTimer);
            }
            if (query.length < this.minChars && query.length > 0) {
                return;
            }

            this.debounceTimer = setTimeout(() => {
                this._fetchRemote(query);
            }, DEFAULT_DEBOUNCE_MS);
        }

        async _fetchRemote(query) {
            const normKey = normalizeText(query);
            if (this.remoteCache.has(normKey)) {
                const cached = this.remoteCache.get(normKey);
                const cachedItems = Array.isArray(cached) ? cached : (cached.items || []);
                const cachedTotal = typeof cached.total === 'number' ? cached.total : cachedItems.length;
                this.lastTotalCount = cachedTotal;
                this._mergeAndRender(cachedItems, query, null, cachedTotal);
                return;
            }

            if (this.abortController) {
                this.abortController.abort();
            }
            this.abortController = new AbortController();
            this._setLoading(true);
            this.loadError = '';

            try {
                const url = new URL(this.searchUrl, window.location.origin);
                if (query) {
                    url.searchParams.set('q', query);
                }
                url.searchParams.set('limit', '35');

                const resp = await fetch(url.toString(), {
                    method: 'GET',
                    signal: this.abortController.signal,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-Skip-Global-Loader': '1',
                        'Accept': 'application/json',
                    },
                });
                if (!resp.ok) {
                    throw new Error(`HTTP ${resp.status}`);
                }
                const data = await resp.json();
                const items = Array.isArray(data.results) ? data.results : [];
                const total = typeof data.total_count === 'number'
                    ? data.total_count
                    : (typeof data.total === 'number' ? data.total : (typeof data.count === 'number' ? data.count : items.length));
                this.remoteCache.set(normKey, { items, total });
                this.lastTotalCount = total;
                this._setLoading(false);
                if (this.isOpen) {
                    this._mergeAndRender(items, this.searchInput.value.trim(), null, total);
                }
            } catch (err) {
                if (err && err.name === 'AbortError') return;
                this._setLoading(false);
                this.loadError = 'تعذر تحميل النتائج الآن. يتم عرض الخيارات المتاحة محلياً.';
                if (this.isOpen) {
                    this._renderCurrentResults(this.searchInput.value.trim());
                }
            }
        }

        _renderCurrentResults(query) {
            const localItems = readLocalOptions(this.select);
            const normQuery = normalizeText(query);
            const filtered = normQuery
                ? localItems.filter((item) => matchesQuery(item.searchExtra, query))
                : localItems;

            // Also include cached remote results if present for same query
            if (this.searchUrl && this.remoteCache.has(normQuery)) {
                const cached = this.remoteCache.get(normQuery);
                const cachedItems = Array.isArray(cached) ? cached : (cached.items || []);
                const cachedTotal = typeof cached.total === 'number' ? cached.total : cachedItems.length;
                this.lastTotalCount = cachedTotal;
                this._mergeAndRender(cachedItems, query, filtered, cachedTotal);
            } else {
                this.lastTotalCount = filtered.length;
                this._renderList(filtered, query, filtered.length);
            }
        }

        _mergeAndRender(remoteItems, query, localPreFiltered, totalCount) {
            const seen = new Set();
            const merged = [];

            (remoteItems || []).forEach((item) => {
                const key = String(item.id);
                if (seen.has(key)) return;
                seen.add(key);
                merged.push({
                    id: key,
                    text: item.text || item.name || '',
                    subtext: item.subtext || '',
                    disabled: false,
                });
            });

            const locals = localPreFiltered || readLocalOptions(this.select).filter((item) => matchesQuery(item.searchExtra, query));
            locals.forEach((item) => {
                const key = String(item.id);
                if (seen.has(key)) return;
                seen.add(key);
                merged.push(item);
            });

            this._renderList(merged, query, totalCount);
        }

        _renderList(items, query, totalCount) {
            const currentVal = String(this.select.value || '');
            this.renderedItems = items;
            this.activeIndex = items.findIndex((it) => String(it.id) === currentVal && !it.disabled);
            if (this.activeIndex < 0 && items.length > 0) {
                this.activeIndex = items.findIndex((it) => !it.disabled);
            }

            this.listbox.innerHTML = '';

            // Optional clear / "all" choice at top when empty option exists and no query
            const emptyOpt = Array.from(this.select.options).find((o) => o.value === '');
            if (emptyOpt && !query && !this.select.required) {
                const resetLi = document.createElement('li');
                resetLi.className = [
                    'px-3 py-2 text-xs rounded-lg cursor-pointer transition-colors flex items-center justify-between',
                    currentVal === '' ? 'bg-teal-50 text-teal-800 font-semibold' : 'text-slate-500 hover:bg-slate-50',
                ].join(' ');
                resetLi.innerHTML = `<span>${escapeHtml(emptyOpt.textContent.trim() || this.placeholder)}</span>` +
                    (currentVal === '' ? '<span class="material-symbols-outlined text-[15px] text-teal-600">check</span>' : '');
                resetLi.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.clearSelection();
                    this.close(true);
                });
                this.listbox.appendChild(resetLi);
            }

            if (items.length === 0) {
                const emptyLi = document.createElement('li');
                emptyLi.className = 'px-3 py-5 text-center text-xs text-slate-400';
                emptyLi.textContent = this.isLoading
                    ? 'جارٍ البحث...'
                    : (this.loadError || 'لا توجد نتائج مطابقة');
                this.listbox.appendChild(emptyLi);
            } else {
                items.forEach((item, idx) => {
                    const isSelected = String(item.id) === currentVal;
                    const isActive = idx === this.activeIndex;
                    const li = document.createElement('li');
                    li.setAttribute('role', 'option');
                    li.setAttribute('aria-selected', isSelected ? 'true' : 'false');
                    li.setAttribute('data-index', String(idx));
                    li.className = [
                        'px-3 py-2 rounded-lg transition-colors flex items-center justify-between gap-2',
                        item.disabled ? 'opacity-50 cursor-not-allowed text-slate-400' : 'cursor-pointer',
                        isSelected
                            ? 'bg-teal-50 text-teal-900'
                            : (isActive ? 'bg-slate-100 text-slate-900' : 'text-slate-700 hover:bg-slate-50'),
                    ].join(' ');

                    const textWrap = document.createElement('div');
                    textWrap.className = 'min-w-0 flex-1';
                    const titleEl = document.createElement('div');
                    titleEl.className = 'text-sm font-medium truncate';
                    titleEl.textContent = item.text;
                    textWrap.appendChild(titleEl);

                    if (item.subtext) {
                        const subEl = document.createElement('div');
                        subEl.className = 'text-[11px] text-slate-400 truncate mt-0.5';
                        subEl.textContent = item.subtext;
                        textWrap.appendChild(subEl);
                    }

                    li.appendChild(textWrap);
                    if (isSelected) {
                        const check = document.createElement('span');
                        check.className = 'material-symbols-outlined text-[16px] text-teal-600 shrink-0';
                        check.textContent = 'check';
                        li.appendChild(check);
                    }

                    li.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.selectItem(item);
                    });

                    this.listbox.appendChild(li);
                });
            }

            const effTotal = (typeof totalCount === 'number' ? totalCount : this.lastTotalCount) || items.length;
            if (this.loadError && items.length > 0) {
                this.statusFooter.innerHTML = `<span class="text-rose-600">${escapeHtml(this.loadError)}</span>`;
                this.statusFooter.classList.remove('hidden');
            } else if (items.length > 0) {
                let countText = '';
                if (query) {
                    countText = `تم العثور على ${items.length}${effTotal > items.length ? ' من أصل ' + effTotal : ''} نتيجة`;
                } else if (effTotal > items.length) {
                    countText = `عرض ${items.length} من أصل ${effTotal} خيار متاح`;
                } else {
                    countText = `${items.length} خيار متاح`;
                }
                const hint = (this.searchUrl && effTotal > items.length)
                    ? '<span class="text-[10px] text-slate-400">ابحث للمزيد...</span>'
                    : '';
                this.statusFooter.innerHTML = `<span>${countText}</span>${hint}`;
                this.statusFooter.classList.remove('hidden');
            } else {
                this.statusFooter.classList.add('hidden');
            }
        }

        _moveActive(delta) {
            if (!this.renderedItems.length) return;
            let next = this.activeIndex;
            const total = this.renderedItems.length;
            for (let step = 0; step < total; step++) {
                next = (next + delta + total) % total;
                if (!this.renderedItems[next].disabled) {
                    this.activeIndex = next;
                    this._highlightActiveRow();
                    return;
                }
            }
        }

        _highlightActiveRow() {
            const rows = this.listbox.querySelectorAll('li[data-index]');
            rows.forEach((row) => {
                const idx = parseInt(row.getAttribute('data-index'), 10);
                const item = this.renderedItems[idx];
                const isSelected = item && String(item.id) === String(this.select.value || '');
                if (idx === this.activeIndex && !isSelected) {
                    row.classList.add('bg-slate-100', 'text-slate-900');
                    row.scrollIntoView({ block: 'nearest' });
                } else if (!isSelected) {
                    row.classList.remove('bg-slate-100', 'text-slate-900');
                }
            });
        }
    }

    function initSelect(selectEl) {
        if (!selectEl || selectEl._erpSmartSelect) return selectEl ? selectEl._erpSmartSelect : null;
        const inst = new SmartSelectInstance(selectEl);
        selectEl._erpSmartSelect = inst;
        return inst;
    }

    function initAll(root) {
        const container = root || document;
        container.querySelectorAll('select[data-smart-select="true"]').forEach((sel) => {
            initSelect(sel);
        });
    }

    window.ERPSmartSelect = {
        init: initSelect,
        initAll: initAll,
        refresh: function (selectEl) {
            if (selectEl && selectEl._erpSmartSelect) {
                selectEl._erpSmartSelect.syncFromSelect();
            }
        },
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initAll(document));
    } else {
        initAll(document);
    }
})();
