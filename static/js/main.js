/**
 * main.js — Moodle Quiz Assistant frontend JS
 */

// ─── Health Check ─────────────────────────────────────────────
async function checkSystemStatus() {
    try {
        const res = await fetch('/api/health', { signal: AbortSignal.timeout(3000) });
        if (res.ok) {
            const data = await res.json();
            const dot = document.getElementById('status-dot');
            const text = document.getElementById('status-text');
            if (dot && text) {
                if (data.status === 'ok') {
                    dot.style.background = data.gemini_configured ? 'var(--accent-green)' : 'var(--accent-orange)';
                    dot.style.boxShadow = data.gemini_configured ? '0 0 6px var(--accent-green)' : '0 0 6px var(--accent-orange)';
                    text.textContent = data.gemini_configured ? 'System Ready' : 'API Key Missing';
                }
            }
        }
    } catch {
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        if (dot) dot.style.background = 'var(--accent-red)';
        if (text) text.textContent = 'Offline';
    }
}

// ─── Toast System ─────────────────────────────────────────────
function showToast(type, title, message, duration = 5000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
        error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
        warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`,
    };

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
        <div class="toast-icon toast-icon--${type}">${icons[type] || icons.info}</div>
        <div>
            <div class="toast-title">${escapeHtml(title)}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
    `;

    container.appendChild(toast);

    // Auto-remove
    setTimeout(() => {
        toast.style.animation = 'fadeOut 0.3s ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, duration);

    // Click to dismiss
    toast.addEventListener('click', () => toast.remove());
}

// ─── HTML Escaping ────────────────────────────────────────────
function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(String(str)));
    return div.innerHTML;
}

// ─── Notification Poll ────────────────────────────────────────
let _lastNotifCount = 0;

async function pollNotifications() {
    try {
        const res = await fetch('/api/notifications?unread_only=true&limit=5', {
            signal: AbortSignal.timeout(2000)
        });
        if (res.ok) {
            const data = await res.json();
            const notifs = data.notifications || [];
            const badge = document.getElementById('notif-badge');
            
            if (badge) {
                const count = notifs.length;
                if (count > 0) {
                    badge.textContent = count > 99 ? '99+' : count;
                    badge.classList.remove('hidden');
                } else {
                    badge.classList.add('hidden');
                }

                // Show toast for new notifications
                if (count > _lastNotifCount) {
                    const newest = notifs[0];
                    if (newest) {
                        const type = newest.level === 'error' ? 'error' 
                                   : newest.level === 'warning' ? 'warning'
                                   : newest.level === 'success' ? 'success' : 'info';
                        showToast(type, newest.title, newest.message, 4000);
                    }
                }
                _lastNotifCount = count;
            }
        }
    } catch {
        // Silently fail
    }
}

// ─── Sidebar Toggle ───────────────────────────────────────────
function initSidebarToggle() {
    const toggle = document.getElementById('menu-toggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    if (!toggle || !sidebar) return;

    function openSidebar() {
        sidebar.classList.add('open');
        if (backdrop) backdrop.classList.add('active');
        document.body.classList.add('sidebar-open');
    }

    function closeSidebar() {
        sidebar.classList.remove('open');
        if (backdrop) backdrop.classList.remove('active');
        document.body.classList.remove('sidebar-open');
    }

    toggle.addEventListener('click', (e) => {
        e.stopPropagation();
        if (sidebar.classList.contains('open')) {
            closeSidebar();
        } else {
            openSidebar();
        }
    });

    if (backdrop) {
        backdrop.addEventListener('click', closeSidebar);
    }

    // Close sidebar when clicking any navigation link on mobile
    sidebar.querySelectorAll('.sidebar-link').forEach(link => {
        link.addEventListener('click', () => {
            if (window.innerWidth <= 1024) {
                closeSidebar();
            }
        });
    });

    // Close sidebar on outside click (mobile)
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 1024 &&
            sidebar.classList.contains('open') &&
            !sidebar.contains(e.target) &&
            !toggle.contains(e.target)) {
            closeSidebar();
        }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar.classList.contains('open')) {
            closeSidebar();
        }
    });
}

// ─── Notification Dropdown ────────────────────────────────────
function initNotificationDropdown() {
    const bell = document.getElementById('notif-bell');
    const dropdown = document.getElementById('notif-dropdown');
    const markAllBtn = document.getElementById('mark-all-read-btn');
    if (!bell || !dropdown) return;

    bell.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.classList.toggle('hidden');
        if (!dropdown.classList.contains('hidden')) {
            loadNotificationList();
        }
    });

    document.addEventListener('click', (e) => {
        if (!dropdown.contains(e.target) && !bell.contains(e.target)) {
            dropdown.classList.add('hidden');
        }
    });

    if (markAllBtn) {
        markAllBtn.addEventListener('click', async (e) => {
            e.stopPropagation();
            try {
                await fetch('/api/notifications/mark-all-read', { method: 'POST' });
                const badge = document.getElementById('notif-badge');
                if (badge) badge.classList.add('hidden');
                loadNotificationList();
            } catch (err) {
                console.error('Error marking all notifications read:', err);
            }
        });
    }
}

async function loadNotificationList() {
    const list = document.getElementById('notif-list');
    if (!list) return;

    try {
        const res = await fetch('/api/notifications?limit=25');
        if (!res.ok) return;
        const data = await res.json();
        const notifs = data.notifications || [];

        if (notifs.length === 0) {
            list.innerHTML = '<div class="notif-empty">No notifications yet</div>';
            return;
        }

        list.innerHTML = notifs.map(n => {
            const timeStr = new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `
                <div class="notif-item ${n.read ? '' : 'unread'} level-${n.level}">
                    <div class="notif-item-title">
                        <span>${escapeHtml(n.title)}</span>
                    </div>
                    <div class="notif-item-msg">${escapeHtml(n.message)}</div>
                    <div class="notif-item-time">${timeStr}</div>
                </div>
            `;
        }).join('');
    } catch (err) {
        list.innerHTML = '<div class="notif-empty">Failed to load notifications</div>';
    }
}

// ─── Initialize ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkSystemStatus();
    initSidebarToggle();
    initNotificationDropdown();
    
    // Poll notifications every 5 seconds
    setInterval(pollNotifications, 5000);
    pollNotifications();

    // Re-check system health every 30 seconds
    setInterval(checkSystemStatus, 30000);
});

// Add CSS for toast fadeOut
const style = document.createElement('style');
style.textContent = `
    @keyframes fadeOut {
        from { opacity: 1; transform: translateX(0); }
        to { opacity: 0; transform: translateX(20px); }
    }
`;
document.head.appendChild(style);
