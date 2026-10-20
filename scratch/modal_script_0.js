
    let unifiedModalCurrentCustomer = null;
    let unifiedModalCachedTemplates = null;
    let unifiedModalSearchTimeout = null;

    // Open Unified Customer Selection Modal
    // mode: 'unplanned_visit' | 'add_to_plan'
    // options: { date: 'YYYY-MM-DD', assigneeId: '123', contactId: '...', contactData: {...} }
    async function openCustomerSelectionModal(mode = 'unplanned_visit', options = {}) {
        const modal = document.getElementById('unified-customer-selection-modal');
        if (!modal) return;

        // Reset state & error
        hideUnifiedModalError();
        clearUnifiedCustomerSelection();

        const modeInput = document.getElementById('modal-mode');
        const titleEl = document.getElementById('customer-selection-modal-title');
        const iconEl = document.getElementById('modal-header-icon');
        const submitText = document.getElementById('unified-submit-text');
        const submitIcon = document.getElementById('unified-submit-icon');
        const planFields = document.getElementById('unified-plan-context-fields');
        const planDateInput = document.getElementById('modal-plan-date');
        const planDateDisplay = document.getElementById('unified-plan-date-display');
        const assigneeInput = document.getElementById('modal-assignee-id');

        modeInput.value = mode;

        if (mode === 'add_to_plan') {
            titleEl.textContent = 'إضافة عميل إلى الخطة';
            if (iconEl) iconEl.textContent = 'event_available';
            submitText.textContent = 'إضافة إلى الخطة';
            if (submitIcon) submitIcon.textContent = 'playlist_add';
            planFields.classList.remove('hidden');

            const dateVal = options.date || new Date().toISOString().split('T')[0];
            planDateInput.value = dateVal;
            if (planDateDisplay) planDateDisplay.value = dateVal;
            if (assigneeInput) assigneeInput.value = options.assigneeId || '';
        } else {
            titleEl.textContent = 'زيارة خارج الخطة';
            if (iconEl) iconEl.textContent = 'room';
            submitText.textContent = 'تسجيل الزيارة';
            if (submitIcon) submitIcon.textContent = 'directions_walk';
            planFields.classList.add('hidden');
        }

        // Load templates into select if not loaded
        await loadUnifiedTemplates();

        // If pre-supplied contactData or contactId
        if (options.contactData) {
            selectUnifiedCustomer(options.contactData);
        } else if (options.contactId) {
            fetchUnifiedCustomerById(options.contactId);
        }

        modal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');

        // Focus search input if no customer preselected
        if (!options.contactData && !options.contactId) {
            setTimeout(() => {
                const searchInput = document.getElementById('unified-customer-search-input');
                if (searchInput) searchInput.focus();
            }, 100);
        }
    }

    function closeCustomerSelectionModal() {
        const modal = document.getElementById('unified-customer-selection-modal');
        if (modal) {
            modal.classList.add('hidden');
            document.body.classList.remove('overflow-hidden');
            const dropdown = document.getElementById('unified-customer-dropdown');
            if (dropdown) dropdown.classList.add('hidden');
        }
    }

    async function loadUnifiedTemplates() {
        const select = document.getElementById('unified-template-select');
        if (!select || select.options.length > 1) return;

        if (unifiedModalCachedTemplates) {
            renderUnifiedTemplateOptions(unifiedModalCachedTemplates);
            return;
        }

        try {
            const res = await fetch('/activities/api/templates/');
            if (res.ok) {
                const data = await res.json();
                unifiedModalCachedTemplates = data.results || [];
                renderUnifiedTemplateOptions(unifiedModalCachedTemplates);
            }
        } catch(e) {
            console.warn('Failed to load visit templates:', e);
        }
    }

    function renderUnifiedTemplateOptions(templates) {
        const select = document.getElementById('unified-template-select');
        if (!select) return;
        select.innerHTML = '<option value="">اختر قالب الزيارة</option>';
        templates.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.textContent = t.display_name_ar || t.name;
            select.appendChild(opt);
        });
    }

    // Typeahead Search Logic
    function handleUnifiedCustomerSearch(e) {
        clearTimeout(unifiedModalSearchTimeout);
        const query = e.target.value.trim();
        const spinner = document.getElementById('unified-search-spinner');
        const dropdown = document.getElementById('unified-customer-dropdown');
        const listEl = document.getElementById('unified-customer-results-list');

        if (spinner) spinner.classList.remove('hidden');

        unifiedModalSearchTimeout = setTimeout(async function() {
            try {
                const res = await fetch(`/contacts/api/search/?q=${encodeURIComponent(query)}`);
                if (res.ok) {
                    const data = await res.json();
                    const list = data.results || [];
                    renderUnifiedSearchResults(list);
                }
            } catch(err) {
                if (listEl) listEl.innerHTML = '<p class="text-xs text-rose-500 text-center py-3">حدث خطأ أثناء تحميل العملاء</p>';
            } finally {
                if (spinner) spinner.classList.add('hidden');
                if (dropdown) dropdown.classList.remove('hidden');
            }
        }, 250);
    }

    function openUnifiedSearchResults() {
        const input = document.getElementById('unified-customer-search-input');
        if (input) {
            handleUnifiedCustomerSearch({ target: input });
        }
    }

    function clearUnifiedSearchInput() {
        const input = document.getElementById('unified-customer-search-input');
        if (input) {
            input.value = '';
            input.focus();
            openUnifiedSearchResults();
        }
    }

    let unifiedModalSearchResultsMap = new Map();

    function selectUnifiedCustomerById(id) {
        const c = unifiedModalSearchResultsMap.get(String(id));
        if (c) selectUnifiedCustomer(c);
    }

    function renderUnifiedSearchResults(contacts) {
        const listEl = document.getElementById('unified-customer-results-list');
        if (!listEl) return;

        unifiedModalSearchResultsMap.clear();
        if (!contacts.length) {
            listEl.innerHTML = '<p class="text-xs text-slate-400 text-center py-4">لم يتم العثور على أي عملاء مطابقين للبحث.</p>';
            return;
        }

        contacts.forEach(c => unifiedModalSearchResultsMap.set(String(c.id), c));

        listEl.innerHTML = contacts.map(c => `
            <div onclick="selectUnifiedCustomerById('${c.id}')"
                 class="flex items-center justify-between p-2.5 rounded-xl hover:bg-teal-50/60 cursor-pointer transition-colors">
                <div class="flex items-center gap-3 min-w-0">
                    <div class="w-8 h-8 rounded-full bg-[#27bebe] text-white font-bold text-xs flex items-center justify-center shrink-0">
                        ${c.initials || (c.name ? c.name.substring(0, 2) : 'CL')}
                    </div>
                    <div class="min-w-0">
                        <div class="flex items-center gap-1.5 flex-wrap">
                            <span class="text-xs font-bold text-slate-900 truncate">${c.formatted_number || c.code ? '[' + (c.formatted_number || c.code) + '] ' : ''}${c.name}</span>
                            <span class="px-1.5 py-0.2 rounded text-[10px] font-semibold bg-slate-100 text-slate-600">${c.account_type || c.category || 'عميل'}</span>
                        </div>
                        <div class="text-[11px] text-slate-500 flex items-center gap-1.5 mt-0.5">
                            <span>${c.specialty || 'عام'}</span>
                            <span>•</span>
                            <span>${c.area_name || 'غير محدد'}</span>
                        </div>
                    </div>
                </div>
                <div class="shrink-0 text-left">
                    ${c.has_saved_location ? '<span class="material-symbols-outlined text-sm text-emerald-600" title="موقع محفوظ">pin_drop</span>' : '<span class="material-symbols-outlined text-sm text-slate-300" title="لا يوجد موقع مسجل">location_off</span>'}
                </div>
            </div>
        `).join('');
    }

    function selectUnifiedCustomer(c) {
        unifiedModalCurrentCustomer = c;
        document.getElementById('modal-selected-contact-id').value = c.id;

        const searchContainer = document.getElementById('unified-search-box-container');
        const card = document.getElementById('unified-selected-customer-card');
        const dropdown = document.getElementById('unified-customer-dropdown');

        if (dropdown) dropdown.classList.add('hidden');
        if (searchContainer) searchContainer.classList.add('hidden');
        if (card) card.classList.remove('hidden');

        // Populate card
        const nameEl = document.getElementById('unified-card-name');
        const avatarEl = document.getElementById('unified-card-avatar');
        const catEl = document.getElementById('unified-card-category-badge');
        const specEl = document.getElementById('unified-card-specialty');
        const areaEl = document.getElementById('unified-card-area');
        const typeEl = document.getElementById('unified-card-type-badge');
        const gpsEl = document.getElementById('unified-card-gps-indicator');
        const directionsBtn = document.getElementById('unified-card-directions-btn');
        const previewBtn = document.getElementById('unified-card-preview-btn');

        const codeStr = c.formatted_number || c.code ? `[${c.formatted_number || c.code}] ` : '';
        if (nameEl) nameEl.textContent = `${codeStr}${c.name}`;
        if (avatarEl) avatarEl.textContent = c.initials || (c.name ? c.name.substring(0, 2) : 'CL');
        if (catEl) catEl.textContent = c.category || c.account_type || 'عميل';
        if (typeEl) typeEl.textContent = c.contact_type_display || 'شخص';
        if (specEl) specEl.textContent = `التخصص: ${c.specialty || 'عام'}`;
        if (areaEl) areaEl.textContent = `المنطقة: ${c.area_name || 'غير محددة'}`;

        if (previewBtn) previewBtn.href = `/contacts/${c.id}/`;

        if (c.latitude && c.longitude) {
            if (directionsBtn) {
                directionsBtn.classList.remove('hidden');
                directionsBtn.href = `https://www.google.com/maps/dir/?api=1&destination=${c.latitude},${c.longitude}`;
            }
            if (gpsEl) {
                gpsEl.innerHTML = `
                    <span class="inline-flex items-center gap-1 text-emerald-700 font-bold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                        <span class="material-symbols-outlined text-xs">pin_drop</span>
                        <span>موقع محفوظ: ${Number(c.latitude).toFixed(4)}, ${Number(c.longitude).toFixed(4)}</span>
                    </span>
                `;
            }
        } else {
            if (directionsBtn) directionsBtn.classList.add('hidden');
            if (gpsEl) {
                gpsEl.innerHTML = `
                    <span class="inline-flex items-center gap-1 text-amber-700 font-medium bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                        <span class="material-symbols-outlined text-xs">info</span>
                        <span>لا يوجد موقع مسجل للعميل</span>
                    </span>
                `;
            }
        }

        // Filter templates according to customer's account type
        const select = document.getElementById('unified-template-select');
        if (select && unifiedModalCachedTemplates) {
            const custType = (c.account_type || c.category || '').trim().toLowerCase();
            select.innerHTML = '<option value="">اختر قالب الزيارة</option>';
            unifiedModalCachedTemplates.forEach(t => {
                const targetTypes = (t.restrict_account_types || []).map(x => x.toLowerCase());
                if (!targetTypes.length || !custType || targetTypes.includes(custType)) {
                    const opt = document.createElement('option');
                    opt.value = t.id;
                    opt.textContent = t.display_name_ar || t.name;
                    select.appendChild(opt);
                }
            });
            if (select.options.length === 2) {
                select.selectedIndex = 1;
            }
        }

        hideUnifiedModalError();
    }

    function clearUnifiedCustomerSelection() {
        unifiedModalCurrentCustomer = null;
        document.getElementById('modal-selected-contact-id').value = '';

        const searchContainer = document.getElementById('unified-search-box-container');
        const card = document.getElementById('unified-selected-customer-card');
        const searchInput = document.getElementById('unified-customer-search-input');

        if (card) card.classList.add('hidden');
        if (searchContainer) searchContainer.classList.remove('hidden');
        if (searchInput) {
            searchInput.value = '';
        }
    }

    async function fetchUnifiedCustomerById(id) {
        try {
            const res = await fetch(`/contacts/api/search/?q=&id=${id}`);
            if (res.ok) {
                const data = await res.json();
                const list = data.results || [];
                const found = list.find(item => item.id == id);
                if (found) selectUnifiedCustomer(found);
            }
        } catch(e) {}
    }

    function showUnifiedModalError(msg) {
        const errBox = document.getElementById('unified-modal-error');
        const errText = document.getElementById('unified-modal-error-text');
        if (errBox && errText) {
            errText.textContent = msg;
            errBox.classList.remove('hidden');
        }
    }

    function hideUnifiedModalError() {
        const errBox = document.getElementById('unified-modal-error');
        if (errBox) errBox.classList.add('hidden');
    }

    // Form Submit Handler
    async function handleUnifiedModalSubmit(e) {
        e.preventDefault();
        hideUnifiedModalError();

        const contactId = document.getElementById('modal-selected-contact-id').value;
        if (!contactId || !unifiedModalCurrentCustomer) {
            showUnifiedModalError('يرجى اختيار العميل أولاً للمتابعة.');
            return false;
        }

        const mode = document.getElementById('modal-mode').value;
        const templateId = document.getElementById('unified-template-select').value;
        const submitBtn = document.getElementById('unified-modal-submit-btn');

        if (mode === 'unplanned_visit') {
            // UNPLANNED VISIT: Route into canonical visit form with selected contact & template
            let url = `/visits/create/?contact_id=${contactId}`;
            if (templateId) url += `&template_id=${templateId}`;
            window.location.href = url;
            return false;
        }

        if (mode === 'add_to_plan') {
            // ADD TO PLAN: POST to planned_visit_add_item
            const dateStr = document.getElementById('modal-plan-date').value;
            const assigneeId = document.getElementById('modal-assignee-id').value;
            const notes = document.getElementById('unified-plan-notes').value;

            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.classList.add('opacity-75', 'cursor-not-allowed');
            }

            try {
                const formData = new FormData();
                formData.append('contact_id', contactId);
                formData.append('date', dateStr);
                formData.append('assignee_id', assigneeId);
                formData.append('template_id', templateId);
                formData.append('notes', notes);

                // Get CSRF token
                const csrfToken = document.querySelector('#unified-customer-selection-form input[name="csrfmiddlewaretoken"]')?.value;

                const res = await fetch('/planned-visits/add-item/', {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrfToken,
                        'X-Requested-With': 'XMLHttpRequest',
                        'Accept': 'application/json'
                    },
                    body: formData
                });

                const data = await res.json();
                if (res.ok && data.success) {
                    closeCustomerSelectionModal();
                    // Reload page anchored to target day
                    window.location.href = `${window.location.pathname}${window.location.search}#day-${dateStr}`;
                    window.location.reload();
                } else {
                    showUnifiedModalError(data.message || 'فشلت إضافة العميل إلى الخطة.');
                }
            } catch(err) {
                showUnifiedModalError('حدث خطأ في الاتصال بالخادم. يرجى إعادة المحاولة.');
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('opacity-75', 'cursor-not-allowed');
                }
            }
        }

        return false;
    }
