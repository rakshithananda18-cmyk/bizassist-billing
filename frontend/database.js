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

let currentPage = {
    uploads   : 1,
    invoices  : 1,
    inventory : 1
};

const itemsPerPage = 5;

function changePage(tableId, newPage) {

    if (newPage < 1) return;

    currentPage[tableId] = newPage;

    openDatabasePanel();
}


/* -----------------------------------------
   PAGINATION CONTROLS  (reusable helper)
----------------------------------------- */

function paginationControls(tableId, total, page) {

    const totalPages = Math.ceil(total / itemsPerPage);

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

        /* --- Uploads table --- */
        const uploadsPage  = currentPage.uploads;
        const uploadsSlice = data.uploads.slice(
            (uploadsPage - 1) * itemsPerPage,
            uploadsPage * itemsPerPage
        );

        const uploadsRows = uploadsSlice.map(file => `
            <tr>
                <td>${file.filename}</td>
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

        /* --- Invoices table --- */
        const invoicesPage  = currentPage.invoices;
        const invoicesSlice = data.invoices.slice(
            (invoicesPage - 1) * itemsPerPage,
            invoicesPage * itemsPerPage
        );

        const invoiceRows = invoicesSlice.map(inv => `
            <tr>
                <td>${inv.customer}</td>
                <td>₹${inv.amount}</td>
                <td>${inv.status}</td>
            </tr>
        `).join("");

        /* --- Inventory table --- */
        const inventoryPage  = currentPage.inventory;
        const inventorySlice = data.inventory.slice(
            (inventoryPage - 1) * itemsPerPage,
            inventoryPage * itemsPerPage
        );

        const inventoryRows = inventorySlice.map(item => `
            <tr>
                <td>${item.product}</td>
                <td>${item.stock}</td>
                <td>${item.expiry}</td>
            </tr>
        `).join("");

        /* --- Assemble full panel --- */
        dashboardLeft.innerHTML = `

            <!-- OVERVIEW CARDS -->
            <div class="widget">

                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">

                    <div class="widget-title" style="margin:0">
                        Database Overview
                    </div>

                    <div style="display:flex;gap:8px">
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

                <div class="cards">

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

                <div class="database-table">
                    <table>
                        <tr>
                            <th>Filename</th>
                            <th>Type</th>
                            <th>Rows</th>
                            <th>Uploaded</th>
                            <th>Action</th>
                        </tr>
                        ${uploadsRows}
                    </table>
                    ${paginationControls("uploads", data.uploads.length, uploadsPage)}
                </div>

            </div>

            <!-- INVOICE RECORDS -->
            <div class="widget">

                <div class="widget-title">Invoice Records</div>

                <div class="database-table">
                    <table>
                        <tr>
                            <th>Customer</th>
                            <th>Amount</th>
                            <th>Status</th>
                        </tr>
                        ${invoiceRows}
                    </table>
                    ${paginationControls("invoices", data.invoices.length, invoicesPage)}
                </div>

            </div>

            <!-- INVENTORY RECORDS -->
            <div class="widget">

                <div class="widget-title">Inventory Records</div>

                <div class="database-table">
                    <table>
                        <tr>
                            <th>Product</th>
                            <th>Stock</th>
                            <th>Expiry</th>
                        </tr>
                        ${inventoryRows}
                    </table>
                    ${paginationControls("inventory", data.inventory.length, inventoryPage)}
                </div>

            </div>

        `;

    } catch (error) {

        console.error(error);
        await showCustomAlert("Failed to load database", "Error");
    } finally {
        const refreshBtnLive = document.querySelector('button[onclick="openDatabasePanel()"]');
        if (typeof setElementLoading === "function" && refreshBtnLive) {
            setElementLoading(refreshBtnLive, false);
        }
    }
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
        console.error(error);
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
