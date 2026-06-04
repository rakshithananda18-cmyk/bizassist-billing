/* =========================================
   config.js
   Shared constants — imported by every module.
   Change API_BASE here and it updates everywhere.
========================================= */

// Auto-switch: use the local backend when developing (localhost / 127.0.0.1 /
// opening index.html as a file), otherwise the deployed backend. This keeps the
// file safe to commit without shipping a localhost URL to production.
const _isLocal = (
    location.hostname === "localhost" ||
    location.hostname === "127.0.0.1" ||
    location.protocol === "file:"
);
const API_BASE       = _isLocal
    ? "http://localhost:8001"
    : "https://bizassist-backend-jgz2.onrender.com";
const DEBUG          = _isLocal;
const DEFAULT_BIZ    = "My Business";   // fallback if not set by user

/* Escape untrusted strings before inserting into innerHTML, to prevent
   stored XSS from uploaded data (customer/product/supplier names, chat
   content, session titles, etc.). Use on ANY value that originates from
   user input or the database. */
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

// Intercept all fetch calls to automatically append Authorization header
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
    return originalFetch(url, options);
};
