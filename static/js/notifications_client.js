/**
 * Framework-agnostic, Capacitor-ready Notifications API Client & State Store.
 * Completely decoupled from web popover/drawer DOM so it can be reused inside
 * Capacitor Android / iOS WebView wrappers or external JS clients.
 */
(function (global) {
    'use strict';

    function getCookie(name) {
        const value = '; ' + document.cookie;
        const parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    class ERPNotificationsClient {
        constructor(options = {}) {
            this.apiBase = (options.apiBase || '/api/v1/notifications').replace(/\/$/, '');
            this.pollIntervalMs = options.pollIntervalMs || 45000;
            this.state = {
                unreadCount: 0,
                items: [],
                loading: false,
                error: null,
                lastUpdatedAt: null,
            };
            this._listeners = new Set();
            this._timerId = null;
            this._boundVisibilityHandler = null;
        }

        subscribe(listener) {
            this._listeners.add(listener);
            return () => this._listeners.delete(listener);
        }

        _notify() {
            const snapshot = { ...this.state };
            this._listeners.forEach(fn => {
                try { fn(snapshot); } catch (e) {}
            });
        }

        _headers(isWrite = false) {
            const h = {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
                'X-Skip-Global-Loader': '1',
            };
            if (isWrite) {
                h['Content-Type'] = 'application/json';
                const csrf = getCookie('csrftoken');
                if (csrf) h['X-CSRFToken'] = csrf;
            }
            return h;
        }

        async fetchUnreadCount() {
            const res = await fetch(`${this.apiBase}/unread-count/`, {
                method: 'GET',
                credentials: 'same-origin',
                headers: this._headers(false),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.state.unreadCount = Number(data.unread_count || 0);
            this.state.lastUpdatedAt = new Date();
            this.state.error = null;
            this._notify();
            return this.state.unreadCount;
        }

        async fetchSummary(limit = 12) {
            this.state.loading = true;
            this.state.error = null;
            this._notify();
            try {
                const res = await fetch(`${this.apiBase}/summary/?limit=${encodeURIComponent(limit)}`, {
                    method: 'GET',
                    credentials: 'same-origin',
                    headers: this._headers(false),
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                this.state.unreadCount = Number(data.unread_count || 0);
                this.state.items = Array.isArray(data.items) ? data.items : [];
                this.state.lastUpdatedAt = new Date();
                this.state.error = null;
                return data;
            } catch (err) {
                this.state.error = 'تعذر تحميل الإشعارات حالياً.';
                throw err;
            } finally {
                this.state.loading = false;
                this._notify();
            }
        }

        async fetchList(params = {}) {
            const url = new URL(`${this.apiBase}/`, global.location.origin);
            Object.entries(params).forEach(([k, v]) => {
                if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v);
            });
            const res = await fetch(url.toString(), {
                method: 'GET',
                credentials: 'same-origin',
                headers: this._headers(false),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }

        async markAsRead(notificationId) {
            const res = await fetch(`${this.apiBase}/${encodeURIComponent(notificationId)}/read/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._headers(true),
                body: JSON.stringify({}),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.state.unreadCount = Number(data.unread_count || 0);
            this.state.items = this.state.items.map(it =>
                String(it.id) === String(notificationId) ? { ...it, is_read: true } : it
            );
            this._notify();
            return data;
        }

        async markAllAsRead(moduleFilter = '') {
            const res = await fetch(`${this.apiBase}/read-all/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._headers(true),
                body: JSON.stringify(moduleFilter ? { module: moduleFilter } : {}),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.state.unreadCount = Number(data.unread_count || 0);
            this.state.items = this.state.items.map(it =>
                (!moduleFilter || it.module === moduleFilter) ? { ...it, is_read: true } : it
            );
            this._notify();
            return data;
        }

        async registerDevice({ deviceToken, platform = 'android', provider = 'fcm', deviceName = '', appVersion = '' }) {
            const res = await fetch(`${this.apiBase}/devices/register/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._headers(true),
                body: JSON.stringify({
                    device_token: deviceToken,
                    platform,
                    provider,
                    device_name: deviceName,
                    app_version: appVersion,
                }),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }

        startPolling() {
            this.stopPolling();
            const tick = () => {
                if (document.visibilityState === 'visible') {
                    this.fetchUnreadCount().catch(() => {});
                }
            };
            tick();
            this._timerId = global.setInterval(tick, this.pollIntervalMs);
            this._boundVisibilityHandler = () => {
                if (document.visibilityState === 'visible') {
                    this.fetchUnreadCount().catch(() => {});
                }
            };
            document.addEventListener('visibilitychange', this._boundVisibilityHandler);
        }

        stopPolling() {
            if (this._timerId) {
                global.clearInterval(this._timerId);
                this._timerId = null;
            }
            if (this._boundVisibilityHandler) {
                document.removeEventListener('visibilitychange', this._boundVisibilityHandler);
                this._boundVisibilityHandler = null;
            }
        }
    }

    global.ERPNotificationsClient = ERPNotificationsClient;
})(window);
