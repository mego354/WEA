/**
 * Unified Viewport-Safe Fixed-Position Row & Detail Action Menus (RTL)
 * Prevents clipping inside overflow-x-auto tables and clamps cleanly within viewport on desktop & mobile.
 */
(function () {
    let activeMenu = null;
    let activeBtn = null;
    let openedAt = 0;

    function positionFixedPopover(panel, btn) {
        const rect = btn.getBoundingClientRect();
        const menuW = panel.offsetWidth || 210;
        const menuH = panel.offsetHeight || 160;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        let left = rect.left;
        if (left + menuW > vw - 12) {
            left = Math.max(12, rect.right - menuW);
        }
        if (left < 12) left = 12;

        let top = rect.bottom + 6;
        if (top + menuH > vh - 12) {
            top = Math.max(12, rect.top - menuH - 6);
        }

        panel.style.left = left + 'px';
        panel.style.right = 'auto';
        panel.style.top = top + 'px';
    }

    function closeMenu() {
        if (activeMenu) {
            activeMenu.classList.add('hidden');
            activeMenu.innerHTML = '';
            activeMenu = null;
        }
        if (activeBtn) {
            activeBtn.setAttribute('aria-expanded', 'false');
            activeBtn = null;
        }
    }

    function closeAllDetailMenus() {
        document.querySelectorAll('.detail-action-dropdown').forEach(el => {
            el.classList.add('hidden');
        });
        document.querySelectorAll('[data-detail-action-menu] > button').forEach(b => {
            b.setAttribute('aria-expanded', 'false');
        });
    }

    window.openRowActionMenu = function (btn, event) {
        if (event) {
            event.stopPropagation();
            event.preventDefault();
        }
        const host = btn.closest('[data-row-menu-host]');
        const tpl = host ? host.querySelector('template.row-menu-items') : null;
        const portal = document.getElementById('globalRowActionMenu');
        if (!tpl || !portal) return;

        closeAllDetailMenus();
        if (activeBtn === btn && !portal.classList.contains('hidden')) {
            closeMenu();
            return;
        }
        closeMenu();

        portal.innerHTML = tpl.innerHTML;
        portal.classList.remove('hidden');
        activeMenu = portal;
        activeBtn = btn;
        openedAt = Date.now();
        btn.setAttribute('aria-expanded', 'true');

        positionFixedPopover(portal, btn);

        const firstItem = portal.querySelector('a, button');
        if (firstItem && firstItem.focus) {
            try {
                firstItem.focus({ preventScroll: true });
            } catch (_) {
                firstItem.focus();
            }
        }
    };

    window.toggleDetailActionMenu = function (btn, event) {
        if (event) {
            event.stopPropagation();
        }
        const wrap = btn.closest('[data-detail-action-menu]');
        const menu = wrap ? wrap.querySelector('.detail-action-dropdown') : null;
        if (!menu) return;

        closeMenu();
        const isOpen = !menu.classList.contains('hidden');
        closeAllDetailMenus();
        if (!isOpen) {
            menu.classList.add('fixed');
            menu.classList.remove('hidden', 'sm:absolute');
            positionFixedPopover(menu, btn);
            openedAt = Date.now();
            btn.setAttribute('aria-expanded', 'true');
        }
    };

    document.addEventListener('click', function (e) {
        if (activeMenu) {
            const insideMenu = e.target.closest('#globalRowActionMenu');
            if (insideMenu) {
                if (e.target.closest('a, button')) {
                    setTimeout(closeMenu, 0);
                }
            } else if (!e.target.closest('[data-row-menu-trigger]')) {
                closeMenu();
            }
        }

        const insideDetail = e.target.closest('.detail-action-dropdown');
        if (insideDetail) {
            if (e.target.closest('a, button')) {
                setTimeout(closeAllDetailMenus, 0);
            }
        } else if (!e.target.closest('[data-detail-action-menu]')) {
            closeAllDetailMenus();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            if (activeMenu) {
                const btn = activeBtn;
                closeMenu();
                if (btn) btn.focus();
            }
            closeAllDetailMenus();
            return;
        }
        if (activeMenu && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            const items = Array.from(activeMenu.querySelectorAll('a, button'));
            if (!items.length) return;
            e.preventDefault();
            const idx = items.indexOf(document.activeElement);
            const nextIdx = e.key === 'ArrowDown'
                ? (idx + 1) % items.length
                : (idx - 1 + items.length) % items.length;
            items[nextIdx].focus();
        }
    });

    window.addEventListener('scroll', function (e) {
        if (Date.now() - openedAt < 150) return;
        if (activeMenu && !(e && e.target && e.target.closest && e.target.closest('#globalRowActionMenu'))) {
            closeMenu();
        }
        if (!(e && e.target && e.target.closest && e.target.closest('.detail-action-dropdown'))) {
            closeAllDetailMenus();
        }
    }, true);

    window.addEventListener('resize', function () {
        closeMenu();
        closeAllDetailMenus();
    });
})();
