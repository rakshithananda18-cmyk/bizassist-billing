/* =========================================
   dashboard.js
   Stat cards, top customers, live visual
   insights panel with mini charts.
   Depends on: config.js
========================================= */


/* -----------------------------------------
   DASHBOARD SUMMARY  (top stat cards)
----------------------------------------- */

async function loadDashboardSummary() {
    try {
        const res  = await fetch(`${API_BASE}/dashboard-summary`);
        const data = await res.json();

        document.getElementById("total-revenue").textContent =
            `₹${Number(data.total_revenue).toLocaleString('en-IN')}`;
        document.getElementById("pending-payments").textContent =
            data.pending_invoices;
        document.getElementById("invoice-count").textContent =
            data.invoice_count;

        /* refresh insights if visible */
        if (typeof loadInsightsPanel === "function") loadInsightsPanel();

    } catch (e) {
        if (DEBUG) console.error("Dashboard summary failed:", e);
    }
}


/* -----------------------------------------
   TOP CUSTOMERS
----------------------------------------- */

async function loadTopCustomers() {
    try {
        const res  = await fetch(`${API_BASE}/top-customers`);
        const data = await res.json();
        const el   = document.getElementById("top-customers-list");
        if (!el) return;
        el.innerHTML = "";
        data.forEach(c => {
            const d = document.createElement("div");
            d.className = "customer-item";
            d.innerHTML = `<div><strong>${c.customer}</strong></div>
                           <div>₹${Number(c.total).toLocaleString('en-IN')}</div>`;
            el.appendChild(d);
        });
    } catch (e) {
        if (DEBUG) console.error("Top customers failed:", e);
    }
}


/* -----------------------------------------
   MINI SVG CHARTS
----------------------------------------- */

/* Donut chart — invoice status breakdown */
function buildDonut(paid, pending, overdue) {
    const total = paid + pending + overdue || 1;
    const r = 36, cx = 44, cy = 44, stroke = 10;
    const circ = 2 * Math.PI * r;

    function arc(value, offset, color) {
        const dash = (value / total) * circ;
        return `<circle cx="${cx}" cy="${cy}" r="${r}"
            fill="none" stroke="${color}" stroke-width="${stroke}"
            stroke-dasharray="${dash} ${circ}"
            stroke-dashoffset="${-offset}"
            stroke-linecap="butt"
            style="transition:stroke-dasharray 0.6s ease"/>`;
    }

    const paidDash    = (paid    / total) * circ;
    const pendDash    = (pending / total) * circ;
    const oDash       = (overdue / total) * circ;

    return `
    <svg width="88" height="88" viewBox="0 0 88 88" style="transform:rotate(-90deg)">
        ${arc(paid,    0,                paidDash, '#3a9a5c')}
        ${arc(pending, paidDash,         '#c97c22')}
        ${arc(overdue, paidDash+pendDash,'#c94242')}
    </svg>`;
}

/* Horizontal bar chart — top 5 customers */
function buildBarChart(customers) {
    if (!customers.length) return '<div style="color:var(--secondary-text);font-size:12px;padding:8px 0">No data yet</div>';
    const max = customers[0].total || 1;
    const colors = ['#c96442','#c97c22','#3a9a5c','#4a90c9','#9b6ec9'];

    return customers.slice(0, 5).map((c, i) => {
        const pct = Math.max(4, (c.total / max) * 100);
        const label = c.customer.length > 14 ? c.customer.slice(0, 13) + '…' : c.customer;
        return `
        <div class="bar-row" onclick="sendChip('Tell me about ${c.customer} payment status and invoices')"
             title="${c.customer} — ₹${Number(c.total).toLocaleString('en-IN')}">
            <div class="bar-label">${label}</div>
            <div class="bar-track">
                <div class="bar-fill" style="width:${pct}%;background:${colors[i]};
                     transition:width 0.7s cubic-bezier(.4,0,.2,1) ${i*0.1}s"></div>
            </div>
            <div class="bar-value">₹${(c.total/1000).toFixed(0)}k</div>
        </div>`;
    }).join('');
}


/* -----------------------------------------
   LIVE INSIGHTS PANEL
----------------------------------------- */

async function loadInsightsPanel() {

    const panel = document.getElementById("insights-panel");
    if (!panel || panel.classList.contains("hidden")) return;

    try {

        /* Fetch all data in parallel */
        const [summaryRes, customersRes] = await Promise.all([
            fetch(`${API_BASE}/dashboard-summary`),
            fetch(`${API_BASE}/top-customers`)
        ]);

        const summary   = await summaryRes.json();
        const customers = await customersRes.json();

        /* Invoice counts */
        const total   = summary.invoice_count   || 0;
        const pending = summary.pending_invoices || 0;
        const overdue = Math.round((summary.overdue_amount || 0) /
                        ((summary.total_revenue || 1) / total)) || 0;
        const paid    = Math.max(0, total - pending - overdue);

        const revenue      = summary.total_revenue    || 0;
        const overdueAmt   = summary.overdue_amount   || 0;
        const collectedAmt = revenue - overdueAmt;
        const healthPct    = revenue > 0 ? Math.round((collectedAmt / revenue) * 100) : 0;

        panel.innerHTML = `

        <!-- ═══ ROW 1: Visual stat cards ═══ -->
        <div class="ip-cards-row">

            <!-- Revenue card with mini donut -->
            <div class="ip-card ip-card-accent"
                 onclick="sendChip('Give me a complete revenue breakdown — paid, pending and overdue')">
                <div class="ip-card-top">
                    <div>
                        <div class="ip-card-label">Total Revenue</div>
                        <div class="ip-card-value">₹${(revenue/100000).toFixed(1)}L</div>
                        <div class="ip-card-sub">${total} invoices total</div>
                    </div>
                    <div class="ip-donut-wrap">
                        <svg width="64" height="64" viewBox="0 0 88 88" style="transform:rotate(-90deg)">
                            <circle cx="44" cy="44" r="36" fill="none" stroke="var(--border-color)" stroke-width="10"/>
                            <circle cx="44" cy="44" r="36" fill="none" stroke="#3a9a5c" stroke-width="10"
                                stroke-dasharray="${(paid/Math.max(total,1))*226} 226"
                                stroke-dashoffset="0" style="transition:stroke-dasharray 0.8s ease"/>
                            <circle cx="44" cy="44" r="36" fill="none" stroke="#c97c22" stroke-width="10"
                                stroke-dasharray="${(pending/Math.max(total,1))*226} 226"
                                stroke-dashoffset="${-(paid/Math.max(total,1))*226}"
                                style="transition:stroke-dasharray 0.8s ease 0.1s"/>
                            <circle cx="44" cy="44" r="36" fill="none" stroke="#c94242" stroke-width="10"
                                stroke-dasharray="${((total-paid-pending)/Math.max(total,1))*226} 226"
                                stroke-dashoffset="${-((paid+pending)/Math.max(total,1))*226}"
                                style="transition:stroke-dasharray 0.8s ease 0.2s"/>
                        </svg>
                        <div class="ip-donut-center">${healthPct}%</div>
                    </div>
                </div>
                <div class="ip-legend">
                    <span class="ip-dot" style="background:#3a9a5c"></span><span>Paid</span>
                    <span class="ip-dot" style="background:#c97c22"></span><span>Pending</span>
                    <span class="ip-dot" style="background:#c94242"></span><span>Overdue</span>
                </div>
            </div>

            <!-- Overdue alert card -->
            <div class="ip-card ip-card-danger"
                 onclick="sendChip('List all overdue invoices with customer names and amounts')">
                <div class="ip-card-label">Overdue Amount</div>
                <div class="ip-card-value" style="color:#c94242">
                    ₹${Number(overdueAmt).toLocaleString('en-IN')}
                </div>
                <div class="ip-card-sub">${pending} pending invoices</div>
                <div class="ip-alert-bar">
                    <div class="ip-alert-fill"
                         style="width:${Math.min(100,(overdueAmt/Math.max(revenue,1))*100)}%">
                    </div>
                </div>
                <div class="ip-card-cta">Tap to see full list →</div>
            </div>

        </div>

        <!-- ═══ ROW 2: Bar chart — top customers ═══ -->
        <div class="ip-section" onclick="sendChip('Who are my top customers by revenue? Give full details')">
            <div class="ip-section-header">
                <span class="ip-section-title">Top Customers</span>
                <span class="ip-section-cta">View all →</span>
            </div>
            <div class="ip-bars">
                ${buildBarChart(customers)}
            </div>
        </div>

        <!-- ═══ ROW 3: Alert rows ═══ -->
        <div class="ip-alerts-section">
            <div class="ip-section-header" style="margin-bottom:8px">
                <span class="ip-section-title">Quick Actions</span>
            </div>

            <div class="ip-alert-row ip-alert-warn"
                 onclick="sendChip('Which medicines and products are expiring in the next 30 days?')">
                <div class="ip-alert-icon">⏰</div>
                <div class="ip-alert-text">
                    <strong>Expiry check</strong>
                    <span>See items expiring soon</span>
                </div>
                <div class="ip-alert-arrow">›</div>
            </div>

            <div class="ip-alert-row ip-alert-info"
                 onclick="sendChip('Which products have low stock and need reordering?')">
                <div class="ip-alert-icon">📦</div>
                <div class="ip-alert-text">
                    <strong>Low stock</strong>
                    <span>Items needing reorder</span>
                </div>
                <div class="ip-alert-arrow">›</div>
            </div>

            <div class="ip-alert-row ip-alert-red"
                 onclick="sendChip('List all overdue invoices with amounts and due dates')">
                <div class="ip-alert-icon">🔴</div>
                <div class="ip-alert-text">
                    <strong>Overdue invoices</strong>
                    <span>₹${Number(overdueAmt).toLocaleString('en-IN')} pending recovery</span>
                </div>
                <div class="ip-alert-arrow">›</div>
            </div>

            <div class="ip-alert-row ip-alert-green"
                 onclick="sendChip('Who are my top 5 customers by revenue this period?')">
                <div class="ip-alert-icon">🏆</div>
                <div class="ip-alert-text">
                    <strong>Top customers</strong>
                    <span>${customers[0] ? customers[0].customer + ' leads' : 'See rankings'}</span>
                </div>
                <div class="ip-alert-arrow">›</div>
            </div>

        </div>`;

    } catch (e) {
        if (DEBUG) console.error("Insights panel failed:", e);
        const panel = document.getElementById("insights-panel");
        if (panel) panel.innerHTML = `
            <div style="color:var(--secondary-text);font-size:13px;padding:20px;text-align:center">
                Could not load insights. Is the backend running?
            </div>`;
    }
}


/* -----------------------------------------
   DEV TESTING
----------------------------------------- */

async function testInvoices() {
    try {
        const r = await fetch(`${API_BASE}/invoices`);
        const d = await r.json();
        console.log(d);
        await showCustomAlert(`Invoices Loaded: ${d.length}`, "Dev Testing");
    } catch (e) {
        console.error(e);
        await showCustomAlert("Invoices API failed", "Error");
    }
}

async function testOverdue() {
    try {
        const r = await fetch(`${API_BASE}/overdue`);
        const d = await r.json();
        console.log(d);
        await showCustomAlert("Overdue API working", "Dev Testing");
    } catch (e) {
        console.error(e);
        await showCustomAlert("Overdue API failed", "Error");
    }
}


if (localStorage.getItem("user")) {
    loadDashboardSummary();
    loadTopCustomers();
}