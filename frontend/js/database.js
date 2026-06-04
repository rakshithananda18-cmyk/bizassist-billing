/* =========================================
   database.js
   Handles: Database Viewer panel rendering,
   pagination state, renderInsights helper.
   Depends on: config.js, theme.js
   (uses dashboardLeft, assistantPanel,
    insightsPanel, setActiveButton from theme.js)
========================================= */


/* -----------------------------------------
   PAGINATION STATE
----------------------------------------- */

let currentDatabaseData = null;

let currentPage = {
    uploads        : 1,
    folder_uploads : 1,
    invoices       : 1,
    inventory      : 1,
    payments       : 1,
    chat           : 1
};

const itemsPerPage = 7;

function changePage(tableId, newPage) {

    if (newPage < 1) return;

    console.log(`%c[BizAssist DB Pagination] Table: ${tableId} | Navigating to Page ${newPage}`, "color: #9c27b0;");
    currentPage[tableId] = newPage;

    if (tableId === "uploads") {
        renderMainUploadsTable();
    } else if (tableId === "folder_uploads") {
        renderFolderUploadsTable();
    } else if (tableId === "invoices") {
        renderFolderInvoicesTable();
    } else if (tableId === "inventory") {
        renderFolderInventoryTable();
    } else if (tableId === "payments") {
        renderFolderPaymentsTable();
    } else if (tableId === "chat") {
        renderFolderChatTable();
    }
}


/* -----------------------------------------
   PAGINATION CONTROLS  (reusable helper)
   ----------------------------------------- */

function paginationControls(tableId, total, page, limit = 7) {

    const totalPages = Math.ceil(total / limit);

    if (totalPages <= 1) return "";

    const btnStyle =
        "padding:6px 12px;border-radius:6px;cursor:pointer;" +
        "border:1px solid var(--border-subtle,rgba(212,176,140,0.2));background:transparent;color:inherit";

    return `
        <div style="margin-top:12px;display:flex;gap:8px;justify-content:center;align-items:center">
            <button
                onclick="changePage('${tableId}', ${page - 1})"
                ${page === 1 ? "disabled" : ""}
                style="${btnStyle}"
            >← Prev</button>

            <span style="padding:6px 12px;font-size:12px">
                Page ${page} / ${totalPages}
            </span>

            <button
                onclick="changePage('${tableId}', ${page + 1})"
                ${page >= totalPages ? "disabled" : ""}
                style="${btnStyle}"
            >Next →</button>
        </div>
    `;
}


/* -----------------------------------------
   DATABASE PANEL
   ----------------------------------------- */

async function openDatabasePanel() {

    setActiveButton("database");

    if (!dashboardLeft) {
        dashboardLeft = document.getElementById("dashboard-left");
    }
    if (!dashboardLeft) return;

    console.group(`%c[BizAssist DB Viewer] Fetching table page states...`, "color: #2196f3; font-weight: bold;");
    console.log("Current page parameters:", currentPage);

    /* Show loading skeleton immediately to clear static index.html content */
    dashboardLeft.innerHTML = `
        <div class="vheader" style="margin-bottom:16px">
            <div>
                <div class="vheader-title">Business Database</div>
                <div class="vheader-sub">View and manage uploaded files and records</div>
            </div>
        </div>
        <div class="widget">${typeof skeleton === "function" ? skeleton(4) : '<div class="vskel"></div>'}</div>
    `;

    const refreshBtn = document.querySelector('button[onclick="openDatabasePanel()"]');
    if (typeof setElementLoading === "function" && refreshBtn) {
        setElementLoading(refreshBtn, true, "Refreshing...");
    }

    try {

        const response = await fetch(`${API_BASE}/database`);
        const data     = await response.json();

        console.log("Database metadata loaded successfully. Row counts: Invoices =", data.invoice_count, ", Inventory =", data.inventory_count, ", Uploads =", data.upload_count);
        console.groupEnd();

        currentDatabaseData = data;
        currentPage = {
            uploads        : 1,
            folder_uploads : 1,
            invoices       : 1,
            inventory      : 1,
            payments       : 1,
            chat           : 1
        };

        /* Layout: show left panel, push assistant to right, hide insights */
        dashboardLeft.style.display     = "flex";
        if (assistantPanel) {
            assistantPanel.style.display    = "";
            assistantPanel.style.gridColumn = "2 / 3";
        }
        if (insightsPanel) {
            insightsPanel.classList.add("hidden");
            insightsPanel.style.display     = "none";
        }

        const isDbEmpty = (data.uploads || []).length === 0 && 
                          (data.invoices || []).length === 0 && 
                          (data.inventory || []).length === 0;

        if (isDbEmpty) {
            dashboardLeft.innerHTML = `
                <div class="vheader" style="margin-bottom:16px">
                    <div>
                        <div class="vheader-title">Business Database</div>
                        <div class="vheader-sub">View and manage uploaded files and records</div>
                    </div>
                </div>
                ${typeof emptyState === "function" 
                  ? emptyState('🗄', 'Database is empty', 'Upload CSV/XLSX billing files to populate the database.')
                  : '<div style="text-align:center;padding:40px;">Database is empty. Please upload data.</div>'}
            `;
            return;
        }

        // Calculate session count for folders layout summary
        const chatHistoryList = data.chat_history || [];
        const sessions = {};
        chatHistoryList.forEach(m => {
            const sid = m.session_id || 'default';
            if (!sessions[sid]) {
                sessions[sid] = {
                    title: m.session_title || 'Previous Chat Session',
                    messages: []
                };
            }
            sessions[sid].messages.push(m);
        });
        const sessionKeys = Object.keys(sessions);

        /* --- Assemble full panel template with content placeholders --- */
        dashboardLeft.innerHTML = `

            <!-- OVERVIEW CARDS -->
            <div class="widget">

                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">

                    <div class="widget-title" style="margin:0">
                        Database Overview
                    </div>

                    <div style="display:flex;gap:8px;align-items:center">
                        <button
                            class="upload-btn-highlight"
                            onclick="document.getElementById('file-upload-db').click()"
                            style="padding:8px 12px;border-radius:8px;
                                   cursor:pointer;font-size:12px;font-weight:600;display:flex;align-items:center;gap:6px"
                        >
                            <span style="font-size:13px;font-weight:bold">↑</span> Upload Data
                        </button>
                        <input type="file" id="file-upload-db" accept=".csv,.xlsx,.pdf" hidden>

                        <button
                            onclick="openDatabasePanel()"
                            style="padding:8px 12px;border:1px solid var(--border-color);border-radius:8px;
                                   background:var(--card-color);color:var(--text-color);cursor:pointer;font-size:12px;
                                   font-weight:600"
                        >↻ Refresh</button>

                        <button
                            onclick="showDeleteDatabaseModal()"
                            style="padding:8px 12px;border:none;border-radius:8px;
                                   background:rgba(201,66,66,0.15);color:#c94242;cursor:pointer;font-size:12px;
                                   font-weight:600"
                            title="Delete entire database (cannot be undone)"
                        >🗑 Delete All</button>
                    </div>

                </div>

                <div class="cards db-cards">

                    <div class="card">
                        <h3>Invoices</h3>
                        <p>${data.invoice_count}</p>
                    </div>

                    <div class="card">
                        <h3>Inventory</h3>
                        <p>${data.inventory_count}</p>
                    </div>

                    <div class="card">
                        <h3>Uploads</h3>
                        <p>${data.upload_count}</p>
                    </div>

                </div>

            </div>

            <!-- UPLOADED FILES -->
            <div class="widget">

                <div class="widget-title">Uploaded Files</div>

                <div id="main-uploads-container" class="database-table">
                    <!-- Loaded dynamically -->
                </div>

            </div>

            <!-- DATABASE EXPLORER -->
            <div class="widget">
                <div class="widget-title" style="margin-bottom: 16px">Database Explorer</div>
                <div style="display: flex; flex-direction: column; gap: 16px">
                    <details class="tree-node">
                        <summary class="tree-summary">Uploaded Datasets (${(data.uploads || []).length})</summary>
                        <div class="tree-content" id="folder-uploads-container"></div>
                    </details>
                    <details class="tree-node">
                        <summary class="tree-summary">Invoices & Sales (${(data.invoices || []).length})</summary>
                        <div class="tree-content" id="folder-invoices-container"></div>
                    </details>
                    <details class="tree-node">
                        <summary class="tree-summary">Inventory Stock (${(data.inventory || []).length} items)</summary>
                        <div class="tree-content" id="folder-inventory-container"></div>
                    </details>
                    <details class="tree-node">
                        <summary class="tree-summary">Logged Payments & Dues (${(data.payments || []).length})</summary>
                        <div class="tree-content" id="folder-payments-container"></div>
                    </details>
                    <details class="tree-node">
                        <summary class="tree-summary">Chat Threads History (${sessionKeys.length} sessions)</summary>
                        <div class="tree-content" id="folder-chat-container"></div>
                    </details>
                </div>
            </div>

        `;

        // Render subcomponents initially
        renderMainUploadsTable();
        renderFolderUploadsTable();
        renderFolderInvoicesTable();
        renderFolderInventoryTable();
        renderFolderPaymentsTable();
        renderFolderChatTable();

    } catch (error) {

        console.error("%c[BizAssist DB Viewer] Failed to retrieve database metadata:", "color: #f44336; font-weight: bold;", error);
        console.groupEnd();
        await showCustomAlert("Failed to load database", "Error");
    } finally {
        const refreshBtnLive = document.querySelector('button[onclick="openDatabasePanel()"]');
        if (typeof setElementLoading === "function" && refreshBtnLive) {
            setElementLoading(refreshBtnLive, false);
        }
    }
}


/* -----------------------------------------
   SUB-COMPONENT RENDERING FUNCTIONS
   ----------------------------------------- */

function renderMainUploadsTable() {
    const container = document.getElementById("main-uploads-container");
    if (!container || !currentDatabaseData) return;

    const uploadsList = currentDatabaseData.uploads || [];
    const page = currentPage.uploads || 1;
    const limit = 7;
    const sliced = uploadsList.slice((page - 1) * limit, page * limit);

    const rows = sliced.map(file => `
        <tr>
            <td>${escapeHtml(file.filename)}</td>
            <td>${file.type}</td>
            <td>${file.rows}</td>
            <td>${file.uploaded}</td>
            <td>
                <button
                    class="delete-btn-small"
                    onclick="deleteUpload(${file.id})"
                    title="Delete file"
                >✕ Delete</button>
            </td>
        </tr>
    `).join("");

    container.innerHTML = `
        <table>
            <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Rows</th>
                <th>Uploaded</th>
                <th>Action</th>
            </tr>
            ${rows}
        </table>
        ${paginationControls("uploads", uploadsList.length, page, limit)}
    `;
}

function renderFolderUploadsTable() {
    const container = document.getElementById("folder-uploads-container");
    if (!container || !currentDatabaseData) return;

    const uploadsList = currentDatabaseData.uploads || [];
    const page = currentPage.folder_uploads || 1;
    const limit = 7;
    const sliced = uploadsList.slice((page - 1) * limit, page * limit);

    let html = '';
    if (uploadsList.length === 0) {
        html = '<div style="color:var(--secondary-text);padding:10px 0;">No datasets uploaded.</div>';
    } else {
        html = `
            <table class="tree-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Filename</th>
                        <th>Type</th>
                        <th>Row Count</th>
                        <th>Uploaded Time</th>
                    </tr>
                </thead>
                <tbody>
                    ${sliced.map(u => `
                        <tr>
                            <td style="font-family:monospace;">${u.id}</td>
                            <td style="font-weight:600;color:var(--accent-color);">${escapeHtml(u.filename)}</td>
                            <td><span class="tag">${u.file_type || u.type}</span></td>
                            <td>${u.rows_count || u.rows} rows</td>
                            <td>${u.upload_time || u.uploaded}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            ${paginationControls("folder_uploads", uploadsList.length, page, limit)}
        `;
    }
    container.innerHTML = html;
}

function renderFolderInvoicesTable() {
    const container = document.getElementById("folder-invoices-container");
    if (!container || !currentDatabaseData) return;

    const invoicesList = currentDatabaseData.invoices || [];
    const page = currentPage.invoices || 1;
    const limit = 7;
    const sliced = invoicesList.slice((page - 1) * limit, page * limit);

    let html = '';
    if (invoicesList.length === 0) {
        html = '<div style="color:var(--secondary-text);padding:10px 0;">No invoices present.</div>';
    } else {
        html = `
            <table class="tree-table">
                <thead>
                    <tr>
                        <th>Invoice ID</th>
                        <th>Customer</th>
                        <th>Product</th>
                        <th>Amount</th>
                        <th>Status</th>
                        <th>Due Date</th>
                    </tr>
                </thead>
                <tbody>
                    ${sliced.map(inv => `
                        <tr>
                            <td style="font-family:monospace;">${escapeHtml(inv.invoice_id || 'N/A')}</td>
                            <td style="font-weight:500;">${escapeHtml(inv.customer)}</td>
                            <td>${escapeHtml(inv.product || 'N/A')}</td>
                            <td style="font-weight:600;">₹${(inv.amount || 0).toLocaleString('en-IN')}</td>
                            <td><span class="tag" style="background:${inv.status === 'Paid' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)'};color:${inv.status === 'Paid' ? '#3a9a5c' : 'var(--accent-color)'}">${escapeHtml(inv.status)}</span></td>
                            <td>${inv.due_date || 'N/A'}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            ${paginationControls("invoices", invoicesList.length, page, limit)}
        `;
    }
    container.innerHTML = html;
}

function renderFolderInventoryTable() {
    const container = document.getElementById("folder-inventory-container");
    if (!container || !currentDatabaseData) return;

    const inventoryList = currentDatabaseData.inventory || [];
    const page = currentPage.inventory || 1;
    const limit = 7;
    const sliced = inventoryList.slice((page - 1) * limit, page * limit);

    let html = '';
    if (inventoryList.length === 0) {
        html = '<div style="color:var(--secondary-text);padding:10px 0;">No inventory records.</div>';
    } else {
        html = `
            <table class="tree-table">
                <thead>
                    <tr>
                        <th>Product Name</th>
                        <th>Stock</th>
                        <th>Expiry Date</th>
                        <th>Supplier</th>
                    </tr>
                </thead>
                <tbody>
                    ${sliced.map(item => `
                        <tr>
                            <td style="font-weight:600;color:var(--accent-color);">${escapeHtml(item.product_name || item.product)}</td>
                            <td>${item.stock} items</td>
                            <td>${item.expiry_date || item.expiry || 'N/A'}</td>
                            <td>${escapeHtml(item.supplier || 'N/A')}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            ${paginationControls("inventory", inventoryList.length, page, limit)}
        `;
    }
    container.innerHTML = html;
}

function renderFolderPaymentsTable() {
    const container = document.getElementById("folder-payments-container");
    if (!container || !currentDatabaseData) return;

    const paymentsList = currentDatabaseData.payments || [];
    const page = currentPage.payments || 1;
    const limit = 7;
    const sliced = paymentsList.slice((page - 1) * limit, page * limit);

    let html = '';
    if (paymentsList.length === 0) {
        html = '<div style="color:var(--secondary-text);padding:10px 0;">No payment entries.</div>';
    } else {
        html = `
            <table class="tree-table">
                <thead>
                    <tr>
                        <th>Customer</th>
                        <th>Amount</th>
                        <th>Due Date</th>
                        <th>Paid Status</th>
                    </tr>
                </thead>
                <tbody>
                    ${sliced.map(p => `
                        <tr>
                            <td style="font-weight:500;">${escapeHtml(p.customer)}</td>
                            <td style="font-weight:600;">₹${(p.amount || 0).toLocaleString('en-IN')}</td>
                            <td>${p.due_date || 'N/A'}</td>
                            <td><span class="tag" style="background:${p.paid === 'Yes' ? 'rgba(58,154,92,0.12)' : 'rgba(201,100,66,0.12)'};color:${p.paid === 'Yes' ? '#3a9a5c' : 'var(--accent-color)'}">${p.paid === 'Yes' ? 'Paid' : 'Unpaid'}</span></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
            ${paginationControls("payments", paymentsList.length, page, limit)}
        `;
    }
    container.innerHTML = html;
}

function renderFolderChatTable() {
    const container = document.getElementById("folder-chat-container");
    if (!container || !currentDatabaseData) return;

    const chatHistoryList = currentDatabaseData.chat_history || [];
    const sessions = {};
    chatHistoryList.forEach(m => {
        const sid = m.session_id || 'default';
        if (!sessions[sid]) {
            sessions[sid] = {
                title: m.session_title || 'Previous Chat Session',
                messages: []
            };
        }
        sessions[sid].messages.push(m);
    });
    const sessionKeys = Object.keys(sessions);

    const page = currentPage.chat || 1;
    const limit = 7;
    const slicedKeys = sessionKeys.slice((page - 1) * limit, page * limit);

    let html = '';
    if (sessionKeys.length === 0) {
        html = '<div style="color:var(--secondary-text);padding:10px 0;">No chat history threads found.</div>';
    } else {
        html = `
            ${slicedKeys.map(sid => {
                const s = sessions[sid];
                const sortedMsgs = [...s.messages].reverse();
                return `
                    <details style="margin-bottom:12px;border:1px dashed var(--border-color);border-radius:8px;padding:6px 12px;background:var(--input-bg);">
                        <summary style="font-weight:600;font-size:13px;padding:6px 0;cursor:pointer;color:var(--text-color);">${s.title}</summary>
                        <div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;">
                            ${sortedMsgs.map(msg => `
                                <div class="chat-tree-bubble ${msg.role}">
                                    <span style="font-weight:600;font-size:10px;text-transform:uppercase;color:${msg.role === 'user' ? 'var(--accent-color)' : '#3a9a5c'};display:block;margin-bottom:2px;">${msg.role}</span>
                                    <span>${escapeHtml(msg.content)}</span>
                                </div>
                            `).join('')}
                        </div>
                    </details>
                `;
            }).join('')}
            ${paginationControls("chat", sessionKeys.length, page, limit)}
        `;
    }
    container.innerHTML = html;
}


/* -----------------------------------------
   INSIGHTS PANEL  (AI view — right column)
----------------------------------------- */

function renderInsights() {

    return `
        <div class="widget">

            <div class="widget-title">Business Insights</div>

            <div style="display:flex;gap:12px;flex-wrap:wrap">

                <div class="card" style="padding:12px;flex:1">
                    <strong>Total Revenue</strong>
                    <div>₹125,000</div>
                </div>

                <div class="card" style="padding:12px;flex:1">
                    <strong>Top Customer</strong>
                    <div>Vision Tech</div>
                </div>

            </div>

            <div class="widget-title" style="margin-top:12px">
                Notifications
            </div>

            <ul class="activity-list">
                <li>Reminder: INV-103 due in 3 days</li>
                <li>Payment ₹7,800 overdue</li>
            </ul>

        </div>
    `;
}


/* -----------------------------------------
   DELETE DATABASE (SMART CONFIRMATION)
----------------------------------------- */

let deleteConfirmationStep = 0;

function showDeleteDatabaseModal() {
    // Multi-step confirmation to prevent accidental deletes.
    // Step 1: Show warning modal
    // Step 2: User clicks 'I understand', then must type 'DELETE'
    // Step 3: Confirm and execute deletion
    
    deleteConfirmationStep = 0;
    
    // Create modal overlay
    const modal = document.createElement("div");
    modal.id = "deleteDbModal";
    modal.className = "custom-modal-overlay";
    
    modal.innerHTML = `
        <div style="
            background: var(--card-color);
            border-radius: 12px;
            padding: 32px;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 16px 48px rgba(0,0,0,0.3);
            border: 2px solid rgba(201,66,66,0.3);
        ">
            <div style="
                font-size: 24px;
                font-weight: 700;
                margin-bottom: 12px;
                color: #c94242;
            ">⚠ Delete Entire Database?</div>
            
            <div style="
                font-size: 14px;
                line-height: 1.6;
                margin-bottom: 24px;
                color: var(--secondary-text);
            ">
                This will <strong>permanently delete</strong> all data:
                <br/>• All invoices
                <br/>• All inventory records
                <br/>• All payment history
                <br/>• All uploads
                <br/><br/>
                <span style="color: #c94242; font-weight: 600;">This action CANNOT be undone.</span>
            </div>
            
            <div style="
                display: flex;
                gap: 12px;
                margin-bottom: 20px;
            ">
                <button
                    onclick="closeDeleteModal()"
                    style="
                        flex: 1;
                        padding: 12px;
                        border-radius: 8px;
                        border: 1px solid var(--border-color);
                        background: transparent;
                        color: var(--text-color);
                        cursor: pointer;
                        font-weight: 600;
                    "
                >Cancel</button>
                
                <button
                    onclick="confirmDeleteStep1()"
                    style="
                        flex: 1;
                        padding: 12px;
                        border-radius: 8px;
                        border: none;
                        background: #c94242;
                        color: white;
                        cursor: pointer;
                        font-weight: 600;
                    "
                >I Understand, Delete</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
}

function confirmDeleteStep1() {
    // Step 1 → Step 2: Show confirmation text input
    
    const modal = document.getElementById("deleteDbModal");
    
    modal.innerHTML = `
        <div style="
            background: var(--card-color);
            border-radius: 12px;
            padding: 32px;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 16px 48px rgba(0,0,0,0.3);
            border: 2px solid rgba(201,66,66,0.3);
        ">
            <div style="
                font-size: 20px;
                font-weight: 700;
                margin-bottom: 16px;
                color: #c94242;
            ">Final Confirmation Required</div>
            
            <div style="
                font-size: 13px;
                line-height: 1.6;
                margin-bottom: 20px;
                color: var(--secondary-text);
            ">
                Type the word <strong style="color: #c94242">DELETE</strong> below to confirm permanent deletion.
            </div>
            
            <input
                id="deleteConfirmInput"
                type="text"
                placeholder="Type DELETE..."
                style="
                    width: 100%;
                    padding: 12px;
                    border-radius: 8px;
                    border: 1px solid var(--border-color);
                    background: var(--input-bg);
                    color: var(--text-color);
                    font-size: 14px;
                    margin-bottom: 20px;
                    box-sizing: border-box;
                "
                oninput="updateDeleteButton()"
            />
            
            <div style="
                display: flex;
                gap: 12px;
            ">
                <button
                    onclick="closeDeleteModal()"
                    style="
                        flex: 1;
                        padding: 12px;
                        border-radius: 8px;
                        border: 1px solid var(--border-color);
                        background: transparent;
                        color: var(--text-color);
                        cursor: pointer;
                        font-weight: 600;
                    "
                >Cancel</button>
                
                <button
                    id="deleteFinalBtn"
                    onclick="confirmDeleteStep2()"
                    disabled
                    style="
                        flex: 1;
                        padding: 12px;
                        border-radius: 8px;
                        border: none;
                        background: #c94242;
                        color: white;
                        cursor: not-allowed;
                        font-weight: 600;
                        opacity: 0.5;
                    "
                >Delete Permanently</button>
            </div>
        </div>
    `;
    
    // Focus input
    setTimeout(() => document.getElementById("deleteConfirmInput").focus(), 100);
}

function updateDeleteButton() {
    const input = document.getElementById("deleteConfirmInput");
    const btn = document.getElementById("deleteFinalBtn");
    
    if (input.value.toUpperCase() === "DELETE") {
        btn.disabled = false;
        btn.style.opacity = "1";
        btn.style.cursor = "pointer";
    } else {
        btn.disabled = true;
        btn.style.opacity = "0.5";
        btn.style.cursor = "not-allowed";
    }
}

async function confirmDeleteStep2() {
    // Step 2 → Execute deletion
    console.warn("%c[BizAssist DB Wipe] User confirmed DELETE database operation. Sending API request...", "color: #f44336; font-weight: bold;");
    
    const modal = document.getElementById("deleteDbModal");
    
    // Show loading state
    modal.innerHTML = `
        <div style="
            background: var(--card-color);
            border-radius: 12px;
            padding: 32px;
            max-width: 450px;
            width: 90%;
            box-shadow: 0 16px 48px rgba(0,0,0,0.3);
            text-align: center;
        ">
            <div style="
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 16px;
            ">Deleting database...</div>
            <div style="
                width: 40px;
                height: 40px;
                border-radius: 50%;
                border: 4px solid var(--border-color);
                border-top-color: #c94242;
                animation: spin 1s linear infinite;
                margin: 0 auto;
            "></div>
        </div>
    `;
    
    try {
        const response = await fetch(`${API_BASE}/database/delete`, {
            method: "DELETE",
            headers: { "Content-Type": "application/json" }
        });
        
        if (response.ok) {
            const data = await response.json();
            console.log("%c[BizAssist DB Wipe] Database wiped successfully! Details:", "color: #4caf50; font-weight: bold;", data);
            
            // Success!
            modal.innerHTML = `
                <div style="
                    background: var(--card-color);
                    border-radius: 12px;
                    padding: 32px;
                    max-width: 450px;
                    width: 90%;
                    box-shadow: 0 16px 48px rgba(0,0,0,0.3);
                    text-align: center;
                    border: 2px solid rgba(76,175,80,0.3);
                ">
                    <div style="
                        font-size: 24px;
                        margin-bottom: 16px;
                    ">✓</div>
                    <div style="
                        font-size: 18px;
                        font-weight: 700;
                        margin-bottom: 8px;
                        color: #4caf50;
                     ">Database Deleted</div>
                    <div style="
                        font-size: 13px;
                        color: var(--secondary-text);
                        margin-bottom: 24px;
                    ">All data has been permanently removed.</div>
                    <button
                        onclick="closeDeleteModal(); openDatabasePanel();"
                        style="
                            width: 100%;
                            padding: 12px;
                            border-radius: 8px;
                            border: none;
                            background: #4caf50;
                            color: white;
                            cursor: pointer;
                            font-weight: 600;
                        "
                    >Done</button>
                </div>
            `;
        } else {
            throw new Error("Failed to delete database");
        }
    } catch (error) {
        console.error("%c[BizAssist DB Wipe Error] Failed to delete database:", "color: #f44336; font-weight: bold;", error);
        modal.innerHTML = `
            <div style="
                background: var(--card-color);
                border-radius: 12px;
                padding: 32px;
                max-width: 450px;
                width: 90%;
                box-shadow: 0 16px 48px rgba(0,0,0,0.3);
                border: 2px solid rgba(201,66,66,0.3);
            ">
                <div style="
                    font-size: 18px;
                    font-weight: 700;
                    margin-bottom: 16px;
                    color: #c94242;
                ">Error Deleting Database</div>
                <div style="
                    font-size: 13px;
                    color: var(--secondary-text);
                    margin-bottom: 24px;
                ">${error.message}</div>
                <button
                    onclick="closeDeleteModal()"
                    style="
                        width: 100%;
                        padding: 12px;
                        border-radius: 8px;
                        border: none;
                        background: #c94242;
                        color: white;
                        cursor: pointer;
                        font-weight: 600;
                    "
                >Close</button>
            </div>
        `;
    }
}

function closeDeleteModal() {
    const modal = document.getElementById("deleteDbModal");
    if (modal) {
        modal.remove();
    }
    deleteConfirmationStep = 0;
}
