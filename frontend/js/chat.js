/* =========================================
   chat.js
   Handles: AI chat send/receive, textarea
   auto-resize, Enter-to-send, markdown
   rendering, prompt chips.
   Depends on: config.js
========================================= */


/* -----------------------------------------
   HEADER HELPERS — dynamic title
----------------------------------------- */

/* Header always shows biz name + date — never changes to session title */
function setAssistantHeader(title) { /* no-op — header stays as biz name */ }
function resetAssistantHeader()    { /* no-op */ }


/* -----------------------------------------
   TEXTAREA — auto-resize + Enter to send
----------------------------------------- */

const textarea = document.getElementById("user-input");

if (!textarea && DEBUG) console.warn("`#user-input` not found");

textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + "px";

    // Toggle send button active style by adding/removing has-content class
    const inputArea = textarea.closest(".input-area");
    if (inputArea) {
        if (textarea.value.trim().length > 0) {
            inputArea.classList.add("has-content");
        } else {
            inputArea.classList.remove("has-content");
        }
    }

    // Collapse banner on typing, restore when input is empty and chat has no messages
    const currentActive = document.documentElement.getAttribute("data-active");
    if (currentActive === "ai") {
        const isEmptyStatePresent = !!document.getElementById("chat-empty-state");
        if (isEmptyStatePresent) {
            if (textarea.value.trim().length > 0) {
                document.documentElement.classList.add("chat-active");
            } else {
                document.documentElement.classList.remove("chat-active");
            }
        }
    }
});

textarea.addEventListener("keydown", function (e) {

    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});


/* -----------------------------------------
   MARKDOWN RENDERER
   Converts AI markdown output to clean HTML.
   Handles: bold, italic, inline code, code
   blocks, bullet lists, numbered lists,
   headings, horizontal rules, line breaks.
----------------------------------------- */

function renderMarkdown(text) {

    /* Escape raw HTML to prevent injection */
    const escape = s => s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    const lines  = text.split("\n");
    const output = [];
    let inCode   = false;
    let codeLines = [];
    let inList   = false;   /* bullet */
    let inOList  = false;   /* numbered */

    const closeList = () => {
        if (inList)  { output.push("</ul>"); inList  = false; }
        if (inOList) { output.push("</ol>"); inOList = false; }
    };

    for (let i = 0; i < lines.length; i++) {

        const raw  = lines[i];
        const line = raw;

        /* ---- Fenced code block ---- */
        if (line.trimStart().startsWith("```")) {

            if (!inCode) {
                closeList();
                const lang = line.trim().slice(3).trim();
                inCode = true;
                codeLines = [];
                output.push(`<pre class="md-code-block"><code${lang ? ` class="lang-${escape(lang)}"` : ""}>`);
            } else {
                output.push("</code></pre>");
                inCode = false;
            }
            continue;
        }

        if (inCode) {
            output.push(escape(line) + "\n");
            continue;
        }

        /* ---- Blank line ---- */
        if (line.trim() === "") {
            closeList();
            output.push("<br>");
            continue;
        }

        /* ---- Headings ---- */
        const h3 = line.match(/^### (.+)/);
        const h2 = line.match(/^## (.+)/);
        const h1 = line.match(/^# (.+)/);

        if (h3) { closeList(); output.push(`<h3 class="md-h3">${inlineFormat(h3[1])}</h3>`); continue; }
        if (h2) { closeList(); output.push(`<h2 class="md-h2">${inlineFormat(h2[1])}</h2>`); continue; }
        if (h1) { closeList(); output.push(`<h1 class="md-h1">${inlineFormat(h1[1])}</h1>`); continue; }

        /* ---- Horizontal rule ---- */
        if (/^[-*_]{3,}$/.test(line.trim())) {
            closeList();
            output.push("<hr class='md-hr'>");
            continue;
        }

        /* ---- Bullet list (-, *, •) ---- */
        const bullet = line.match(/^[\s]*[-*•]\s+(.+)/);
        if (bullet) {
            if (inOList) { output.push("</ol>"); inOList = false; }
            if (!inList) { output.push("<ul class='md-ul'>"); inList = true; }
            output.push(`<li>${inlineFormat(bullet[1])}</li>`);
            continue;
        }

        /* ---- Numbered list ---- */
        const numbered = line.match(/^[\s]*(\d+)[.)]\s+(.+)/);
        if (numbered) {
            if (inList) { output.push("</ul>"); inList = false; }
            if (!inOList) { output.push("<ol class='md-ol'>"); inOList = true; }
            output.push(`<li>${inlineFormat(numbered[2])}</li>`);
            continue;
        }

        /* ---- Plain paragraph ---- */
        closeList();
        output.push(`<p class="md-p">${inlineFormat(line)}</p>`);
    }

    closeList();
    if (inCode) output.push("</code></pre>");

    return output.join("");
}

/* Inline formatting: bold, italic, inline code, links */
function inlineFormat(text) {

    const escape = s => s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    return escape(text)
        /* Bold+italic */
        .replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>")
        /* Bold */
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/__(.+?)__/g,     "<strong>$1</strong>")
        /* Italic */
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/_(.+?)_/g,   "<em>$1</em>")
        /* Inline code */
        .replace(/`(.+?)`/g, "<code class='md-inline-code'>$1</code>")
        /* ₹ amounts — highlight */
        .replace(/(₹[\d,]+)/g, "<span class='md-rupee'>$1</span>");
}


/* -----------------------------------------
   ACTIVE SESSION STATE
----------------------------------------- */
let activeSessionId = localStorage.getItem("active_session_id") || null;

/* -----------------------------------------
   SEND MESSAGE
----------------------------------------- */

async function sendMessage() {

    const input   = document.getElementById("user-input");
    const chatBox = document.getElementById("chat-box");
    const message = input.value.trim();

    if (!message) return;

    // Start a console trace group for this query lifecycle
    console.group(`%c[BizAssist AI Client] Query: "${message.substring(0, 50)}${message.length > 50 ? '...' : ''}"`, "color: #4caf50; font-weight: bold;");
    console.time("API Latency");

    hideChips();

    /* --- User bubble --- */
    const userRow       = document.createElement("div");
    userRow.className   = "message-row user-row";
    const userDiv       = document.createElement("div");
    userDiv.className   = "message user";
    userDiv.textContent = message;
    userRow.appendChild(userDiv);
    chatBox.appendChild(userRow);

    input.value           = "";
    textarea.style.height = "auto";
    const inputArea = textarea.closest(".input-area");
    if (inputArea) {
        inputArea.classList.remove("has-content");
    }

    /* --- Typing indicator (inside a bot-row) --- */
    const loadingRow     = document.createElement("div");
    loadingRow.className = "message-row bot-row";
    loadingRow.innerHTML = `<div class="bot-avatar">B</div><div class="loading-dots"><div class="typing"><span></span><span></span><span></span></div></div>`;
    const loading        = loadingRow;
    chatBox.appendChild(loadingRow);
    chatBox.scrollTop = chatBox.scrollHeight;

    const isNewSession = !activeSessionId;

    try {
        console.log(`Sending POST request to ${API_BASE}/ask...`);
        const response = await fetch(`${API_BASE}/ask`, {
            method  : "POST",
            headers : { "Content-Type": "application/json" },
            body    : JSON.stringify({ message, session_id: activeSessionId })
        });

        console.timeEnd("API Latency");

        if (!response.ok) throw new Error(`Server Error ${response.status}`);

        const data = await response.json();

        /* ===== CHECK FOR 429 RATE LIMIT ===== */
        if (data.status_code === 429) {
            console.warn("%c[Rate Limit Triggered] API returned 429 status code.", "color: #ff9800; font-weight: bold;", data);
            loading.remove();

            /* --- Rate limit error bubble --- */
            const errorDiv = document.createElement("div");
            errorDiv.className = "message message-error";
            errorDiv.innerHTML = `
                <div style="font-weight: 600; margin-bottom: 8px;">⚠ Rate Limit Exceeded</div>
                <div style="margin-bottom: 8px;">${data.error}</div>
                <div style="font-size: 12px; opacity: 0.85;">Please wait 1-2 minutes before trying again.</div>
            `;
            const errRow = document.createElement("div");
            errRow.className = "message-row bot-row";
            errRow.appendChild(errorDiv);
            chatBox.appendChild(errRow);
            chatBox.scrollTop = chatBox.scrollHeight;

            /* --- Disable input for 2 minutes --- */
            input.disabled = true;
            input.placeholder = "⏳ Rate limited... Please wait 2 minutes";

            /* --- Also disable send button --- */
            const sendBtn = document.querySelector(".input-area .send-btn");
            if (sendBtn) {
                sendBtn.disabled = true;
                sendBtn.style.opacity = "0.5";
                sendBtn.style.cursor = "not-allowed";
            }

            /* --- Auto-re-enable after 2 minutes --- */
            setTimeout(() => {
                input.disabled = false;
                input.placeholder = "Ask me anything...";
                if (sendBtn) {
                    sendBtn.disabled = false;
                    sendBtn.style.opacity = "1";
                    sendBtn.style.cursor = "pointer";
                }
            }, 120000); /* 2 minutes */

            console.groupEnd();
            return;
        }

        // Set session state
        if (data.session_id) {
            activeSessionId = data.session_id;
            localStorage.setItem("active_session_id", activeSessionId);
            loadChatSessions(isNewSession); // refresh sidebar list
        }

        // Update header to show session title
        if (data.session_title) {
            setAssistantHeader(data.session_title);
        }

        const text = data.response || "";
        const source = data.source || "unknown";
        const isCached = !!data.cached;
        
        let pathMsg = "Groq AI Tool-Calling (LLM Tokens Used)";
        if (source === "db") {
            pathMsg = "0 tokens used (Direct DB/Local SQL)";
        } else if (isCached) {
            pathMsg = "0 tokens used (Cached AI Response)";
        }
        
        console.log(`%c[BizAssist Route Decision] Path Chosen: ${isCached ? "CACHE" : source.toUpperCase()} | ${pathMsg}`, "color: #c9532a; font-weight: bold;");
        console.log(`Response length: ${text.length} chars. Beginning streaming render.`);
        console.groupEnd();

        loading.remove();

        /* --- Bot message — avatar + plain text, no name label --- */
        const botRow = document.createElement("div");
        botRow.className = "message-row bot-row";
        botRow.innerHTML = `<div class="bot-avatar">B</div>`;
        const botDiv = document.createElement("div");
        botDiv.className = "message bot";
        botRow.appendChild(botDiv);
        chatBox.appendChild(botRow);

        /* Typewrite the raw text, re-render markdown on each tick.
           This gives the "typing" feel while keeping proper HTML. */
        let i = 0;

        function typeEffect() {

            if (i < text.length) {

                /* Advance by a small chunk each tick for smoother feel */
                const chunk = text.charAt(i);
                i++;

                /* Re-render markdown on the accumulated text so far */
                botDiv.innerHTML = renderMarkdown(text.slice(0, i));

                chatBox.scrollTo({ top: chatBox.scrollHeight, behavior: "smooth" });

                /* Slightly faster on long responses so user isn't waiting */
                const delay = text.length > 500 ? 4 : 8;
                setTimeout(typeEffect, delay);

            }
        }

        typeEffect();

    } catch (error) {
        console.timeEnd("API Latency");
        console.error("%c[BizAssist Network Error] Request failed:", "color: #f44336; font-weight: bold;", error);
        console.groupEnd();

        loading.remove();

        /* --- Error bubble --- */
        const errorDiv = document.createElement("div");
        errorDiv.className = "message message-error";
        errorDiv.textContent = `${error.message} → Error connecting to AI. Please try again.`;
        const errRow2 = document.createElement("div");
        errRow2.className = "message-row bot-row";
        errRow2.appendChild(errorDiv);
        chatBox.appendChild(errRow2);
        chatBox.scrollTop = chatBox.scrollHeight;
    }
}


/* -----------------------------------------
   EMPTY STATE — greeting + chips
----------------------------------------- */

/* Set time-based greeting on load */
(function setGreeting() {
    const el = document.getElementById("ces-greeting");
    if (!el) return;
    const h = new Date().getHours();
    el.textContent =
        h < 12 ? "Good morning" :
        h < 17 ? "Good afternoon" :
                 "Good evening";
})();

function hideChips() {
    const emptyState = document.getElementById("chat-empty-state");
    if (emptyState) {
        document.documentElement.classList.add("chat-active");
        emptyState.style.transition = "opacity 0.25s ease, transform 0.25s ease";
        emptyState.style.opacity   = "0";
        emptyState.style.transform = "translateY(-8px)";
        setTimeout(() => emptyState.remove(), 260);
    }
}

function sendChip(question) {

    const input = document.getElementById("user-input");
    if (!input) return;

    input.value          = question;
    input.style.height   = "auto";
    input.style.height   = input.scrollHeight + "px";

    sendMessage();
}

/* -----------------------------------------
   PERSISTENT HISTORY & MULTI-SESSION
----------------------------------------- */

function removeEmptyStateImmediately() {
    document.documentElement.classList.add("chat-active");
    const emptyState = document.getElementById("chat-empty-state");
    if (emptyState) {
        emptyState.remove();
    }
}

async function loadChatSessions(selectFirstIfNoActive = false) {
    const listContainer = document.getElementById("chat-sessions-list");
    if (!listContainer) return;

    /* Also refresh the right panel chat history */
    if (typeof loadRpChatHistory === "function") loadRpChatHistory();

    try {
        console.log("Loading chat sessions list...");
        const response = await fetch(`${API_BASE}/chat/sessions`);
        if (!response.ok) throw new Error("Failed to load sessions");

        const sessions = await response.json();
        listContainer.innerHTML = "";

        if (sessions.length === 0) {
            startNewChat();
            return;
        }

        sessions.forEach(s => {
            const activeClass = s.session_id === activeSessionId ? "active" : "";
            const sessionDiv = document.createElement("div");
            sessionDiv.className = `rp-chat-item ${activeClass}`;
            sessionDiv.setAttribute("data-session-id", s.session_id);
            sessionDiv.onclick = () => selectChatSession(s.session_id);

            sessionDiv.innerHTML = `
                <div class="rp-chat-title-wrapper">
                    <svg class="rp-chat-icon" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
                    </svg>
                    <span class="rp-chat-title" title="${escapeHtml(s.session_title || 'Untitled')}">${escapeHtml(s.session_title || 'Untitled')}</span>
                </div>
                <button class="rp-chat-delete" onclick="event.stopPropagation(); deleteChatSession(event, '${s.session_id}')" title="Delete conversation">
                    <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="3 6 5 6 21 6"></polyline>
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    </svg>
                </button>
            `;
            listContainer.appendChild(sessionDiv);
        });

        // Set active session selection on load/refresh
        if (selectFirstIfNoActive) {
            // Find if saved activeSessionId exists in returned sessions
            const exists = sessions.some(s => s.session_id === activeSessionId);
            if (exists) {
                selectChatSession(activeSessionId);
            } else {
                selectChatSession(sessions[0].session_id);
            }
        } else if (activeSessionId) {
            // Check if active session still exists
            const exists = sessions.some(s => s.session_id === activeSessionId);
            if (!exists) {
                selectChatSession(sessions[0].session_id);
            } else {
                // Ensure proper active CSS class is maintained
                const items = listContainer.querySelectorAll(".rp-chat-item");
                items.forEach(item => {
                    if (item.getAttribute("data-session-id") === activeSessionId) {
                        item.classList.add("active");
                    } else {
                        item.classList.remove("active");
                    }
                });
            }
        }
    } catch (e) {
        console.error("Error loading chat sessions list:", e);
    }
}

async function selectChatSession(sessionId) {
    if (!sessionId) return;
    activeSessionId = sessionId;
    localStorage.setItem("active_session_id", sessionId);

    // Hide popup after selecting
    const popup = document.getElementById("chat-history-popup");
    if (popup) {
        popup.classList.add("hidden");
    }

    // Update UI active styles in sidebar
    const items = document.querySelectorAll(".rp-chat-item");
    items.forEach(item => {
        if (item.getAttribute("data-session-id") === sessionId) {
            item.classList.add("active");
        } else {
            item.classList.remove("active");
        }
    });

    // Clear chat display and fetch history
    const chatBox = document.getElementById("chat-box");
    if (chatBox) {
        chatBox.innerHTML = "";
    }
    await fetchChatHistory(sessionId);
}

async function fetchChatHistory(sessionId) {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;

    try {
        console.log(`Loading chat history for session_id=${sessionId}...`);
        const response = await fetch(`${API_BASE}/chat/history?session_id=${sessionId}`);
        if (!response.ok) throw new Error("Failed to fetch chat history");
        
        const history = await response.json();
        if (history.length > 0) {
            removeEmptyStateImmediately();

            // Set header to session title from first message
            const sessionTitle = history[0]?.session_title;
            if (sessionTitle) setAssistantHeader(sessionTitle);
            
            history.forEach(m => {
                if (m.role === "user") {
                    const row = document.createElement("div");
                    row.className = "message-row user-row";
                    const div = document.createElement("div");
                    div.className = "message user";
                    div.textContent = m.content;
                    row.appendChild(div);
                    chatBox.appendChild(row);
                } else {
                    const row = document.createElement("div");
                    row.className = "message-row bot-row";
                    row.innerHTML = `<div class="bot-avatar">B</div>`;
                    const div = document.createElement("div");
                    div.className = "message bot";
                    div.innerHTML = renderMarkdown(m.content);
                    row.appendChild(div);
                    chatBox.appendChild(row);
                }
            });
            chatBox.scrollTop = chatBox.scrollHeight;
        } else {
            restoreEmptyState();
        }
    } catch (e) {
        console.error("Error loading chat history:", e);
    }
}

function startNewChat() {
    activeSessionId = null;
    localStorage.removeItem("active_session_id");

    // Remove active styles from sidebar
    const items = document.querySelectorAll(".rp-chat-item");
    items.forEach(item => item.classList.remove("active"));

    // Reset header to default
    resetAssistantHeader();

    // Restore empty welcome screen
    restoreEmptyState();
    console.log("Started a fresh conversation session.");
}

async function deleteChatSession(event, sessionId) {
    event.stopPropagation(); // prevent clicking delete from selecting session

    const confirmed = await showCustomConfirm(
        "Are you sure you want to delete this chat conversation? This cannot be undone.",
        "Delete Conversation"
    );
    if (!confirmed) return;

    try {
        console.log(`Deleting chat session_id=${sessionId}...`);
        const response = await fetch(`${API_BASE}/chat/history?session_id=${sessionId}`, {
            method: "DELETE"
        });
        if (!response.ok) throw new Error("Failed to delete session history");

        console.log("Session history deleted successfully on backend.");
        
        if (activeSessionId === sessionId) {
            activeSessionId = null;
            localStorage.removeItem("active_session_id");
        }

        // Reload lists
        await loadChatSessions(true);
    } catch (e) {
        console.error("Error deleting session history:", e);
        showCustomAlert("Failed to delete conversation: " + e.message, "Error");
    }
}

function restoreEmptyState() {
    const chatBox = document.getElementById("chat-box");
    if (!chatBox) return;

    document.documentElement.classList.remove("chat-active");

    const h = new Date().getHours();
    const greeting =
        h < 12 ? "Good morning" :
        h < 17 ? "Good afternoon" :
                 "Good evening";

    chatBox.innerHTML = `
        <div class="chat-empty-state" id="chat-empty-state">
            <div class="ces-glow"></div>
            <div class="ces-symbol">✦</div>
            <div class="ces-greeting" id="ces-greeting">${greeting}</div>
            <div class="ces-sub">
                Ask anything about your business —<br>
                revenue, stock, payments, customers.
            </div>
            <div class="ces-chips" id="prompt-chips">
                <button class="chip" onclick="sendChip('Who owes me the most?')">💰 Who owes most?</button>
                <button class="chip" onclick="sendChip('Which medicines are expiring soon?')">⏰ Expiring soon</button>
                <button class="chip" onclick="sendChip('Show me the total revenue and pending payments summary')">📊 Revenue summary</button>
                <button class="chip" onclick="sendChip('Which products are low on stock?')">📦 Low stock</button>
                <button class="chip" onclick="sendChip('List all overdue invoices with amounts')">🔴 Overdue invoices</button>
                <button class="chip" onclick="sendChip('Who are my top 5 customers by revenue?')">🏆 Top customers</button>
            </div>
        </div>
    `;
}

// Load sessions list and select default on startup if authenticated
window.addEventListener("DOMContentLoaded", () => {
    if (localStorage.getItem("user")) {
        const active = localStorage.getItem("active_session_id");
        if (active) {
            loadChatSessions(true);
        } else {
            startNewChat();
            loadChatSessions(false);
        }
    }
});

function toggleHistoryPopup() {
    const popup = document.getElementById("chat-history-popup");
    if (!popup) return;
    popup.classList.toggle("hidden");
}

// Close the history popup when clicking outside of it
window.addEventListener("click", (e) => {
    const popup     = document.getElementById("chat-history-popup");
    const toggleBtn = document.querySelector(".history-btn");
    if (popup && !popup.classList.contains("hidden")) {
        if (!popup.contains(e.target) && (!toggleBtn || !toggleBtn.contains(e.target))) {
            popup.classList.add("hidden");
        }
    }
});

async function showFutureVoiceAlert() {
    await showCustomAlert("Voice integration (voice commands and speech readout) is coming in a future update! Stay tuned.", "Voice Assistant");
}