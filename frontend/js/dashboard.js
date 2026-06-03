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

/* Area chart for monthly revenue trends */
function buildAreaChart(trends) {
    if (!trends || !trends.length || (trends.length === 1 && trends[0].revenue === 0)) {
        return `<div style="color:var(--secondary-text);font-size:12px;text-align:center;padding:50px 0;width:100%;">No revenue trends recorded yet</div>`;
    }
    
    const maxVal = Math.max(...trends.map(t => t.revenue), 1);
    const width = 500;
    const height = 150;
    const padding = { top: 20, right: 20, bottom: 25, left: 50 };
    
    const chartWidth = width - padding.left - padding.right;
    const chartHeight = height - padding.top - padding.bottom;
    
    const points = trends.map((t, idx) => {
        const x = padding.left + (idx / Math.max(trends.length - 1, 1)) * chartWidth;
        const y = padding.top + chartHeight - (t.revenue / maxVal) * chartHeight;
        return { x, y, label: t.month, val: t.revenue };
    });
    
    const linePath = points.map((p, idx) => `${idx === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    const firstP = points[0];
    const lastP = points[points.length - 1];
    const areaPath = `${linePath} L ${lastP.x} ${padding.top + chartHeight} L ${firstP.x} ${padding.top + chartHeight} Z`;
    
    const gridLines = [];
    for (let i = 0; i <= 3; i++) {
        const y = padding.top + (i / 3) * chartHeight;
        const val = maxVal - (i / 3) * maxVal;
        gridLines.push(`
            <line x1="${padding.left}" y1="${y}" x2="${width - padding.right}" y2="${y}" stroke="var(--border-color)" stroke-dasharray="3 3" />
            <text x="${padding.left - 8}" y="${y + 4}" fill="var(--secondary-text)" font-size="9" text-anchor="end">₹${(val/1000).toFixed(0)}k</text>
        `);
    }
    
    let labelInterval = 1;
    if (trends.length > 18) {
        labelInterval = 4;
    } else if (trends.length > 12) {
        labelInterval = 3;
    } else if (trends.length > 6) {
        labelInterval = 2;
    }

    const xLabels = points.map((p, idx) => {
        if (idx % labelInterval === 0 || idx === points.length - 1) {
            return `<text x="${p.x}" y="${height - 6}" fill="var(--secondary-text)" font-size="9" text-anchor="middle">${p.label}</text>`;
        }
        return '';
    }).join('');
    
    const dots = points.map((p, idx) => `
        <g class="chart-dot-group" style="cursor:pointer;" onclick="sendChip('Tell me about revenue in ${p.label}')">
            <circle cx="${p.x}" cy="${p.y}" r="4" fill="var(--card-color)" stroke="var(--accent-color)" stroke-width="2" class="chart-dot" />
            <circle cx="${p.x}" cy="${p.y}" r="12" fill="transparent" class="chart-dot-hitbox" />
            <title>${p.label}: ₹${Number(p.val).toLocaleString('en-IN')}</title>
        </g>
    `).join('');
    
    return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="100%" class="area-chart-svg">
        <defs>
            <linearGradient id="chart-area-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="var(--accent-color)" stop-opacity="0.25" />
                <stop offset="100%" stop-color="var(--accent-color)" stop-opacity="0.0" />
            </linearGradient>
        </defs>
        ${gridLines.join('')}
        ${xLabels}
        <path d="${areaPath}" fill="url(#chart-area-grad)" style="opacity:0.85;" />
        <path d="${linePath}" fill="none" stroke="var(--accent-color)" stroke-width="2.5" stroke-linecap="round" class="chart-line-path" />
        ${dots}
    </svg>
    `;
}

/* Horizontal aging chart for overdue/pending invoices */
function buildAgingBars(aging) {
    if (!aging || !aging.length || aging.every(a => a.amount === 0)) {
        return '<div style="color:var(--secondary-text);font-size:12px;padding:50px 0;text-anchor:middle;text-align:center;width:100%;">No outstanding debt recorded</div>';
    }
    const maxVal = Math.max(...aging.map(a => a.amount), 1);
    const colors = ['#c97c22', '#c95e22', '#c94242', '#962424'];
    
    return aging.map((a, i) => {
        const pct = Math.max(2, (a.amount / maxVal) * 100);
        return `
        <div class="bar-row" onclick="sendChip('Tell me about overdue payments in range ${a.range}')"
             title="${a.range} — ₹${Number(a.amount).toLocaleString('en-IN')}">
            <div class="bar-label">${a.range}</div>
            <div class="bar-track">
                <div class="bar-fill" style="width:${pct}%;background:${colors[i]};
                     transition:width 0.7s cubic-bezier(.4,0,.2,1) ${i*0.1}s"></div>
            </div>
            <div class="bar-value">₹${(a.amount/1000).toFixed(1)}k</div>
        </div>`;
    }).join('');
}


/* -----------------------------------------
   LIVE INSIGHTS PANEL
----------------------------------------- */

async function loadInsightsPanel() {

    const panel = document.getElementById("insights-panel");
    if (!panel || panel.classList.contains("hidden")) return;
    const contentContainer = document.getElementById("insights-content");
    if (!contentContainer) return;

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

        /* ── BUILD DONUT SVG ── */
        const r = 36, circ = 2 * Math.PI * r;
        const paidPct    = paid    / Math.max(total, 1);
        const pendPct    = pending / Math.max(total, 1);
        const overPct    = Math.max(0, 1 - paidPct - pendPct);
        const paidDash   = paidPct  * circ;
        const pendDash   = pendPct  * circ;
        const overDash   = overPct  * circ;
        const pendOffset = -(paidPct * circ);
        const overOffset = -((paidPct + pendPct) * circ);
        const donutSVG   = `
          <svg width="68" height="68" viewBox="0 0 88 88" style="transform:rotate(-90deg);flex-shrink:0">
            <circle cx="44" cy="44" r="${r}" fill="none" stroke="var(--border-color)" stroke-width="10"/>
            <circle cx="44" cy="44" r="${r}" fill="none" stroke="#3a9a5c" stroke-width="10"
              stroke-dasharray="${paidDash} ${circ}" stroke-dashoffset="0"/>
            <circle cx="44" cy="44" r="${r}" fill="none" stroke="#c97c22" stroke-width="10"
              stroke-dasharray="${pendDash} ${circ}" stroke-dashoffset="${pendOffset}"/>
            <circle cx="44" cy="44" r="${r}" fill="none" stroke="#c94242" stroke-width="10"
              stroke-dasharray="${overDash} ${circ}" stroke-dashoffset="${overOffset}"/>
          </svg>`;

        const overPctBar = Math.min(100, (overdueAmt / Math.max(revenue, 1)) * 100);
        const maxCust    = customers[0] ? customers[0].total : 1;

        /* ── Revenue card ── */
        const metricsEl = document.getElementById("insights-metrics");
        if (metricsEl) {
            metricsEl.innerHTML = `
            <div class="ip-card ip-card-accent"
                 onclick="sendChip('Give me a complete revenue breakdown — paid, pending and overdue')">
                <div class="ip-card-top">
                    <div>
                        <div class="ip-card-label">Total Revenue</div>
                        <div class="ip-card-value">₹${(revenue/100000).toFixed(1)}L</div>
                        <div class="ip-card-sub">${total} invoices total</div>
                    </div>
                    <div class="ip-donut-wrap" style="position:relative;width:64px;height:64px;flex-shrink:0">
                        ${donutSVG}
                        <div class="ip-donut-center">${healthPct}%</div>
                    </div>
                </div>
                <div class="ip-legend">
                    <span class="ip-dot" style="background:#3a9a5c"></span><span>Paid</span>
                    <span class="ip-dot" style="background:#c97c22"></span><span>Pend</span>
                    <span class="ip-dot" style="background:#c94242"></span><span>Over</span>
                </div>
            </div>`;
        }

        /* ── Overdue card ── */
        const customersEl = document.getElementById("insights-customers");
        if (customersEl) {
            customersEl.innerHTML = `
            <div class="ip-card ip-card-danger"
                 onclick="sendChip('List all overdue invoices with amounts and due dates')">
                <div class="ip-card-label">Overdue Amount</div>
                <div class="ip-card-value" style="color:#c94242">
                    ₹${Number(overdueAmt).toLocaleString('en-IN')}
                </div>
                <div class="ip-card-sub">${pending} pending invoices</div>
                <div class="ip-alert-bar">
                    <div class="ip-alert-fill" style="width:${overPctBar}%"></div>
                </div>
                <div class="ip-card-cta">Tap to see full list →</div>
            </div>`;
        }

        /* ── Top customers bar chart + alert action rows ── */
        const alertsEl = document.getElementById("insights-alerts");
        if (alertsEl) {
            alertsEl.innerHTML = `
            <div class="ip-section"
                 onclick="sendChip('Who are my top customers by revenue? Give full details')">
                <div class="ip-section-header">
                    <span class="ip-section-title">Top Customers</span>
                    <span class="ip-section-cta">View all →</span>
                </div>
                <div class="ip-bars">
                    ${customers.slice(0, 4).map(c => {
                        const pct = Math.max(4, (c.total / maxCust) * 100);
                        const label = c.customer.length > 12 ? c.customer.slice(0, 11) + '…' : c.customer;
                        return `<div class="bar-row">
                            <div class="bar-label">${label}</div>
                            <div class="bar-track"><div class="bar-fill" style="width:${pct}%;background:var(--accent-color)"></div></div>
                            <div class="bar-value">₹${Math.round(c.total/1000)}k</div>
                        </div>`;
                    }).join('')}
                </div>
            </div>

            <div class="ip-alerts-section">
                <div class="ip-alert-row ip-alert-warn"
                     onclick="sendChip('Which medicines and products are expiring in the next 30 days?')">
                    <div class="ip-alert-icon">⏰</div>
                    <div class="ip-alert-text"><strong>Expiry check</strong><span>See items expiring soon</span></div>
                    <div class="ip-alert-arrow">›</div>
                </div>
                <div class="ip-alert-row ip-alert-info"
                     onclick="sendChip('Which products have low stock and need reordering?')">
                    <div class="ip-alert-icon">📦</div>
                    <div class="ip-alert-text"><strong>Low stock</strong><span>Items needing reorder</span></div>
                    <div class="ip-alert-arrow">›</div>
                </div>
                <div class="ip-alert-row ip-alert-red"
                     onclick="sendChip('List all overdue invoices with amounts and due dates')">
                    <div class="ip-alert-icon">🔴</div>
                    <div class="ip-alert-text"><strong>Overdue invoices</strong><span>₹${Number(overdueAmt).toLocaleString('en-IN')} pending</span></div>
                    <div class="ip-alert-arrow">›</div>
                </div>
                <div class="ip-alert-row ip-alert-green"
                     onclick="sendChip('Who are my top 5 customers by revenue this period?')">
                    <div class="ip-alert-icon">🏆</div>
                    <div class="ip-alert-text"><strong>Top customers</strong><span>${customers[0] ? customers[0].customer + ' leads' : 'See rankings'}</span></div>
                    <div class="ip-alert-arrow">›</div>
                </div>
            </div>`;
        }

    } catch (e) {
        if (DEBUG) console.error("Insights panel failed:", e);
        const contentContainer = document.getElementById("insights-content");
        if (contentContainer) contentContainer.innerHTML = `
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