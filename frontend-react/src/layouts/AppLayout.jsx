import { useState, useEffect, useRef } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'
import { API_BASE } from '../config'
import Chat from '../pages/Chat'
import InsightsPanel from '../components/InsightsPanel'

const NAV = [
  { to: '/chat',      id: 'ai-btn',       label: 'AI Assistant', icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg> },
  { to: '/dashboard', id: 'dashboard-btn', label: 'Dashboard',    icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9"></rect><rect x="14" y="3" width="7" height="5"></rect><rect x="14" y="12" width="7" height="9"></rect><rect x="3" y="16" width="7" height="5"></rect></svg> },
  { to: '/invoices',  id: 'invoices-btn',  label: 'Invoices',     icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg> },
  { to: '/payments',  id: 'payments-btn',  label: 'Payments',     icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="4" width="20" height="16" rx="2" ry="2"></rect><line x1="2" y1="10" x2="22" y2="10"></line></svg> },
  { to: '/clients',   id: 'clients-btn',   label: 'Clients',      icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path></svg> },
  { to: '/alerts',    id: 'alerts-btn',    label: 'Alerts',       icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg> },
  { to: '/database',  id: 'db-btn',        label: 'Database Viewer', icon: <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"></path></svg> },
]

export default function AppLayout() {
  const { user, logout, authFetch } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  // Panel collapsed/open states
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => localStorage.getItem('sidebar_collapsed') === 'true')
  const [insightsCollapsed, setInsightsCollapsed] = useState(() => localStorage.getItem('insights_collapsed') === 'true')
  const [isMounting, setIsMounting] = useState(true)

  // Mobile layout open states
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [mobileInsightsOpen, setMobileInsightsOpen] = useState(false)
  const [mobileAssistantOpen, setMobileAssistantOpen] = useState(false)

  // Profile menus
  const [showProfileMenu, setShowProfileMenu] = useState(false)
  const [showMobileProfileMenu, setShowMobileProfileMenu] = useState(false)

  // Business renaming
  const [bizName, setBizName] = useState(() => localStorage.getItem('biz_name') || user?.business_name || 'My Business')
  const [isRenaming, setIsRenaming] = useState(false)
  const [tempBizName, setTempBizName] = useState(bizName)

  // Sync with user business name if loaded/updated
  useEffect(() => {
    if (user?.business_name && !localStorage.getItem('biz_name')) {
      setBizName(user.business_name)
      setTempBizName(user.business_name)
    }
  }, [user])

  // Theme settings
  const [theme, setTheme] = useState(() => localStorage.getItem('theme') || 'system')

  // Summary stats cards
  const [stats, setStats] = useState({ total_revenue: 0, pending_invoices: 0, invoice_count: 0 })

  // Alerts preference modal
  const [showAlertsModal, setShowAlertsModal] = useState(false)
  const [alertsStatus, setAlertsStatus] = useState('')
  const [alertsForm, setAlertsForm] = useState({
    active: false,
    email: '',
    whatsapp: '',
    overdue: true,
    lowStock: true,
    lowStockThresh: 10,
    expiry: true,
    expiryThresh: 30,
    dailySummary: true
  })

  const isFirstThemeRun = useRef(true);

  // Theme effect
  const applyTheme = (t, animate = true) => {
    if (animate) {
      document.body.classList.add("theme-animating");
    }
    document.documentElement.classList.remove("dark-mode");
    if (t === "dark") {
      document.documentElement.classList.add("dark-mode");
    } else if (t === "system") {
      if (window.matchMedia("(prefers-color-scheme: dark)").matches) {
        document.documentElement.classList.add("dark-mode");
      }
    }
    if (animate) {
      setTimeout(() => {
        document.body.classList.remove("theme-animating");
      }, 220);
    }
  };

  useEffect(() => {
    if (isFirstThemeRun.current) {
      applyTheme(theme, false);
      isFirstThemeRun.current = false;
    } else {
      applyTheme(theme, true);
    }
    localStorage.setItem("theme", theme);
  }, [theme]);

  // Listen for system theme preferences changes if theme is "system"
  useEffect(() => {
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (e) => {
      if (e.matches) {
        document.documentElement.classList.add("dark-mode");
      } else {
        document.documentElement.classList.remove("dark-mode");
      }
    };
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  // Fetch summary stats
  const loadSummaryStats = async () => {
    try {
      const res = await authFetch(`${API_BASE}/dashboard-summary`);
      if (res.ok) {
        const data = await res.json();
        setStats({
          total_revenue: data.total_revenue || 0,
          pending_invoices: data.pending_invoices || 0,
          invoice_count: data.invoice_count || 0
        });
      }
    } catch (e) {
      console.error("Failed to load dashboard summary stats:", e);
    }
  };

  useEffect(() => {
    loadSummaryStats();
    
    const timer = setTimeout(() => {
      setIsMounting(false);
    }, 100);
    
    // Add event listener for data updates
    const handleDataUpdated = () => {
      loadSummaryStats();
    };
    window.addEventListener("data-updated", handleDataUpdated);

    // Add event listener for AI chip shortcuts — keep on current page, open mobile drawer
    const handleAiShortcut = (e) => {
      if (e.detail?.query) {
        sessionStorage.setItem('prefill_query', e.detail.query);
      }
      setMobileAssistantOpen(true);
    };
    window.addEventListener("ai-shortcut", handleAiShortcut);

    return () => {
      clearTimeout(timer);
      window.removeEventListener("data-updated", handleDataUpdated);
      window.removeEventListener("ai-shortcut", handleAiShortcut);
    };
  }, []);

  // Listen to path changes to set data-active and sync title
  useEffect(() => {
    const path = location.pathname;
    let name = 'ai';
    if (path.startsWith('/dashboard')) name = 'dashboard';
    else if (path.startsWith('/invoices')) name = 'invoices';
    else if (path.startsWith('/payments')) name = 'payments';
    else if (path.startsWith('/clients')) name = 'clients';
    else if (path.startsWith('/database')) name = 'database';
    else if (path.startsWith('/upload')) name = 'uploads';
    else if (path.startsWith('/alerts')) name = 'alerts';
    else if (path.startsWith('/chat')) name = 'ai';
    else name = '';

    document.documentElement.setAttribute('data-active', name);
    closeAllMobilePanels();
  }, [location.pathname]);

  // Sync biz_name dynamically when updated elsewhere
  useEffect(() => {
    const handleBizNameChange = (e) => {
      if (e.detail) {
        setBizName(e.detail);
        setTempBizName(e.detail);
      }
    };
    window.addEventListener('biz-name-updated', handleBizNameChange);
    return () => window.removeEventListener('biz-name-updated', handleBizNameChange);
  }, []);

  function handleLogout() {
    logout()
    navigate('/login')
  }

  // Toggles
  function toggleSidebar() {
    const val = !sidebarCollapsed;
    setSidebarCollapsed(val);
    localStorage.setItem('sidebar_collapsed', val);
  }

  function toggleInsights() {
    const val = !insightsCollapsed;
    setInsightsCollapsed(val);
    localStorage.setItem('insights_collapsed', val);
  }

  function closeAllMobilePanels() {
    setMobileSidebarOpen(false);
    setMobileInsightsOpen(false);
    setMobileAssistantOpen(false);
  }

  // Rename Business
  function commitRename() {
    const val = tempBizName.trim() || 'My Business';
    setBizName(val);
    localStorage.setItem('biz_name', val);
    setIsRenaming(false);
    window.dispatchEvent(new CustomEvent('biz-name-updated', { detail: val }));
  }

  // Alerts save / load
  const loadAlertConfigs = async () => {
    try {
      const res = await authFetch(`${API_BASE}/alerts/config`);
      if (res.ok) {
        const data = await res.json();
        setAlertsForm({
          active: !!data.active,
          email: data.email || '',
          whatsapp: data.whatsapp_number || '',
          overdue: !!data.alert_overdue,
          lowStock: !!data.alert_low_stock,
          lowStockThresh: data.low_stock_threshold || 10,
          expiry: !!data.alert_expiry,
          expiryThresh: data.expiry_days_threshold || 30,
          dailySummary: !!data.alert_daily_summary
        });
      } else {
        setAlertsForm({
          active: false,
          email: user?.email || '',
          whatsapp: '',
          overdue: true,
          lowStock: true,
          lowStockThresh: 10,
          expiry: true,
          expiryThresh: 30,
          dailySummary: true
        });
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleOpenAlerts = () => {
    setAlertsStatus('');
    loadAlertConfigs();
    setShowAlertsModal(true);
    setShowProfileMenu(false);
    setShowMobileProfileMenu(false);
  };

  const saveAlertPreferences = async () => {
    if (alertsForm.active) {
      if (!alertsForm.email.trim()) {
        setAlertsStatus('Email is required to enable alerts.');
        return;
      }
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
      if (!emailRegex.test(alertsForm.email)) {
        setAlertsStatus('Please enter a valid email address.');
        return;
      }
    }

    setAlertsStatus('Saving preferences...');

    try {
      const res = await authFetch(`${API_BASE}/alerts/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: alertsForm.email || null,
          whatsapp_number: alertsForm.whatsapp || null,
          alert_overdue: alertsForm.overdue,
          alert_low_stock: alertsForm.lowStock,
          alert_expiry: alertsForm.expiry,
          alert_daily_summary: alertsForm.dailySummary,
          low_stock_threshold: parseInt(alertsForm.lowStockThresh) || 10,
          expiry_days_threshold: parseInt(alertsForm.expiryThresh) || 30,
          active: alertsForm.active
        })
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Save failed');
      }
      setAlertsStatus('Settings saved successfully!');
      setTimeout(() => {
        setShowAlertsModal(false);
      }, 1200);
    } catch (err) {
      setAlertsStatus(err.message || 'Failed to save settings.');
    }
  };

  const sendTestAlertEmail = async () => {
    setAlertsStatus('Sending test email...');
    try {
      const res = await authFetch(`${API_BASE}/alerts/test/daily_summary`, {
        method: 'POST'
      });
      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || 'Test trigger failed');
      }
      setAlertsStatus('Test email sent successfully!');
    } catch (err) {
      setAlertsStatus(err.message || 'Failed to send test email.');
    }
  };

  // Close dropdowns on clicking outside
  useEffect(() => {
    const handleGlobalClick = () => {
      setShowProfileMenu(false);
      setShowMobileProfileMenu(false);
    };
    window.addEventListener('click', handleGlobalClick);
    return () => window.removeEventListener('click', handleGlobalClick);
  }, []);

  const initials = bizName.charAt(0).toUpperCase() || 'M';

  return (
    <div className="app">
      {/* MOBILE NAVBAR */}
      <div className="mobile-navbar">
        <button className="mobile-nav-btn mobile-sidebar-toggle" onClick={(e) => { e.stopPropagation(); setMobileSidebarOpen(true); }} title="Toggle Sidebar">
          <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
            <line x1="9" y1="3" x2="9" y2="21"></line>
          </svg>
        </button>
        <div className="mobile-navbar-title">{bizName.toUpperCase()}</div>
        <div className="mobile-navbar-right">
          <button
            className="mobile-nav-btn mobile-insights-toggle"
            id="mobile-insights-toggle"
            onClick={(e) => { e.stopPropagation(); setMobileInsightsOpen(true); }}
            title="Toggle Insights"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2"></rect>
              <line x1="15" y1="3" x2="15" y2="21"></line>
            </svg>
          </button>
          <div className="profile-badge-wrap mobile-profile" onClick={(e) => { e.stopPropagation(); setShowMobileProfileMenu(!showMobileProfileMenu); }}>
            <div className="profile-badge-circle">{initials}</div>
            
            {showMobileProfileMenu && (
              <div className="profile-menu" id="mobileProfileMenu" style={{ display: 'block' }}>
                <div className="profile-menu-header">
                  <div className="profile-menu-biz">{bizName}</div>
                  <div className="profile-menu-sub">Enterprise Account</div>
                </div>
                <div className="profile-menu-sep"></div>
                <div className="profile-menu-item" onClick={(e) => { e.stopPropagation(); setIsRenaming(true); setShowMobileProfileMenu(false); }}>✏ Rename Business</div>
                <div className="profile-menu-item" onClick={handleOpenAlerts}>🔔 Alert Settings</div>
                <div className="profile-menu-item logout" onClick={handleLogout}>➔ Sign Out</div>
                <div className="profile-menu-sep"></div>
                <div className="profile-menu-theme" onClick={(e) => e.stopPropagation()}>
                  <span className="profile-menu-theme-label">Theme</span>
                  <div className="profile-theme-toggle">
                    <button className={`theme-opt-btn light-opt ${theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')} title="Light mode">☀</button>
                    <button className={`theme-opt-btn dark-opt ${theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')} title="Dark mode">☾</button>
                    <button className={`theme-opt-btn system-opt ${theme === 'system' ? 'active' : ''}`} onClick={() => setTheme('system')} title="System theme">◐</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* SIDEBAR */}
      <div className={`sidebar ${sidebarCollapsed ? 'collapsed' : ''} ${mobileSidebarOpen ? 'mobile-open' : ''} ${isMounting ? 'no-transition' : ''}`} id="sidebar-nav">
        <div className="sidebar-header">
          <div className="sidebar-brand-text">BizAssist</div>
          <button className="sidebar-toggle-btn matte-glass" onClick={() => {
            if (window.matchMedia('(max-width: 1024px)').matches) {
              setMobileSidebarOpen(false);
            } else {
              toggleSidebar();
            }
          }} title="Toggle Sidebar">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
              <line x1="9" y1="3" x2="9" y2="21"></line>
            </svg>
          </button>
        </div>

        <div className="sidebar-sep"></div>

        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} id={n.id} className={({ isActive }) => `matte-glass ${isActive ? 'active' : ''}`}>
            {n.icon}
            <span className="sidebar-text">{n.label}</span>
          </NavLink>
        ))}

        <div className="sidebar-footer">
          <div className="profile-badge-wrap" onClick={(e) => { e.stopPropagation(); setShowProfileMenu(!showProfileMenu); }}>
            <div className="profile-badge-circle" id="profile-badge-initials">{initials}</div>
            
            {isRenaming ? (
              <input
                value={tempBizName}
                onChange={e => setTempBizName(e.target.value)}
                onBlur={commitRename}
                onKeyDown={e => {
                  if (e.key === 'Enter') commitRename();
                  if (e.key === 'Escape') { setTempBizName(bizName); setIsRenaming(false); }
                }}
                onClick={(e) => e.stopPropagation()}
                autoFocus
                style={{
                  fontFamily: 'inherit', fontSize: 'inherit', fontWeight: 'inherit',
                  letterSpacing: 'inherit', color: 'var(--accent-color)', background: 'transparent',
                  border: 'none', borderBottom: '1.5px solid var(--accent-color)',
                  outline: 'none', width: '100px', padding: 0, maxWidth: '110px'
                }}
              />
            ) : (
              <span className="sidebar-text profile-biz-name-text" id="biz-name" title="Click to rename" onClick={(e) => { e.stopPropagation(); setIsRenaming(true); }}>
                {bizName}
              </span>
            )}

            {showProfileMenu && (
              <div className="profile-menu" id="profileMenu" style={{ display: 'block' }}>
                <div className="profile-menu-header">
                  <div className="profile-menu-biz" id="profile-menu-biz-name">{bizName}</div>
                  <div className="profile-menu-sub">Enterprise Account</div>
                </div>
                <div className="profile-menu-sep"></div>
                <div className="profile-menu-item" onClick={(e) => { e.stopPropagation(); setIsRenaming(true); setShowProfileMenu(false); }}>✏ Rename Business</div>
                <div className="profile-menu-item" onClick={handleOpenAlerts}>🔔 Alert Settings</div>
                <div className="profile-menu-item logout" onClick={handleLogout}>➔ Sign Out</div>
                <div className="profile-menu-sep"></div>
                <div className="profile-menu-theme" onClick={(e) => e.stopPropagation()}>
                  <span className="profile-menu-theme-label">Theme</span>
                  <div className="profile-theme-toggle">
                    <button className={`theme-opt-btn light-opt ${theme === 'light' ? 'active' : ''}`} onClick={() => setTheme('light')} title="Light mode">☀</button>
                    <button className={`theme-opt-btn dark-opt ${theme === 'dark' ? 'active' : ''}`} onClick={() => setTheme('dark')} title="Dark mode">☾</button>
                    <button className={`theme-opt-btn system-opt ${theme === 'system' ? 'active' : ''}`} onClick={() => setTheme('system')} title="System theme">◐</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* MAIN CONTENT AREA */}
      <div className="main">
        {/* CARDS (visible on all non-AI views) */}
        {location.pathname !== '/chat' && (
          <div className="cards">
            <div className="card">
              <span className="card-icon">₹</span>
              <h3>Total Revenue</h3>
              <p id="total-revenue">₹{Number(stats.total_revenue).toLocaleString('en-IN')}</p>
            </div>
            <div className="card">
              <span className="card-icon">⏳</span>
              <h3>Pending Payments</h3>
              <p id="pending-payments">{stats.pending_invoices}</p>
            </div>
            <div className="card">
              <span className="card-icon">📋</span>
              <h3>Invoices</h3>
              <p id="invoice-count">{stats.invoice_count}</p>
            </div>
          </div>
        )}

        {/* SIDE BY SIDE GRID */}
        <div className={`dashboard-grid ${insightsCollapsed ? 'insights-collapsed' : ''} ${isMounting ? 'no-transition' : ''}`}>
          {/* Left Column: Active Page Component */}
          <div
            id="dashboard-left"
            className="dashboard-left"
            style={{
              display: location.pathname === '/chat' ? 'none' : 'flex',
              flexDirection: 'column'
            }}
          >
            <Outlet />
          </div>

          {/* AI Assistant Chat panel (Always mounted, gridColumn handled by CSS) */}
          <Chat
            isFullWidth={location.pathname === '/chat'}
            mobileOpen={mobileAssistantOpen}
            onCloseMobile={() => setMobileAssistantOpen(false)}
          />

          {/* Collapsible Insights panel (Only visible on /chat, always mounted, display/gridColumn handled by CSS) */}
          {location.pathname === '/chat' && (
            <div
              id="insights-panel"
              className={`sidebar rp-sidebar ${insightsCollapsed ? 'collapsed' : ''} ${mobileInsightsOpen ? 'mobile-open' : ''} ${isMounting ? 'no-transition' : ''}`}
            >
              <InsightsPanel
                onCollapse={toggleInsights}
                onCloseMobile={() => setMobileInsightsOpen(false)}
              />
            </div>
          )}
        </div>
      </div>

      {/* ALERTS PREFERENCES MODAL */}
      {showAlertsModal && (
        <div id="alerts-modal" className="alerts-modal-overlay" onClick={() => setShowAlertsModal(false)}>
          <div className="alerts-modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="alerts-modal-header">
              <span className="alerts-modal-title">🔔 Proactive Alert Settings</span>
              <button className="alerts-modal-close" onClick={() => setShowAlertsModal(false)} title="Close">×</button>
            </div>
            
            <div className="alerts-modal-body">
              <div className="alerts-toggle-row">
                <label className="alerts-switch-label" htmlFor="alerts-active-toggle">Enable Email Alerts</label>
                <label className="alerts-switch">
                  <input
                    type="checkbox"
                    id="alerts-active-toggle"
                    checked={alertsForm.active}
                    onChange={(e) => setAlertsForm(prev => ({ ...prev, active: e.target.checked }))}
                  />
                  <span className="alerts-slider"></span>
                </label>
              </div>

              {alertsForm.active && (
                <div id="alerts-settings-section" className="alerts-settings-section">
                  <div className="alerts-form-group">
                    <label htmlFor="alerts-email">Recipient Email Address</label>
                    <input
                      type="email"
                      id="alerts-email"
                      placeholder="e.g. owner@business.com"
                      value={alertsForm.email}
                      onChange={(e) => setAlertsForm(prev => ({ ...prev, email: e.target.value }))}
                    />
                  </div>
                  
                  <div className="alerts-form-group">
                    <label htmlFor="alerts-whatsapp" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      WhatsApp Number <span style={{ fontSize: 11, opacity: 0.6 }}>(Optional, with country code)</span>
                    </label>
                    <input
                      type="text"
                      id="alerts-whatsapp"
                      placeholder="e.g. +919876543210"
                      value={alertsForm.whatsapp}
                      onChange={(e) => setAlertsForm(prev => ({ ...prev, whatsapp: e.target.value }))}
                    />
                  </div>
                  
                  <div className="alerts-section-title" style={{ fontWeight: 600, marginTop: 12 }}>Alert Categories</div>
                  
                  <div className="alerts-checkbox-row">
                    <label className="alerts-checkbox-label">
                      <input
                        type="checkbox"
                        id="alerts-overdue"
                        checked={alertsForm.overdue}
                        onChange={(e) => setAlertsForm(prev => ({ ...prev, overdue: e.target.checked }))}
                      /> Overdue Invoice Warnings
                    </label>
                    <span className="alerts-desc">Get notified when invoices cross their due date.</span>
                  </div>

                  <div className="alerts-checkbox-row">
                    <label className="alerts-checkbox-label">
                      <input
                        type="checkbox"
                        id="alerts-low-stock"
                        checked={alertsForm.lowStock}
                        onChange={(e) => setAlertsForm(prev => ({ ...prev, lowStock: e.target.checked }))}
                      /> Low Stock Warnings
                    </label>
                    <span className="alerts-desc">Get warned when products drop below threshold.</span>
                    {alertsForm.lowStock && (
                      <div className="alerts-sub-input" id="alerts-low-stock-threshold-group">
                        <label htmlFor="alerts-low-stock-threshold">Low stock threshold: </label>
                        <input
                          type="number"
                          id="alerts-low-stock-threshold"
                          min="1"
                          max="999"
                          value={alertsForm.lowStockThresh}
                          onChange={(e) => setAlertsForm(prev => ({ ...prev, lowStockThresh: e.target.value }))}
                          style={{ width: 60, marginLeft: 8 }}
                        /> units
                      </div>
                    )}
                  </div>

                  <div className="alerts-checkbox-row">
                    <label className="alerts-checkbox-label">
                      <input
                        type="checkbox"
                        id="alerts-expiry"
                        checked={alertsForm.expiry}
                        onChange={(e) => setAlertsForm(prev => ({ ...prev, expiry: e.target.checked }))}
                      /> Expiry Warnings
                    </label>
                    <span className="alerts-desc">Get notified of medicines/products expiring soon.</span>
                    {alertsForm.expiry && (
                      <div className="alerts-sub-input" id="alerts-expiry-threshold-group">
                        <label htmlFor="alerts-expiry-threshold">Days before expiry to warn: </label>
                        <input
                          type="number"
                          id="alerts-expiry-threshold"
                          min="1"
                          max="365"
                          value={alertsForm.expiryThresh}
                          onChange={(e) => setAlertsForm(prev => ({ ...prev, expiryThresh: e.target.value }))}
                          style={{ width: 60, marginLeft: 8 }}
                        /> days
                      </div>
                    )}
                  </div>

                  <div className="alerts-checkbox-row">
                    <label className="alerts-checkbox-label">
                      <input
                        type="checkbox"
                        id="alerts-daily-summary"
                        checked={alertsForm.dailySummary}
                        onChange={(e) => setAlertsForm(prev => ({ ...prev, dailySummary: e.target.checked }))}
                      /> Daily Business Summary
                    </label>
                    <span className="alerts-desc">Receive a morning digest at 08:00 IST detailing sales & inventory health.</span>
                  </div>
                </div>
              )}
            </div>
            
            <div className="alerts-modal-footer">
              <div id="alerts-save-status" className="alerts-save-status" style={{
                color: alertsStatus.includes('success') ? '#27864a' : alertsStatus.includes('failed') || alertsStatus.includes('required') || alertsStatus.includes('valid') ? '#c02a2a' : 'var(--secondary-text)'
              }}>{alertsStatus}</div>
              {alertsForm.active && (
                <button id="alerts-test-btn" className="alerts-btn-secondary" style={{ marginRight: 6 }} onClick={sendTestAlertEmail}>Send Test</button>
              )}
              <button className="alerts-btn-secondary" onClick={() => setShowAlertsModal(false)}>Cancel</button>
              <button className="alerts-btn-primary" onClick={saveAlertPreferences}>Save Preferences</button>
            </div>
          </div>
        </div>
      )}

      {/* MOBILE OVERLAY BACKDROP */}
      {(mobileSidebarOpen || mobileInsightsOpen || mobileAssistantOpen) && (
        <div className="mobile-overlay active" id="mobile-overlay" onClick={closeAllMobilePanels}></div>
      )}

      {/* FLOATING ACTION BUTTON FOR AI ASSISTANT */}
      {location.pathname !== '/chat' && (
        <button
          className="mobile-assistant-toggle"
          id="mobile-assistant-toggle"
          onClick={() => setMobileAssistantOpen(true)}
          title="Toggle AI Assistant"
        >
          ✦
        </button>
      )}
    </div>
  )
}
