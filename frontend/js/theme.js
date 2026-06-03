/* =========================================
   theme.js
   Handles: theme switching, sidebar active
   state, layout switching (AI vs Dashboard
   vs Database view).
========================================= */


/* -----------------------------------------
   THEME
----------------------------------------- */

function toggleThemeMenu() {

    const menu = document.getElementById("themeMenu");

    menu.style.display =
        menu.style.display === "block"
            ? "none"
            : "block";
}

function setTheme(theme) {

    localStorage.setItem("theme", theme);

    applyTheme(theme);
}

function applyTheme(theme) {

    document.body.classList.add("theme-animating");

    /* classic is removed — treat as light */
    if (theme === "classic") { theme = "light"; localStorage.setItem("theme", "light"); }

    document.documentElement.classList.remove("dark-mode");

    if (theme === "dark") {

        document.documentElement.classList.add("dark-mode");

    } else if (theme === "system") {

        if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
            document.documentElement.classList.add("dark-mode");
        }
    }

    document.getElementById("themeMenu").style.display = "none";

    setTimeout(() => {
        document.body.classList.remove("theme-animating");
    }, 220);
}

/* Close theme menu when clicking outside it */
window.addEventListener("click", function (e) {

    const dropdown = document.querySelector(".theme-dropdown");

    if (dropdown && !dropdown.contains(e.target)) {
        document.getElementById("themeMenu").style.display = "none";
    }
});


/* -----------------------------------------
   SIDEBAR ACTIVE BUTTON
----------------------------------------- */

function setActiveButton(name) {

    const map = {
        dashboard : "dashboard-btn",
        invoices  : "invoices-btn",
        payments  : "payments-btn",
        clients   : "clients-btn",
        ai        : "ai-btn",
        uploads   : "uploads-btn",
        database  : "db-btn"
    };

    Object.values(map).forEach(id => {
        const b = document.getElementById(id);
        if (b) b.classList.remove("active");
    });

    const active = document.getElementById(map[name]);
    if (active) active.classList.add("active");

    /* Keep html[data-active] in sync so CSS shows the correct state
       immediately without waiting for JS paint */
    try { document.documentElement.setAttribute("data-active", name); } catch (e) {}
}


/* -----------------------------------------
   LAYOUT SWITCHING
----------------------------------------- */

/* Cached panel references — set once DOM is ready */
let dashboardLeft   = null;
let assistantPanel  = null;
let insightsPanel   = null;
let originalLeftDisplay = "";
let originalLeftHTML    = "";

function selectSidebar(name) {

    setActiveButton(name);

    /* Persist so the selection survives page refresh */
    try { localStorage.setItem("selected_sidebar", name); } catch (e) {}

    /* Database view has its own full-panel renderer */
    if (name === "database") {
        openDatabasePanel();
        return;
    }

    if (!dashboardLeft || !assistantPanel || !insightsPanel) return;

    const statCards = document.querySelector(".main > .cards");

    if (name === "ai") {

        /* AI mode: hide stat cards + left panel; chat fills full height */
        if (statCards) statCards.style.display = "none";
        dashboardLeft.style.display = "none";

        assistantPanel.style.gridColumn = "1 / 2";

        insightsPanel.classList.remove("hidden");
        insightsPanel.style.display    = "";
        insightsPanel.style.gridColumn = "2 / 3";

        setBizHeaderRight("AI Assistant");

        /* Populate right panel */
        if (typeof loadInsightsPanel === "function") loadInsightsPanel();
        loadRpChatHistory();

    } else {

        /* All non-AI views: restore panels, call view renderer */
        if (statCards) statCards.style.display = "";

        dashboardLeft.style.display     = (originalLeftDisplay && originalLeftDisplay !== "none") ? originalLeftDisplay : "flex";
        assistantPanel.style.display    = "";
        assistantPanel.style.gridColumn = "2 / 3";

        insightsPanel.classList.add("hidden");
        insightsPanel.style.display = "none";

        /* Update header subtitle */
        const subtitles = {
            dashboard: "Overview",
            invoices:  "Invoices",
            payments:  "Payments",
            clients:   "Clients",
        };
        setBizHeaderRight(subtitles[name] || "");

        /* Route to the correct view renderer */
        try {
            if      (name === "dashboard") renderDashboardView();
            else if (name === "invoices")  renderInvoicesView();
            else if (name === "payments")  renderPaymentsView();
            else if (name === "clients")   renderClientsView();
        } catch (e) {
            if (DEBUG) console.error("View render failed", e);
        }
    }
}


/* -----------------------------------------
   BOOT — runs after DOM is ready
----------------------------------------- */

/* -----------------------------------------
   BUSINESS NAME
----------------------------------------- */

function loadBizName() {
    const stored = localStorage.getItem("biz_name") || DEFAULT_BIZ;
    const el = document.getElementById("biz-name");
    if (el) {
        el.textContent = stored;
    }
    const bannerEl = document.getElementById("ai-biz-banner-name");
    if (bannerEl) {
        bannerEl.textContent = stored;
    }
    updateProfileInitials();
}

function editBizName() {
    const el = document.getElementById("biz-name");
    if (!el) return;

    const current = el.textContent.trim();

    const input = document.createElement("input");
    input.value = current;
    input.style.cssText =
        "font-family:inherit;font-size:inherit;font-weight:inherit;" +
        "letter-spacing:inherit;color:var(--accent-color);background:transparent;" +
        "border:none;border-bottom:1.5px solid var(--accent-color);" +
        "outline:none;width:" + Math.max(current.length * 8, 100) + "px;padding:0;" +
        "max-width:140px";

    el.replaceWith(input);
    input.focus();
    input.select();

    function commit() {
        const val = input.value.trim() || DEFAULT_BIZ;
        localStorage.setItem("biz_name", val);
        const span = document.createElement("span");
        span.id          = "biz-name";
        span.className   = "sidebar-text profile-biz-name-text";
        span.title       = "Click to rename";
        span.textContent = val;
        span.onclick     = (e) => { editBizName(); e.stopPropagation(); };
        input.replaceWith(span);

        const bannerEl = document.getElementById("ai-biz-banner-name");
        if (bannerEl) {
            bannerEl.textContent = val;
        }
        updateProfileInitials();

        // Restore collapsed state if it was collapsed
        const sidebarCollapsed = localStorage.getItem("sidebar_collapsed") === "true";
        const sidebarNav = document.getElementById("sidebar-nav");
        if (sidebarNav && sidebarCollapsed) {
            sidebarNav.classList.add("collapsed");
        }
    }

    input.addEventListener("blur",    commit);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { input.value = current; input.blur(); }
    });
}

function editBannerBizName() {
    const el = document.getElementById("ai-biz-banner-name");
    if (!el) return;

    const current = el.textContent.trim();

    const input = document.createElement("input");
    input.value = current;
    input.style.cssText =
        "font-family:inherit;font-size:inherit;font-weight:inherit;" +
        "letter-spacing:inherit;color:var(--accent-color);background:transparent;" +
        "border:none;border-bottom:2.5px solid var(--accent-color);" +
        "outline:none;text-align:center;width:" + Math.max(current.length * 16, 150) + "px;padding:0;" +
        "max-width:600px";

    el.replaceWith(input);
    input.focus();
    input.select();

    function commit() {
        const val = input.value.trim() || DEFAULT_BIZ;
        localStorage.setItem("biz_name", val);
        const div = document.createElement("div");
        div.id          = "ai-biz-banner-name";
        div.className   = "ai-biz-banner-name";
        div.title       = "Click to rename";
        div.textContent = val;
        div.onclick     = editBannerBizName;
        input.replaceWith(div);

        const sidebarEl = document.getElementById("biz-name");
        if (sidebarEl) {
            sidebarEl.textContent = val;
        }
        updateProfileInitials();
    }

    input.addEventListener("blur",    commit);
    input.addEventListener("keydown", e => {
        if (e.key === "Enter")  { e.preventDefault(); input.blur(); }
        if (e.key === "Escape") { input.value = current; input.blur(); }
    });
}

function loadBizDate() {
    const el = document.getElementById("ai-biz-banner-date");
    if (el) {
        const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
        const today = new Date();
        el.textContent = today.toLocaleDateString('en-US', options);
    }
}

function setBizHeaderRight(content) {
    const el = document.getElementById("biz-header-right");
    if (el) el.innerHTML = content;
}


window.addEventListener("DOMContentLoaded", () => {

    /* Resolve panel refs */
    dashboardLeft  = document.getElementById("dashboard-left");
    assistantPanel = document.getElementById("assistant-panel");
    insightsPanel  = document.getElementById("insights-panel");

    if (dashboardLeft) {
        originalLeftDisplay = getComputedStyle(dashboardLeft).display;
        originalLeftHTML    = dashboardLeft.innerHTML;
    }

    /* Load business name */
    loadBizName();
    loadBizDate();

    /* Apply saved sidebar collapse state */
    const sidebarCollapsed = localStorage.getItem("sidebar_collapsed") === "true";
    const sidebarNav = document.getElementById("sidebar-nav");
    if (sidebarNav && sidebarCollapsed) {
        sidebarNav.classList.add("collapsed");
    }

    /* Apply saved insights collapse state */
    const insightsCollapsed = localStorage.getItem("insights_collapsed") === "true";
    if (insightsPanel && insightsCollapsed) {
        insightsPanel.classList.add("collapsed");
        const grid = insightsPanel.parentElement;
        if (grid && grid.classList.contains("dashboard-grid")) {
            grid.classList.add("insights-collapsed");
        }
    }

    /* Restore right-panel section collapse states */
    ["progress", "context"].forEach(name => {
        if (localStorage.getItem(`rp_section_${name}`) === "collapsed") {
            const section = document.getElementById(`rp-section-${name}`);
            if (section) section.classList.add("collapsed");
        }
    });

    /* Apply saved theme */
    const savedTheme = localStorage.getItem("theme") || "system";
    applyTheme(savedTheme);

    /* Remove preload class so layout becomes visible */
    document.body.classList.remove("preload");

    let saved = null;
    try { saved = localStorage.getItem("selected_sidebar"); } catch (e) {}

    if (!saved) {
        saved = "ai";
        try { localStorage.setItem("selected_sidebar", "ai"); } catch (e) {}
    }

    if (localStorage.getItem("user")) {
        selectSidebar(saved);
    } else {
        setActiveButton(saved);
    }

    /* Password dynamic validation event binding (1s debounce) */
    let validationTimeout = null;
    const passwordInput = document.getElementById("password");
    if (passwordInput) {
        passwordInput.addEventListener("input", (e) => {
            const val = e.target.value;
            
            // Clear pending timeout
            if (validationTimeout) {
                clearTimeout(validationTimeout);
            }
            
            // Hide the checklist container instantly while typing
            const passwordConditions = document.getElementById("password-conditions");
            if (passwordConditions) {
                passwordConditions.style.display = "none";
            }
            
            // Wait for 1 second of inactivity before evaluating and showing unmet rules
            validationTimeout = setTimeout(() => {
                validatePasswordConditions(val);
            }, 1000);
        });
    }
});

/* -----------------------------------------
   USER AUTHENTICATION
----------------------------------------- */
let authMode = "login";

const EYE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="eye-icon"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>`;
const EYE_OFF_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="eye-icon"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>`;

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    const wrapper = input.parentElement;
    const button = wrapper ? wrapper.querySelector('.password-toggle-btn') : null;
    if (!button) return;

    if (input.type === "password") {
        input.type = "text";
        button.innerHTML = EYE_OFF_SVG;
    } else {
        input.type = "password";
        button.innerHTML = EYE_SVG;
    }
}

function validatePasswordConditions(value) {
    const condLength = document.getElementById("cond-length");
    const condCapital = document.getElementById("cond-capital");
    const condLowercase = document.getElementById("cond-lowercase");
    const condNumber = document.getElementById("cond-number");
    const condSpecial = document.getElementById("cond-special");
    const passwordConditions = document.getElementById("password-conditions");

    const hasLength = value.length >= 8;
    const hasCapital = /[A-Z]/.test(value);
    const hasLowercase = /[a-z]/.test(value);
    const hasNumber = /\d/.test(value);
    const hasSpecial = /[^A-Za-z0-9]/.test(value);

    const toggleClass = (el, isValid) => {
        if (!el) return;
        if (isValid) {
            el.classList.add("valid");
        } else {
            el.classList.remove("valid");
        }
    };

    toggleClass(condLength, hasLength);
    toggleClass(condCapital, hasCapital);
    toggleClass(condLowercase, hasLowercase);
    toggleClass(condNumber, hasNumber);
    toggleClass(condSpecial, hasSpecial);

    const allValid = hasLength && hasCapital && hasLowercase && hasNumber && hasSpecial;

    if (passwordConditions) {
        if (allValid || value === "") {
            passwordConditions.style.display = "none";
        } else if (authMode === "signup") {
            passwordConditions.style.display = "flex";
        }
    }

    return allValid;
}

function switchLoginTab(mode) {
    authMode = mode;
    const tabLogin = document.getElementById("tab-login");
    const tabSignup = document.getElementById("tab-signup");
    const groupBizname = document.getElementById("group-bizname");
    const submitBtn = document.getElementById("submit-btn");
    const errEl = document.getElementById("login-error");
    const passwordConditions = document.getElementById("password-conditions");

    if (errEl) errEl.style.display = "none";

    if (mode === "login") {
        tabLogin.classList.add("active");
        tabSignup.classList.remove("active");
        if (groupBizname) groupBizname.style.display = "none";
        if (submitBtn) submitBtn.textContent = "Sign In";
        if (passwordConditions) passwordConditions.style.display = "none";
    } else {
        tabLogin.classList.remove("active");
        tabSignup.classList.add("active");
        if (groupBizname) groupBizname.style.display = "flex";
        if (submitBtn) submitBtn.textContent = "Register";
        if (passwordConditions) {
            passwordConditions.style.display = "none"; // Hide initially on register tab switch
        }
    }
}

async function handleAuthSubmit(e) {
    e.preventDefault();
    const uInput = document.getElementById("username");
    const pInput = document.getElementById("password");
    const bInput = document.getElementById("bizname");
    const errEl = document.getElementById("login-error");

    const username = uInput ? uInput.value.trim() : "";
    const password = pInput ? pInput.value.trim() : "";
    const bizname = bInput ? bInput.value.trim() : "";

    if (errEl) errEl.style.display = "none";

    if (authMode === "signup") {
        if (!bizname) {
            if (errEl) {
                errEl.textContent = "Business name is required for registration.";
                errEl.style.display = "block";
            }
            return;
        }

        // Validate password strength conditions
        const isPasswordValid = validatePasswordConditions(password);
        if (!isPasswordValid) {
            if (errEl) {
                errEl.textContent = "Password must meet all security conditions (Length, Capital, Lowercase, Number, Special).";
                errEl.style.display = "block";
            }
            return;
        }
    }

    try {
        const url = authMode === "login" ? `${API_BASE}/login` : `${API_BASE}/signup`;
        const body = authMode === "login" 
            ? { username, password } 
            : { username, password, business_name: bizname };

        const res = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.detail || "Authentication failed");
        }

        const user = await res.json();
        
        // Save session
        localStorage.setItem("user", JSON.stringify(user));
        localStorage.setItem("biz_name", user.business_name);
        localStorage.removeItem("active_session_id"); // Reset active session for new user
        document.documentElement.setAttribute("data-logged", "true");

        // Clear forms
        if (uInput) uInput.value = "";
        if (pInput) pInput.value = "";
        if (bInput) bInput.value = "";

        // Reload names and dashboard views
        loadBizName();
        loadBizDate();
        
        if (typeof loadDashboardSummary === "function") loadDashboardSummary();
        if (typeof loadTopCustomers === "function") loadTopCustomers();
        if (typeof startNewChat === "function") {
            startNewChat(); // Start with a fresh/new conversation state
        }
        if (typeof loadChatSessions === "function") {
            loadChatSessions(false); // Load chat sessions list without auto-selecting
        }
        
        localStorage.setItem("selected_sidebar", "ai");
        selectSidebar("ai");

    } catch (err) {
        if (errEl) {
            errEl.textContent = err.message || "Connection to authentication server failed.";
            errEl.style.display = "block";
        }
    }
}

function logout() {
    localStorage.removeItem("user");
    localStorage.removeItem("biz_name");
    localStorage.removeItem("active_session_id");
    localStorage.setItem("selected_sidebar", "ai");
    document.documentElement.setAttribute("data-logged", "false");
    
    // Reset view
    location.reload();
}

/* -----------------------------------------
   REUSABLE LOADING INDICATOR
   Disables a button/element and inserts a spinner
----------------------------------------- */
function setElementLoading(element, isLoading, loadingText = "") {
    if (!element) return;
    
    if (isLoading) {
        if (element.classList.contains("loading-active")) return;
        
        element.dataset.originalHtml = element.innerHTML;
        element.disabled = true;
        element.classList.add("loading-active");
        
        const spinner = `<span class="loading-spinner"></span>`;
        if (loadingText) {
            element.innerHTML = `${spinner}<span>${loadingText}</span>`;
        } else {
            const text = element.innerText || 'Loading...';
            element.innerHTML = `${spinner}<span>${text}</span>`;
        }
    } else {
        if (element.dataset.originalHtml !== undefined) {
            element.innerHTML = element.dataset.originalHtml;
            delete element.dataset.originalHtml;
        }
        element.disabled = false;
        element.classList.remove("loading-active");
    }
}

/* -----------------------------------------
   CUSTOM ALERT / CONFIRM SYSTEM
   Returns promises to allow async/await usage
----------------------------------------- */
async function showCustomAlert(message, title = "Notification") {
    return new Promise((resolve) => {
        const modal = document.createElement("div");
        modal.className = "custom-modal-overlay";
        modal.innerHTML = `
            <div class="custom-modal-card">
                <div class="custom-modal-title">${title}</div>
                <div class="custom-modal-body">${message.replace(/\n/g, "<br>")}</div>
                <div class="custom-modal-actions">
                    <button class="custom-modal-btn confirm-btn">OK</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        const confirmBtn = modal.querySelector(".confirm-btn");
        confirmBtn.addEventListener("click", () => {
            modal.remove();
            resolve(true);
        });
        
        // Auto-focus OK button so hitting space/enter works naturally
        setTimeout(() => confirmBtn.focus(), 50);
    });
}

async function showCustomConfirm(message, title = "Confirm Action") {
    return new Promise((resolve) => {
        const modal = document.createElement("div");
        modal.className = "custom-modal-overlay";
        modal.innerHTML = `
            <div class="custom-modal-card">
                <div class="custom-modal-title">${title}</div>
                <div class="custom-modal-body">${message.replace(/\n/g, "<br>")}</div>
                <div class="custom-modal-actions">
                    <button class="custom-modal-btn cancel-btn">Cancel</button>
                    <button class="custom-modal-btn confirm-btn">Confirm</button>
                </div>
            </div>
        `;
        document.body.appendChild(modal);

        const cancelBtn = modal.querySelector(".cancel-btn");
        const confirmBtn = modal.querySelector(".confirm-btn");

        cancelBtn.addEventListener("click", () => {
            modal.remove();
            resolve(false);
        });

        confirmBtn.addEventListener("click", () => {
            modal.remove();
            resolve(true);
        });

        // Auto-focus confirm button
        setTimeout(() => confirmBtn.focus(), 50);
    });
}

// ── SIDEBAR TOGGLE & FOOTER LOGIC ────────────────────────────────────

function toggleSidebarCollapse() {
    const sidebar = document.getElementById("sidebar-nav");
    if (!sidebar) return;
    sidebar.classList.toggle("collapsed");
    const isCollapsed = sidebar.classList.contains("collapsed");
    localStorage.setItem("sidebar_collapsed", isCollapsed);
}

function updateProfileInitials() {
    const stored = localStorage.getItem("biz_name") || DEFAULT_BIZ;
    const initial = stored.charAt(0).toUpperCase();
    const initialsBadge = document.getElementById("profile-badge-initials");
    if (initialsBadge) {
        initialsBadge.textContent = initial;
    }
    const menuBiz = document.getElementById("profile-menu-biz-name");
    if (menuBiz) {
        menuBiz.textContent = stored;
    }
}

function toggleProfileMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById("profileMenu");
    if (!menu) return;
    const currentDisplay = menu.style.display;
    
    // Close other dropdowns
    const themeMenu = document.getElementById("themeMenu");
    if (themeMenu) themeMenu.style.display = "none";
    
    if (currentDisplay === "block") {
        menu.style.display = "none";
    } else {
        menu.style.display = "block";
    }
}

function editBizNameFromMenu(event) {
    event.stopPropagation();
    const menu = document.getElementById("profileMenu");
    if (menu) menu.style.display = "none";
    
    const sidebarNav = document.getElementById("sidebar-nav");
    if (sidebarNav && sidebarNav.classList.contains("collapsed")) {
        sidebarNav.classList.remove("collapsed");
    }
    
    // Trigger rename on the sidebar footer name element
    editBizName();
}

// Global click handler to close dropdowns when clicking outside
window.addEventListener("click", (e) => {
    const profileMenu = document.getElementById("profileMenu");
    if (profileMenu && profileMenu.style.display === "block") {
        const wrap = document.querySelector(".profile-badge-wrap");
        if (wrap && !wrap.contains(e.target)) {
            profileMenu.style.display = "none";
        }
    }
});

// ── INSIGHTS PANEL COLLAPSE LOGIC ────────────────────────────────────
function toggleInsightsCollapse() {
    const panel = document.getElementById("insights-panel");
    if (!panel) return;
    panel.classList.toggle("collapsed");

    const grid = panel.parentElement;
    if (grid && grid.classList.contains("dashboard-grid")) {
        grid.classList.toggle("insights-collapsed");
    }

    const isCollapsed = panel.classList.contains("collapsed");
    localStorage.setItem("insights_collapsed", isCollapsed);
}

// ── RIGHT PANEL SECTION COLLAPSE ─────────────────────────────────────
function toggleRpSection(name) {
    const section = document.getElementById(`rp-section-${name}`);
    if (!section) return;
    section.classList.toggle("collapsed");
    const isCollapsed = section.classList.contains("collapsed");
    try { localStorage.setItem(`rp_section_${name}`, isCollapsed ? "collapsed" : "open"); } catch(e) {}
}

// ── RIGHT PANEL CHAT HISTORY ─────────────────────────────────────────
async function loadRpChatHistory() {
    const container = document.getElementById("rp-chat-sessions-list");
    const navLabel  = document.getElementById("rp-nav-label");
    if (!container) return;

    try {
        const user = localStorage.getItem("user");
        if (!user) { container.innerHTML = `<div class="rp-empty">Sign in to see history</div>`; return; }

        const res      = await fetch(`${typeof API_BASE !== "undefined" ? API_BASE : "http://localhost:8001"}/chat/sessions`);
        if (!res.ok) throw new Error("Failed");
        const sessions = await res.json();

        if (navLabel) navLabel.textContent = `${sessions.length} chat${sessions.length !== 1 ? "s" : ""}`;

        if (sessions.length === 0) {
            container.innerHTML = `<div class="rp-empty">No conversations yet</div>`;
            return;
        }

        const curSession = typeof activeSessionId !== "undefined" ? activeSessionId : "";
        container.innerHTML = sessions.map(s => `
            <div class="rp-chat-item ${s.session_id === curSession ? "active" : ""}"
                 data-session-id="${s.session_id}"
                 onclick="selectChatSession && selectChatSession('${s.session_id}')">
                <div class="rp-chat-title-wrapper">
                    <svg class="rp-chat-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <span class="rp-chat-title" title="${s.session_title || 'Untitled'}">${s.session_title || "Untitled"}</span>
                </div>
                <button class="rp-chat-delete" onclick="event.stopPropagation(); deleteChatSession && deleteChatSession(event, '${s.session_id}')" title="Delete conversation">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            </div>
        `).join("");
    } catch (e) {
        container.innerHTML = `<div class="rp-empty">Could not load history</div>`;
    }
}