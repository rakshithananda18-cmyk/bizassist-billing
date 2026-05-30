/* =========================================
   chat.js
   Handles: AI chat send/receive, textarea
   auto-resize, Enter-to-send, markdown
   rendering, prompt chips.
   Depends on: config.js
========================================= */


/* -----------------------------------------
   TEXTAREA — auto-resize + Enter to send
----------------------------------------- */

const textarea = document.getElementById("user-input");

if (!textarea && DEBUG) console.warn("`#user-input` not found");

textarea.addEventListener("input", () => {
    textarea.style.height = "auto";
    textarea.style.height = textarea.scrollHeight + "px";
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
   SEND MESSAGE
----------------------------------------- */

async function sendMessage() {

    const input   = document.getElementById("user-input");
    const chatBox = document.getElementById("chat-box");
    const message = input.value.trim();

    if (!message) return;

    hideChips();

    /* --- User bubble --- */
    const userDiv       = document.createElement("div");
    userDiv.className   = "message user";
    userDiv.textContent = message;
    chatBox.appendChild(userDiv);

    input.value           = "";
    textarea.style.height = "auto";

    /* --- Typing indicator --- */
    const loading     = document.createElement("div");
    loading.className = "loading-dots";
    loading.innerHTML = `<div class="typing"><span></span><span></span><span></span></div>`;
    chatBox.appendChild(loading);
    chatBox.scrollTop = chatBox.scrollHeight;

    try {

        const response = await fetch(`${API_BASE}/ask`, {
            method  : "POST",
            headers : { "Content-Type": "application/json" },
            body    : JSON.stringify({ message })
        });

        if (!response.ok) throw new Error(`Server Error ${response.status}`);

        const data = await response.json();

        /* ===== CHECK FOR 429 RATE LIMIT ===== */
        if (data.status_code === 429) {
            loading.remove();

            /* --- Rate limit error bubble --- */
            const errorDiv = document.createElement("div");
            errorDiv.className = "message message-error";
            errorDiv.innerHTML = `
                <div style="font-weight: 600; margin-bottom: 8px;">⚠ Rate Limit Exceeded</div>
                <div style="margin-bottom: 8px;">${data.error}</div>
                <div style="font-size: 12px; opacity: 0.85;">Please wait 1-2 minutes before trying again.</div>
            `;
            chatBox.appendChild(errorDiv);
            chatBox.scrollTop = chatBox.scrollHeight;

            /* --- Disable input for 2 minutes --- */
            input.disabled = true;
            input.placeholder = "⏳ Rate limited... Please wait 2 minutes";

            /* --- Also disable send button --- */
            const sendBtn = document.querySelector(".input-area button");
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

            return;
        }

        const text = data.response || "";

        loading.remove();

        /* --- Bot bubble — render markdown then typewrite --- */
        const botDiv     = document.createElement("div");
        botDiv.className = "message bot";
        chatBox.appendChild(botDiv);

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

        loading.remove();

        /* --- Error bubble --- */
        const errorDiv = document.createElement("div");
        errorDiv.className = "message message-error";
        errorDiv.textContent = `${error.message} → Error connecting to AI. Please try again.`;
        chatBox.appendChild(errorDiv);
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