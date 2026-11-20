/**
 * Unified Viewport-Safe Fixed-Position Row Action Menu (RTL)
 * Prevents clipping inside overflow-x-auto tables on desktop and mobile.
 */
(function () {
    let activeMenu = null;
    let activeBtn = null;
    let openedAt = 0;

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

    window.openRowActionMenu = function (btn, event) {
        if (event) {
            event.stopPropagation();
            event.preventDefault();
        }
        const host = btn.closest('[data-row-menu-host]');
        const tpl = host ? host.querySelector('template.row-menu-items') : null;
        const portal = document.getElementById('globalRowActionMenu');
        if (!tpl || !portal) return;

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

        // Position fixed relative to viewport, flipping up/right if near edge
        const rect = btn.getBoundingClientRect();
        const menuW = portal.offsetWidth || 200;
        const menuH = portal.offsetHeight || 160;
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

        portal.style.left = left + 'px';
        portal.style.top = top + 'px';

        // Focus first interactive item without causing viewport scroll
        const firstItem = portal.querySelector('a, button');
        if (firstItem && firstItem.focus) {
            try {
                firstItem.focus({ preventScroll: true });
            } catch (_) {
                firstItem.focus();
            }
        }
    };

    document.addEventListener('click', function (e) {
        if (!activeMenu) return;
        const insideMenu = e.target.closest('#globalRowActionMenu');
        if (insideMenu) {
            if (e.target.closest('a, button')) {
                setTimeout(closeMenu, 0);
            }
            return;
        }
        if (!e.target.closest('[data-row-menu-trigger]')) {
            closeMenu();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (!activeMenu) return;
        if (e.key === 'Escape') {
            const btn = activeBtn;
            closeMenu();
            if (btn) btn.focus();
            return;
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
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
        if (!activeMenu) return;
        if (Date.now() - openedAt < 150) return;
        if (e && e.target && e.target.closest && e.target.closest('#globalRowActionMenu')) return;
        closeMenu();
    }, true);
    window.addEventListener('resize', closeMenu);

    window.toggleDetailActionMenu = function (btn) {
        const wrap = btn.closest('[data-detail-action-menu]');
        const menu = wrap ? wrap.querySelector('.detail-action-dropdown') : null;
        if (!menu) return;
        const isOpen = !menu.classList.contains('hidden');
        document.querySelectorAll('.detail-action-dropdown').forEach(el => el.classList.add('hidden'));
        if (!isOpen) {
            menu.classList.remove('hidden');
            if (window.innerWidth < 640) {
                const rect = btn.getBoundingClientRect();
                menu.style.top = (rect.bottom + 6) + 'px';
                menu.style.left = Math.max(12, rect.left) + 'px';
            } else {
                menu.style.top = '';
                menu.style.left = '';
            }
            btn.setAttribute('aria-expanded', 'true');
        } else {
            btn.setAttribute('aria-expanded', 'false');
        }
    };

    document.addEventListener('click', function (e) {
        if (!e.target.closest('[data-detail-action-menu]')) {
            document.querySelectorAll('.detail-action-dropdown').forEach(el => el.classList.add('hidden'));
        }
    });
})();
