/* =========================================
   config.js
   Shared constants — imported by every module.
   Change API_BASE here and it updates everywhere.
========================================= */

const API_BASE       = "http://localhost:8001";
const DEBUG          = true;
const DEFAULT_BIZ    = "My Business";   // fallback if not set by user

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
