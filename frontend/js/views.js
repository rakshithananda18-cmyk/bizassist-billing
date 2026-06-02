/* =========================================
   views.js
   Renders each sidebar section into
   #dashboard-left. Each view fetches live
   data, renders a skeleton while loading,
   and integrates AI chip shortcuts.

   Depends on: config.js, chat.js (sendChip)
========================================= */


/* ─── Pagination State for Views ────────────────── */
let _invoicesPage = 1;
let _paymentsOverduePage = 1;
let _paymentsPendingPage = 1;
let _clientsPage = 1;

const INVOICES_PER_PAGE = 10;
const PAYMENTS_PER_PAGE = 5;
const CLIENTS_PER_PAGE = 10;

function _viewsPaginationControls(viewKey, total, page, itemsPerPage, changePageFnName) {
    const totalPages = Math.ceil(total / itemsPerPage);
    if (totalPages <= 1) return "";

    return `
        <div class="db-pagination" style="display:flex;justify-content:center;align-items:center;gap:12px;margin-top:16px;margin-bottom:12px;flex-shrink:0;">
            <button
                class="matte-glass"
                style="padding:6px 12px;cursor:pointer;border-radius:6px;font-size:12px;border:1px solid var(--border-color);background:var(--card-color);color:var(--text-color)"
                onclick="${changePageFnName}(${page - 1})"
                ${page === 1 ? "disabled" : ""}
            >← Previous</button>
            <span style="font-size:12.5px;color:var(--secondary-text);font-weight:600">
                Page ${page} / ${totalPages}
            </span>
            <button
                class="matte-glass"
                style="padding:6px 12px;cursor:pointer;border-radius:6px;font-size:12px;border:1px solid var(--border-color);background:var(--card-color);color:var(--text-color)"
                onclick="${changePageFnName}(${page + 1})"
                ${page >= totalPages ? "disabled" : ""}
            >Next →</button>
        </div>
    `;
}


/* ─── Shared Helpers ────────────────────── */

function fmtAmount(n) {
    if (!n && n !== 0) return '—';
    if (n >= 100000) return '₹' + (n / 100000).toFixed(1) + 'L';
    if (n >= 1000)   return '₹' + Math.round(n / 1000) + 'k';
    return '₹' + Math.round(n);
}

function fmtFull(n) {
    if (!n && n !== 0) return '—';
    return '₹' + Number(n).toLocaleString('en-IN');
}

function statusPill(status) {
    const s = (status || '').toLowerCase();
    const map = {
        paid:    ['#27864a', 'rgba(39,134,74,0.10)'],
        pending: ['#b06510', 'rgba(176,101,16,0.10)'],
        overdue: ['#c02a2a', 'rgba(192,42,42,0.10)'],
    };
    const [color, bg] = map[s] || ['var(--secondary-text)', 'var(--accent-softer)'];
    return `<span class="vpill" style="color:${color};background:${bg}">${status || '—'}</span>`;
}

function skeleton(rows = 4) {
    return Array.from({ length: rows }, () =>
        `<div class="vskel"></div>`
    ).join('');
}

function emptyState(icon, title, sub) {
    return `
        <div class="vempty">
            <div class="vempty-icon">${icon}</div>
            <div class="vempty-title">${title}</div>
            <div class="vempty-sub">${sub}</div>
            <button class="chip upload-btn-highlight" style="margin-top:14px"
                onclick="document.getElementById('file-upload').click()">
                + Upload data
            </button>
            <input type="file" id="file-upload" accept=".csv,.xlsx" hidden>
        </div>`;
}

function viewHeader(title, subtitle, badge) {
    return `
        <div class="vheader">
            <div>
                <div class="vheader-title">${title}
                    ${badge != null ? `<span class="vbadge">${badge}</span>` : ''}
                </div>
                ${subtitle ? `<div class="vheader-sub">${subtitle}</div>` : ''}
            </div>
        </div>`;
}

/* Get the dashboard-left panel safely */
function getLeft() {
    return document.getElementById('dashboard-left');
}


/* ─── DASHBOARD ─────────────────────────── */

async function renderDashboardView() {
    const left = getLeft();
    if (!left) return;

    console.group("%c[BizAssist View] Loading Dashboard...", "color: #3f51b5; font-weight: bold;");

    left.innerHTML = viewHeader('Dashboard', 'Your business at a glance') +
        `<div class="widget">${skeleton(3)}</div>`;

    try {
        const [summary, customers, dbData, charts] = await Promise.all([
            fetch(`${API_BASE}/dashboard-summary`).then(r => r.json()),
            fetch(`${API_BASE}/top-customers`).then(r => r.json()),
            fetch(`${API_BASE}/database`).then(r => r.json()),
            fetch(`${API_BASE}/dashboard-charts`).then(r => r.json()),
        ]);

        console.log("Dashboard components fetched successfully:", { summary, customers, dbData, charts });
        console.groupEnd();

        const isDbEmpty = (summary.invoice_count === 0 && summary.inventory_count === 0) || 
                          ((dbData.invoices || []).length === 0 && (dbData.inventory || []).length === 0);

        const totalVal   = summary.invoice_count   || 0;
        const pendingVal = summary.pending_invoices || 0;
        const overdueVal = Math.round((summary.overdue_amount || 0) /
                        ((summary.total_revenue || 1) / totalVal)) || 0;
        const paidVal    = Math.max(0, totalVal - pendingVal - overdueVal);
        const collectedAmt = summary.total_revenue - summary.overdue_amount;
        const healthPct  = summary.total_revenue > 0 ? Math.round((collectedAmt / summary.total_revenue) * 100) : 0;

        left.innerHTML = viewHeader('Dashboard', 'Your business at a glance') + `

            <!-- STAT STRIP -->
            <div class="vstat-grid" style="margin-bottom: 12px;">
                <div class="vstat-card" style="border-left-color:var(--accent-color)"
                     onclick="sendChip('What is my total revenue?')">
                    <div class="vstat-label">Total Revenue</div>
                    <div class="vstat-value">${fmtAmount(summary.total_revenue)}</div>
                    <div class="vstat-sub">${summary.invoice_count} invoices</div>
                </div>
                <div class="vstat-card" style="border-left-color:#c97c22"
                     onclick="sendChip('List all pending invoices')">
                    <div class="vstat-label">Pending</div>
                    <div class="vstat-value">${summary.pending_invoices}</div>
                    <div class="vstat-sub">invoices awaiting</div>
                </div>
                <div class="vstat-card" style="border-left-color:#c02a2a"
                     onclick="sendChip('Show me all overdue invoices with amounts')">
                    <div class="vstat-label">Overdue</div>
                    <div class="vstat-value" style="color:#c02a2a">${fmtAmount(summary.overdue_amount)}</div>
                    <div class="vstat-sub">needs recovery</div>
                </div>
                <div class="vstat-card" style="border-left-color:#3a9a5c"
                     onclick="sendChip('How many products are in inventory?')">
                    <div class="vstat-label">Inventory</div>
                    <div class="vstat-value">${summary.inventory_count}</div>
                    <div class="vstat-sub">products tracked</div>
                </div>
            </div>

            <!-- QUICK ACTIONS -->
            <div class="widget" style="margin-bottom: 12px;">
                <div class="widget-title">Quick Actions</div>
                <div class="vactions">
                    <button class="vaction-btn ${isDbEmpty ? 'upload-btn-highlight' : ''}" onclick="document.getElementById('file-upload-dash').click()">
                        <span class="vaction-icon">↑</span> Upload Data
                    </button>
                    <input type="file" id="file-upload-dash" accept=".csv,.xlsx" hidden>
                    <button class="vaction-btn" onclick="sendChip('Generate a business summary')">
                        <span class="vaction-icon">✦</span> Business Summary
                    </button>
                    <button class="vaction-btn" onclick="selectSidebar('invoices')">
                        <span class="vaction-icon">◫</span> View Invoices
                    </button>
                </div>
            </div>

            <!-- BUSINESS INSIGHTS & GRAPHS -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px;">
                <!-- Donut Chart -->
                <div class="widget" style="display: flex; flex-direction: column; justify-content: space-between; min-height: 240px;">
                    <div class="widget-title" style="margin-bottom: 16px;">Revenue Distribution</div>
                    <div style="display: flex; align-items: center; gap: 20px; justify-content: center; flex: 1;">
                        <div class="ip-donut-wrap" style="position: relative; width: 88px; height: 88px; flex-shrink: 0;">
                            ${buildDonut(paidVal, pendingVal, overdueVal)}
                            <div class="ip-donut-center" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; color: var(--text-color);">
                                ${healthPct}%
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 8px; font-size: 13px;">
                            <div style="display: flex; align-items: center; gap: 8px; cursor: pointer;" onclick="sendChip('List all paid invoices')">
                                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #3a9a5c;"></span>
                                <span style="color: var(--secondary-text)">Paid:</span>
                                <strong style="color: #3a9a5c">${paidVal} invoices</strong>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px; cursor: pointer;" onclick="sendChip('List all pending invoices')">
                                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #c97c22;"></span>
                                <span style="color: var(--secondary-text)">Pending:</span>
                                <strong style="color: #c97c22">${pendingVal} invoices</strong>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px; cursor: pointer;" onclick="sendChip('List all overdue invoices')">
                                <span style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #c94242;"></span>
                                <span style="color: var(--secondary-text)">Overdue:</span>
                                <strong style="color: #c94242">${overdueVal} invoices</strong>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Top Customers Bar Chart -->
                <div class="widget" style="min-height: 240px; display: flex; flex-direction: column;">
                    <div class="widget-title" style="margin-bottom: 16px;">Top Customers</div>
                    <div class="ip-bars" style="flex: 1; display: flex; flex-direction: column; justify-content: center;">
                        ${buildBarChart(customers)}
                    </div>
                </div>
            </div>

            <!-- SECOND ROW CHART GRID -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; margin-top: 12px;">
                <!-- Monthly Revenue Trends -->
                <div class="widget" style="min-height: 240px; display: flex; flex-direction: column;">
                    <div class="widget-title" style="margin-bottom: 16px;">Monthly Revenue Trend</div>
                    <div id="monthly-trend-chart" style="flex: 1; display: flex; align-items: center; justify-content: center; min-height: 150px;">
                        ${buildAreaChart(charts.monthly_revenue)}
                    </div>
                </div>

                <!-- Invoice Aging -->
                <div class="widget" style="min-height: 240px; display: flex; flex-direction: column;">
                    <div class="widget-title" style="margin-bottom: 16px;">Overdue Debt Aging</div>
                    <div id="aging-overview-chart" style="flex: 1; display: flex; flex-direction: column; justify-content: center;">
                        ${buildAgingBars(charts.aging_overview)}
                    </div>
                </div>
            </div>`;

    } catch (e) {
        console.error("Dashboard components load failed:", e);
        console.groupEnd();
        left.innerHTML = viewHeader('Dashboard', '') +
            emptyState('📊', 'No data yet', 'Upload invoices or inventory to see your dashboard.');
    }
}


/* ─── INVOICES ───────────────────────────── */

let _invoicesData  = [];
let _invoiceFilter = 'all';

async function renderInvoicesView() {
    const left = getLeft();
    if (!left) return;

    console.group("%c[BizAssist View] Loading Invoices...", "color: #3f51b5; font-weight: bold;");

    left.innerHTML = viewHeader('Invoices', 'All billing records') +
        `<div class="widget">${skeleton(5)}</div>`;

    try {
        const data = await fetch(`${API_BASE}/database`).then(r => r.json());
        _invoicesData = data.invoices || [];
        _invoiceFilter = 'all';
        console.log(`Loaded ${_invoicesData.length} total invoices from database.`);
        console.groupEnd();
        _paintInvoices(left);
    } catch (e) {
        console.error("Failed to load invoices database:", e);
        console.groupEnd();
        left.innerHTML = viewHeader('Invoices', '') +
            emptyState('📋', 'No invoices found', 'Upload a CSV/XLSX with invoice_id column.');
    }
}

function _paintInvoices(left) {
    const all      = _invoicesData;
    const filtered = _invoiceFilter === 'all'
        ? all
        : all.filter(i => (i.status || '').toLowerCase() === _invoiceFilter);

    const paid    = all.filter(i => (i.status||'').toLowerCase() === 'paid').length;
    const pending = all.filter(i => (i.status||'').toLowerCase() === 'pending').length;
    const overdue = all.filter(i => (i.status||'').toLowerCase() === 'overdue').length;
    const total   = all.reduce((s, i) => s + (i.amount || 0), 0);

    const tabs = ['all', 'paid', 'pending', 'overdue'].map(t => {
        const count = t === 'all' ? all.length : all.filter(i => (i.status||'').toLowerCase() === t).length;
        const active = t === _invoiceFilter ? ' vtab-active' : '';
        return `<button class="vtab${active}" onclick="_setInvoiceFilter('${t}')">${t.charAt(0).toUpperCase()+t.slice(1)} <span class="vtab-count">${count}</span></button>`;
    }).join('');

    const sliceStart = (_invoicesPage - 1) * INVOICES_PER_PAGE;
    const sliceEnd = _invoicesPage * INVOICES_PER_PAGE;
    const paginatedInvoices = filtered.slice(sliceStart, sliceEnd);

    const rows = paginatedInvoices.length
        ? paginatedInvoices.map(inv => `
            <tr>
                <td><span style="font-family:'Geist Mono',monospace;font-size:12px;opacity:0.7">${inv.invoice_id || '—'}</span></td>
                <td style="font-weight:500">${inv.customer || '—'}</td>
                <td style="font-family:'Crimson Pro',serif;font-size:15px;font-weight:600">${fmtFull(inv.amount)}</td>
                <td>${statusPill(inv.status)}</td>
                <td><button class="vlink" onclick="sendChip('Invoice ${inv.invoice_id} for ${inv.customer}: status and amount')">Ask AI</button></td>
            </tr>`).join('')
        : `<tr><td colspan="5" class="vtable-empty">No ${_invoiceFilter} invoices found.</td></tr>`;

    left.innerHTML = viewHeader('Invoices', `${all.length} total · ${fmtAmount(total)} revenue`, all.length) + `

         <!-- FILTER TABS -->
        <div class="vtabs">${tabs}</div>

        <!-- TABLE -->
        <div class="widget" style="padding:0;overflow:hidden">
            <div class="vtable-wrap">
                <table>
                    <thead><tr>
                        <th>Invoice ID</th><th>Customer</th>
                        <th>Amount</th><th>Status</th><th></th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>

        <!-- PAGINATION CONTROLS -->
        ${_viewsPaginationControls('invoices', filtered.length, _invoicesPage, INVOICES_PER_PAGE, '_changeInvoicesPage')}

        <!-- SUMMARY STRIP -->
        <div class="vsummary-strip">
            <div class="vsummary-item" onclick="sendChip('List all paid invoices')">
                <div class="vsummary-val" style="color:#27864a">${paid}</div>
                <div class="vsummary-key">Paid</div>
            </div>
            <div class="vsummary-item" onclick="sendChip('List all pending invoices')">
                <div class="vsummary-val" style="color:#b06510">${pending}</div>
                <div class="vsummary-key">Pending</div>
            </div>
            <div class="vsummary-item" onclick="sendChip('List all overdue invoices with amounts')">
                <div class="vsummary-val" style="color:#c02a2a">${overdue}</div>
                <div class="vsummary-key">Overdue</div>
            </div>
            <div class="vsummary-item" onclick="sendChip('What is my total revenue?')">
                <div class="vsummary-val">${fmtAmount(total)}</div>
                <div class="vsummary-key">Total</div>
            </div>
        </div>`;
}

function _changeInvoicesPage(newPage) {
    _invoicesPage = newPage;
    _paintInvoices(getLeft());
}

function _setInvoiceFilter(f) {
    _invoiceFilter = f;
    _invoicesPage = 1;
    _paintInvoices(getLeft());
}


/* ─── PAYMENTS ───────────────────────────── */

async function renderPaymentsView() {
    const left = getLeft();
    if (!left) return;

    console.group("%c[BizAssist View] Loading Payments...", "color: #3f51b5; font-weight: bold;");

    left.innerHTML = viewHeader('Payments', 'Dues and recovery') +
        `<div class="widget">${skeleton(4)}</div>`;

    try {
        const data = await fetch(`${API_BASE}/payments`).then(r => r.json());
        console.log("Payments detail loaded successfully:", data);
        console.groupEnd();

        const overdueList = (data.invoice_dues || [])
            .filter(p => (p.status || '').toLowerCase() === 'overdue');

        const pendingList = (data.invoice_dues || [])
            .filter(p => (p.status || '').toLowerCase() === 'pending');

        const overdueSlice = overdueList.slice(
            (_paymentsOverduePage - 1) * PAYMENTS_PER_PAGE,
            _paymentsOverduePage * PAYMENTS_PER_PAGE
        );

        const pendingSlice = pendingList.slice(
            (_paymentsPendingPage - 1) * PAYMENTS_PER_PAGE,
            _paymentsPendingPage * PAYMENTS_PER_PAGE
        );

        const overdueRows = overdueSlice.map(p => `
                <tr>
                    <td style="font-weight:500">${p.customer || '—'}</td>
                    <td>${p.invoice_id || '—'}</td>
                    <td style="font-family:'Crimson Pro',serif;font-size:15px;color:#c02a2a;font-weight:600">${fmtFull(p.amount)}</td>
                    <td style="color:var(--secondary-text);font-size:12px">${p.due_date || '—'}</td>
                    <td><button class="vlink" onclick="sendChip('How much does ${p.customer} owe me?')">Ask AI</button></td>
                </tr>`).join('');

        const pendingRows = pendingSlice.map(p => `
                <tr>
                    <td style="font-weight:500">${p.customer || '—'}</td>
                    <td>${p.invoice_id || '—'}</td>
                    <td style="font-family:'Crimson Pro',serif;font-size:15px;font-weight:600">${fmtFull(p.amount)}</td>
                    <td style="color:var(--secondary-text);font-size:12px">${p.due_date || '—'}</td>
                    <td><button class="vlink" onclick="sendChip('Tell me about pending payment from ${p.customer}')">Ask AI</button></td>
                </tr>`).join('');

        const hasDues = (data.overdue_count + data.pending_count) > 0;

        left.innerHTML = viewHeader('Payments', 'Track dues and collections') + `

            <!-- SUMMARY CARDS -->
            <div class="vstat-grid" style="grid-template-columns:1fr 1fr">
                <div class="vstat-card" style="border-left-color:#c02a2a"
                     onclick="sendChip('Show all overdue invoices with amounts')">
                    <div class="vstat-label">Overdue Amount</div>
                    <div class="vstat-value" style="color:#c02a2a">${fmtAmount(data.total_overdue)}</div>
                    <div class="vstat-sub">${data.overdue_count} invoice${data.overdue_count !== 1 ? 's' : ''}</div>
                </div>
                <div class="vstat-card" style="border-left-color:#c97c22"
                     onclick="sendChip('List all pending payments')">
                    <div class="vstat-label">Pending Amount</div>
                    <div class="vstat-value" style="color:#c97c22">${fmtAmount(data.total_pending)}</div>
                    <div class="vstat-sub">${data.pending_count} invoice${data.pending_count !== 1 ? 's' : ''}</div>
                </div>
            </div>

            ${data.overdue_count > 0 ? `
            <!-- OVERDUE TABLE -->
            <div class="widget" style="padding:0;overflow:hidden">
                <div style="padding:16px 20px 0;display:flex;align-items:center;gap:10px">
                    <div class="widget-title" style="margin:0">Overdue</div>
                    <span class="vpill" style="color:#c02a2a;background:rgba(192,42,42,0.10)">${data.overdue_count}</span>
                </div>
                <div class="vtable-wrap">
                    <table>
                        <thead><tr><th>Customer</th><th>Invoice</th><th>Amount</th><th>Due Date</th><th></th></tr></thead>
                        <tbody>${overdueRows}</tbody>
                    </table>
                </div>
                ${_viewsPaginationControls('paymentsOverdue', overdueList.length, _paymentsOverduePage, PAYMENTS_PER_PAGE, '_changePaymentsOverduePage')}
            </div>` : ''}

            ${data.pending_count > 0 ? `
            <!-- PENDING TABLE -->
            <div class="widget" style="padding:0;overflow:hidden">
                <div style="padding:16px 20px 0;display:flex;align-items:center;gap:10px">
                    <div class="widget-title" style="margin:0">Pending</div>
                    <span class="vpill" style="color:#b06510;background:rgba(176,101,16,0.10)">${data.pending_count}</span>
                </div>
                <div class="vtable-wrap">
                    <table>
                        <thead><tr><th>Customer</th><th>Invoice</th><th>Amount</th><th>Due Date</th><th></th></tr></thead>
                        <tbody>${pendingRows}</tbody>
                    </table>
                </div>
                ${_viewsPaginationControls('paymentsPending', pendingList.length, _paymentsPendingPage, PAYMENTS_PER_PAGE, '_changePaymentsPendingPage')}
            </div>` : ''}

            ${!hasDues ? emptyState('✓', 'All clear!', 'No overdue or pending payments found.') : ''}`;

    } catch (e) {
        console.error("Failed to load payments database:", e);
        console.groupEnd();
        left.innerHTML = viewHeader('Payments', '') +
            emptyState('💳', 'No payment data', 'Upload invoices with due_date column to track payments.');
    }
}

function _changePaymentsOverduePage(newPage) {
    _paymentsOverduePage = newPage;
    renderPaymentsView();
}

function _changePaymentsPendingPage(newPage) {
    _paymentsPendingPage = newPage;
    renderPaymentsView();
}


/* ─── CLIENTS ────────────────────────────── */

async function renderClientsView() {
    const left = getLeft();
    if (!left) return;

    console.group("%c[BizAssist View] Loading Clients...", "color: #3f51b5; font-weight: bold;");

    left.innerHTML = viewHeader('Clients', 'Customer overview') +
        `<div class="widget">${skeleton(5)}</div>`;

    try {
        const data = await fetch(`${API_BASE}/clients`).then(r => r.json());
        const clients = data.clients || [];

        console.log(`Loaded ${clients.length} total clients.`);
        console.groupEnd();

        if (!clients.length) {
            left.innerHTML = viewHeader('Clients', '') +
                emptyState('👥', 'No clients yet', 'Upload invoices with customer names to see your client list.');
            return;
        }

        const maxTotal = clients[0].total || 1;

        const clientSlice = clients.slice(
            (_clientsPage - 1) * CLIENTS_PER_PAGE,
            _clientsPage * CLIENTS_PER_PAGE
        );

        const clientCards = clientSlice.map((c, i) => {
            const barW = Math.round((c.total / maxTotal) * 100);
            const health = c.overdue > 0 ? 'overdue' : c.pending > 0 ? 'pending' : 'paid';
            const healthColor = { overdue: '#c02a2a', pending: '#c97c22', paid: '#27864a' }[health];
            const barColors = ['#e06535','#c97c22','#3a9a5c','#4a90c9','#9b59b6','#e91e63'];
            const absoluteIdx = (_clientsPage - 1) * CLIENTS_PER_PAGE + i;
            return `
            <div class="vclient-card" onclick="sendChip('Give me a full summary for customer ${c.customer}')">
                <div class="vclient-top">
                    <div class="vclient-avatar" style="background:${barColors[absoluteIdx % barColors.length]}22;color:${barColors[absoluteIdx % barColors.length]}">
                        ${c.customer.charAt(0).toUpperCase()}
                    </div>
                    <div class="vclient-info">
                        <div class="vclient-name">${c.customer}</div>
                        <div class="vclient-meta">${c.invoices} invoice${c.invoices !== 1 ? 's' : ''}</div>
                    </div>
                    <div class="vclient-amount">${fmtAmount(c.total)}</div>
                </div>
                <div class="vclient-bar-track">
                    <div class="vclient-bar-fill" style="width:${barW}%;background:${barColors[absoluteIdx % barColors.length]}"></div>
                </div>
                <div class="vclient-pills">
                    ${c.paid    > 0 ? `<span class="vpill" style="color:#27864a;background:rgba(39,134,74,0.10)">${c.paid} paid</span>` : ''}
                    ${c.pending > 0 ? `<span class="vpill" style="color:#b06510;background:rgba(176,101,16,0.10)">${c.pending} pending</span>` : ''}
                    ${c.overdue > 0 ? `<span class="vpill" style="color:#c02a2a;background:rgba(192,42,42,0.10)">${c.overdue} overdue</span>` : ''}
                    <span class="vlink" style="margin-left:auto">Ask AI →</span>
                </div>
            </div>`;
        }).join('');

        left.innerHTML = viewHeader('Clients', `${clients.length} customers tracked`, clients.length) + `
            <div class="vclient-grid">${clientCards}</div>
            ${_viewsPaginationControls('clients', clients.length, _clientsPage, CLIENTS_PER_PAGE, '_changeClientsPage')}`;

    } catch (e) {
        console.error("Failed to load clients database:", e);
        console.groupEnd();
        left.innerHTML = viewHeader('Clients', '') +
            emptyState('👥', 'No clients yet', 'Upload invoices to see your client list.');
    }
}

function _changeClientsPage(newPage) {
    _clientsPage = newPage;
    renderClientsView();
}
