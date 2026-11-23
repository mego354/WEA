/**
 * Framework-agnostic, Capacitor-ready Notifications API Client, Native Push Lifecycle & Deep-Link Handler.
 * Supports:
 * - In-app notifications polling & summary
 * - Automatic Capacitor native push registration (@capacitor/push-notifications / AndroidPush / AppBuilderPush)
 * - Strictly rejects Web Push / browser Notification substitutes when registering native tokens
 * - Automatic re-registration on login/token refresh & automatic unregistration on logout
 * - Foreground in-app notification banner & deep-link validation/navigation
 */
(function (global) {
    'use strict';

    function getCookie(name) {
        const value = '; ' + document.cookie;
        const parts = value.split('; ' + name + '=');
        if (parts.length === 2) return parts.pop().split(';').shift();
        return '';
    }

    function maskToken(token) {
        const t = String(token || '').trim();
        if (t.length <= 14) return t.length > 6 ? (t.slice(0, 4) + '...' + t.slice(-2)) : '***';
        return t.slice(0, 8) + '...' + t.slice(-6);
    }

    function isSafeInternalUrl(rawUrl) {
        const u = String(rawUrl || '').trim();
        if (!u || u.startsWith('//')) return false;
        const lower = u.toLowerCase();
        if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('file:') || lower.startsWith('vbscript:')) {
            return false;
        }
        try {
            const parsed = new URL(u, global.location.origin);
            return parsed.origin === global.location.origin;
        } catch (e) {
            return false;
        }
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
                nativePush: {
                    isNative: false,
                    permissionStatus: 'unknown',
                    registered: false,
                    maskedToken: null,
                    lastError: null,
                },
            };
            this._listeners = new Set();
            this._timerId = null;
            this._boundVisibilityHandler = null;
            this._nativePushInitialized = false;
            this._currentToken = null;
            this._lastNavKey = '';
            this._lastNavTime = 0;
        }

        _getOrCreateDeviceUid(meta = {}) {
            const fromNative = String(meta.deviceUid || meta.device_uid || meta.installationId || meta.installation_id || '').trim();
            if (fromNative) return fromNative.slice(0, 128);
            const storageKey = 'wea_erp_device_uid_v1';
            try {
                let uid = global.localStorage.getItem(storageKey);
                if (!uid) {
                    uid = (global.crypto && typeof global.crypto.randomUUID === 'function')
                        ? global.crypto.randomUUID()
                        : ('dev-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10));
                    global.localStorage.setItem(storageKey, uid);
                }
                return uid;
            } catch (e) {
                return '';
            }
        }

        _handleUnauthorized(res) {
            if (res && res.status === 401) {
                this.stopPolling();
                this.state.error = 'انتهت جلسة العمل، يرجى تسجيل الدخول مجدداً.';
                this.state.authExpired = true;
                this._notify();
                return true;
            }
            return false;
        }

        subscribe(listener) {
            this._listeners.add(listener);
            return () => this._listeners.delete(listener);
        }

        _notify() {
            const snapshot = { ...this.state, nativePush: { ...this.state.nativePush } };
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
            if (this._handleUnauthorized(res)) return 0;
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
                if (this._handleUnauthorized(res)) return null;
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

        async registerDevice({
            deviceToken,
            platform = 'android',
            provider = 'fcm',
            deviceName = '',
            deviceUid = '',
            appVersion = '',
            appId = '',
            permissionStatus = 'granted',
        }) {
            const cleanToken = String(deviceToken || '').trim();
            if (!cleanToken) throw new Error('رمز الجهاز (device_token) مطلوب.');

            const res = await fetch(`${this.apiBase}/devices/register/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._headers(true),
                body: JSON.stringify({
                    device_token: cleanToken,
                    device_uid: deviceUid || this._getOrCreateDeviceUid(),
                    platform,
                    provider: provider || 'fcm',
                    device_name: deviceName,
                    app_version: appVersion,
                    app_id: appId,
                    permission_status: permissionStatus,
                }),
            });
            if (this._handleUnauthorized(res)) throw new Error('انتهت جلسة العمل.');
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                throw new Error(data.message || `HTTP ${res.status}`);
            }
            this._currentToken = cleanToken;
            this.state.nativePush.registered = true;
            this.state.nativePush.maskedToken = data.masked_token || maskToken(cleanToken);
            this.state.nativePush.lastError = null;
            this._notify();
            console.info('[ERPNotifications Push] Device registered with Django:', this.state.nativePush.maskedToken);
            return data;
        }

        async unregisterDevice(deviceToken, { keepalive = false } = {}) {
            const tok = String(deviceToken || this._currentToken || '').trim();
            if (!tok) return null;
            const res = await fetch(`${this.apiBase}/devices/unregister/`, {
                method: 'POST',
                credentials: 'same-origin',
                keepalive: Boolean(keepalive),
                headers: this._headers(true),
                body: JSON.stringify({ device_token: tok }),
            });
            return res.json().catch(() => ({}));
        }

        async sendTestPush({ title = '', body = '', targetUrl = '/notifications/', deviceId = null } = {}) {
            const res = await fetch(`${this.apiBase}/test-push/`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: this._headers(true),
                body: JSON.stringify({
                    title,
                    body,
                    target_url: targetUrl,
                    device_id: deviceId,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok && !data.status) {
                throw new Error(data.message || `HTTP ${res.status}`);
            }
            this.fetchUnreadCount().catch(() => {});
            return data;
        }

        async fetchDiagnostics() {
            const res = await fetch(`${this.apiBase}/diagnostics/`, {
                method: 'GET',
                credentials: 'same-origin',
                headers: this._headers(false),
            });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        }

        /**
         * Initializes Capacitor Native Push Registration & Deep-Link Handling.
         * Uses @capacitor/push-notifications bridge (exposed by Capacitor or MainActivity/AppDelegate).
         * Never substitutes browser Web Push or Notification API.
         */
        async initCapacitorNativePush() {
            if (this._nativePushInitialized) return;
            const isCapNative = Boolean(
                (global.Capacitor && typeof global.Capacitor.isNativePlatform === 'function' && global.Capacitor.isNativePlatform()) ||
                global.AndroidPush ||
                (global.webkit && global.webkit.messageHandlers && global.webkit.messageHandlers.AppBuilderPush)
            );
            if (!isCapNative) return;

            this._nativePushInitialized = true;
            this.state.nativePush.isNative = true;

            const platform = (global.Capacitor && typeof global.Capacitor.getPlatform === 'function')
                ? global.Capacitor.getPlatform()
                : (global.AndroidPush ? 'android' : 'ios');
            // Both Android and iOS use FCM tokens (Firebase Messaging bridges APNs -> FCM on iOS)
            const provider = 'fcm';

            // Bind logout links/forms to unregister device before session logout
            this._bindLogoutUnregister();
            // Consume any cold-start pending deep link passed by the native wrapper
            this.consumePendingDeepLink();

            const PushPlugin = global.Capacitor && global.Capacitor.Plugins && global.Capacitor.Plugins.PushNotifications;
            if (!PushPlugin) {
                console.warn('[ERPNotifications Push] Native platform detected but Capacitor.Plugins.PushNotifications is unavailable');
                return;
            }

            try {
                PushPlugin.addListener('registration', async (tokenObj) => {
                    const tokenVal = tokenObj && tokenObj.value ? String(tokenObj.value).trim() : '';
                    if (!tokenVal) return;
                    let meta = {};
                    if (global.AndroidPush && typeof global.AndroidPush.getDeviceMetadataJson === 'function') {
                        try { meta = JSON.parse(global.AndroidPush.getDeviceMetadataJson() || '{}'); } catch (e) {}
                    }
                    try {
                        await this.registerDevice({
                            deviceToken: tokenVal,
                            deviceUid: this._getOrCreateDeviceUid(meta),
                            platform,
                            provider,
                            deviceName: meta.deviceName || navigator.userAgent.slice(0, 80),
                            appVersion: meta.appVersion || '1.0.0',
                            appId: meta.appId || '',
                            permissionStatus: 'granted',
                        });
                    } catch (regErr) {
                        this.state.nativePush.lastError = regErr.message || String(regErr);
                        this._notify();
                        console.error('[ERPNotifications Push] Backend token registration error:', regErr.message);
                    }
                });

                PushPlugin.addListener('registrationError', (errObj) => {
                    const msg = (errObj && (errObj.error || errObj.message)) ? (errObj.error || errObj.message) : 'Native push registration error';
                    this.state.nativePush.lastError = msg;
                    this._notify();
                    console.warn('[ERPNotifications Push] Native registrationError:', msg);
                });

                PushPlugin.addListener('pushNotificationReceived', (notification) => {
                    console.info('[ERPNotifications Push] Foreground notification received:', notification && notification.id);
                    this.fetchUnreadCount().catch(() => {});
                    this.showForegroundNotificationBanner(notification);
                });

                PushPlugin.addListener('pushNotificationActionPerformed', (action) => {
                    const notif = (action && action.notification) ? action.notification : (action || {});
                    const data = notif.data || {};
                    // Prefer server-validated open_url (/notifications/<id>/open/) so auth, mark-read,
                    // RBAC, DataScope, and deleted-record fallback are always enforced server-side.
                    const rawTarget = data.open_url || data.target_url || data.action_url || data.url || '';
                    console.info('[ERPNotifications Push] Notification tap action received, target=', rawTarget);
                    this.navigateToDeepLink(rawTarget, data.notification_id);
                });

                const permStatus = await PushPlugin.checkPermissions();
                let receivePerm = permStatus && permStatus.receive ? permStatus.receive : 'prompt';
                if (receivePerm === 'prompt' || receivePerm === 'prompt-with-rationale') {
                    const reqResult = await PushPlugin.requestPermissions();
                    receivePerm = reqResult && reqResult.receive ? reqResult.receive : 'denied';
                }
                this.state.nativePush.permissionStatus = receivePerm;
                this._notify();

                if (receivePerm === 'granted') {
                    await PushPlugin.register();
                } else {
                    console.warn('[ERPNotifications Push] Notification permission not granted:', receivePerm);
                }
            } catch (err) {
                this.state.nativePush.lastError = err.message || String(err);
                this._notify();
                console.error('[ERPNotifications Push] Failed to initialize native push:', err);
            }
        }

        consumePendingDeepLink() {
            try {
                let pending = null;
                if (global.__ERP_PENDING_DEEP_LINK__) {
                    pending = global.__ERP_PENDING_DEEP_LINK__;
                    global.__ERP_PENDING_DEEP_LINK__ = null;
                } else if (global.AndroidPush && typeof global.AndroidPush.consumePendingDeepLink === 'function') {
                    const raw = global.AndroidPush.consumePendingDeepLink();
                    if (raw) {
                        try { pending = JSON.parse(raw); } catch (e) { pending = { open_url: String(raw) }; }
                    }
                } else if (global.sessionStorage) {
                    const stored = global.sessionStorage.getItem('erp_pending_deep_link');
                    if (stored) {
                        global.sessionStorage.removeItem('erp_pending_deep_link');
                        try { pending = JSON.parse(stored); } catch (e) { pending = { open_url: stored }; }
                    }
                }
                if (pending) {
                    const url = typeof pending === 'string'
                        ? pending
                        : (pending.open_url || pending.target_url || pending.action_url || '');
                    const notifId = typeof pending === 'object' ? (pending.notification_id || '') : '';
                    if (url || notifId) {
                        this.navigateToDeepLink(url, notifId);
                    }
                }
            } catch (e) {}
        }

        navigateToDeepLink(rawTargetUrl, notificationId) {
            let target = String(rawTargetUrl || '').trim();
            const hasNotifId = Boolean(notificationId && /^\d+$/.test(String(notificationId)));
            // Prefer canonical server gatekeeper (/notifications/<id>/open/) when notificationId is present
            if (hasNotifId && (!target || !target.includes(`/notifications/${notificationId}/open/`))) {
                target = `/notifications/${notificationId}/open/`;
            }
            if (!target) {
                target = '/notifications/';
            }
            if (!isSafeInternalUrl(target)) {
                console.warn('[ERPNotifications Push] Deep-link rejected (untrusted origin or scheme):', target);
                return false;
            }
            // Prevent duplicate rapid navigations (e.g., cold-start + intent replay within 1.5s)
            const navKey = `${target}|${notificationId || ''}`;
            const now = Date.now();
            if (this._lastNavKey === navKey && (now - this._lastNavTime) < 1500) {
                return false;
            }
            this._lastNavKey = navKey;
            this._lastNavTime = now;

            const resolved = new URL(target, global.location.origin).toString();
            if (global.location.href !== resolved) {
                global.location.href = resolved;
            }
            return true;
        }

        showForegroundNotificationBanner(notification) {
            if (!notification) return;
            const data = notification.data || {};
            const title = notification.title || data.title || 'إشعار جديد';
            const body = notification.body || data.body || '';
            const targetUrl = data.open_url || data.target_url || data.action_url || '/notifications/';
            const notifId = data.notification_id || notification.id || '';

            // Deduplicate foreground banner if native bridge already showed one for the same notification ID within 2s
            const dedupeId = `${notifId}:${title}:${body}`;
            if (this._lastBannerKey === dedupeId && (Date.now() - (this._lastBannerTime || 0)) < 2500) {
                return;
            }
            this._lastBannerKey = dedupeId;
            this._lastBannerTime = Date.now();

            const existing = document.getElementById('erpForegroundPushToast');
            if (existing) existing.remove();

            const toast = document.createElement('div');
            toast.id = 'erpForegroundPushToast';
            toast.setAttribute('dir', 'rtl');
            toast.style.cssText = [
                'position:fixed',
                'top:16px',
                'left:16px',
                'right:16px',
                'max-width:440px',
                'margin:0 auto',
                'z-index:99999',
                'background:#0f172a',
                'color:#f8fafc',
                'border:1px solid #27bebe',
                'border-radius:16px',
                'padding:14px 16px',
                'box-shadow:0 20px 35px -10px rgba(0,0,0,0.45)',
                'display:flex',
                'align-items:flex-start',
                'gap:12px',
                'cursor:pointer',
                'font-family:Cairo,sans-serif',
                'transition:all 0.25s ease',
            ].join(';');

            const iconDiv = document.createElement('div');
            iconDiv.style.cssText = 'width:38px;height:38px;border-radius:12px;background:rgba(39,190,190,0.18);color:#27bebe;display:flex;align-items:center;justify-content:center;flex-shrink:0;font-weight:bold;';
            iconDiv.textContent = '🔔';

            const contentDiv = document.createElement('div');
            contentDiv.style.cssText = 'flex:1;min-width:0;';

            const titleEl = document.createElement('div');
            titleEl.style.cssText = 'font-size:13px;font-weight:800;color:#ffffff;margin-bottom:2px;';
            titleEl.textContent = title;

            const bodyEl = document.createElement('div');
            bodyEl.style.cssText = 'font-size:12px;color:#cbd5e1;line-height:1.45;';
            bodyEl.textContent = body;

            const hintEl = document.createElement('div');
            hintEl.style.cssText = 'font-size:11px;color:#27bebe;font-weight:700;margin-top:5px;';
            hintEl.textContent = 'اضغط لفتح الصفحة المرتبطة ←';

            contentDiv.appendChild(titleEl);
            if (body) contentDiv.appendChild(bodyEl);
            contentDiv.appendChild(hintEl);

            const closeBtn = document.createElement('button');
            closeBtn.type = 'button';
            closeBtn.style.cssText = 'background:transparent;border:none;color:#94a3b8;font-size:16px;padding:2px 6px;cursor:pointer;';
            closeBtn.textContent = '✕';
            closeBtn.onclick = (e) => {
                e.stopPropagation();
                toast.remove();
            };

            toast.appendChild(iconDiv);
            toast.appendChild(contentDiv);
            toast.appendChild(closeBtn);

            toast.onclick = () => {
                toast.remove();
                this.navigateToDeepLink(targetUrl, notifId);
            };

            document.body.appendChild(toast);
            setTimeout(() => {
                if (toast.parentNode) toast.remove();
            }, 6500);
        }

        _bindLogoutUnregister() {
            if (this._logoutBound) return;
            this._logoutBound = true;
            const triggerUnregister = () => {
                try {
                    this.stopPolling();
                    if (global.AndroidPush && typeof global.AndroidPush.unregisterDevice === 'function') {
                        global.AndroidPush.unregisterDevice();
                    }
                    if (this._currentToken) {
                        this.unregisterDevice(this._currentToken, { keepalive: true }).catch(() => {});
                    }
                } catch (err) {}
            };

            document.addEventListener('click', (e) => {
                let a = e.target;
                while (a && a.tagName !== 'A') a = a.parentNode;
                if (!a || !a.href) return;
                if (a.href.includes('/logout/') || a.href.includes('/auth/logout/')) {
                    triggerUnregister();
                }
            }, true);

            document.addEventListener('submit', (e) => {
                const form = e.target;
                if (!form || !form.action) return;
                if (form.action.includes('/logout/') || form.action.includes('/auth/logout/')) {
                    triggerUnregister();
                }
            }, true);
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
            this._bindLogoutUnregister();
            this.initCapacitorNativePush().catch(() => {});
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
