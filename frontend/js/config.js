/* =========================================
   config.js
   Shared constants — imported by every module.
   Change API_BASE here and it updates everywhere.
========================================= */

// Auto-switch: local backend when developing (localhost / 127.0.0.1 / file://),
// otherwise the deployed backend. Safe to commit — never ships localhost to prod.
const _isLocal = (
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1" ||
    location.protocol === "file:"
);
const API_BASE       = _isLocal
    ? "http://localhost:8001"
    : "https://bizassist-backend-jgz2.onrender.com";
const DEBUG          = _isLocal;
const DEFAULT_BIZ    = "My Business";

/* Escape untrusted strings before inserting into innerHTML (stored-XSS guard). */
function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
window.escapeHtml = escapeHtml;

// Clear the stored session and return to the login screen.
var _handlingUnauthorized = false;
function forceLogout() {
    if (_handlingUnauthorized) return;
    _handlingUnauthorized = true;
    try {
        localStorage.removeItem("user");
        localStorage.removeItem("admin_user");
        localStorage.removeItem("biz_name");
        localStorage.removeItem("active_session_id");
    } catch (e) {}
    document.documentElement.setAttribute("data-logged", "false");
    location.reload();
}
window.forceLogout = forceLogout;

// Intercept all fetch calls: attach the auth header and handle expired sessions.
const originalFetch = window.fetch;
window.fetch = function (url, options) {
    options = options || {};
    options.headers = options.headers || {};

    var userJson = null;
    try {
        userJson = localStorage.getItem("user") || localStorage.getItem("admin_user");
    } catch (e) {}

    if (userJson) {
        try {
            var user = JSON.parse(userJson);
            if (user && user.token) {
                if (options.headers instanceof Headers) {
                    options.headers.set("Authorization", "Bearer " + user.token);
                } else {
                    options.headers["Authorization"] = "Bearer " + user.token;
                }
            }
        } catch (e) {}
    }

    // Don't auto-logout on login/signup (a wrong password also returns 401).
    var urlStr = (typeof url === "string") ? url : ((url && url.url) || "");
    var isAuthEndpoint = /\/(login|signup)(\?|$)/.test(urlStr);

    return originalFetch(url, options).then(function (response) {
        if (response.status === 401 && !isAuthEndpoint) {
            forceLogout();
        }
        return response;
    });
};