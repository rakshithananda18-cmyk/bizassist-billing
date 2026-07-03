import Reveal from './Reveal'
import { useLatestRelease, detectOS, RELEASES_PAGE } from './useLatestRelease'

/* ────────────────────────── tiny inline icons ───────────────────────── */
const Icon = {
  bolt: (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-6 w-6">
      <path d="M13 2 4.5 13.5H11L10 22l8.5-11.5H12L13 2z" />
    </svg>
  ),
  offline: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3" strokeLinecap="round" />
      <circle cx="12" cy="12" r="5.2" />
      <path d="M12 9.5v2.8l1.8 1.4" strokeLinecap="round" />
    </svg>
  ),
  sync: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
      <path d="M4 12a8 8 0 0 1 13.6-5.7L20 8.5M20 12a8 8 0 0 1-13.6 5.7L4 15.5" strokeLinecap="round" />
      <path d="M20 4v4.5h-4.5M4 20v-4.5h4.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  shield: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
      <path d="M12 3 5 6v5c0 4.5 3 8.4 7 10 4-1.6 7-5.5 7-10V6l-7-3z" strokeLinejoin="round" />
      <path d="m9.2 12 2 2 3.6-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
  chart: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
      <path d="M4 20h16M7 16v-5M12 16V7M17 16v-8" strokeLinecap="round" />
    </svg>
  ),
  update: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6">
      <path d="M12 3v10m0 0 3.5-3.5M12 13 8.5 9.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 17a8 8 0 0 0 16 0" strokeLinecap="round" />
    </svg>
  ),
  windows: (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
      <path d="M3 5.5 10.5 4.4v7.1H3V5.5zm0 13 7.5 1.1v-7H3v5.9zM11.5 4.2 21 3v8.5h-9.5V4.2zm0 15.6L21 21v-8.5h-9.5v7.3z" />
    </svg>
  ),
  apple: (
    <svg viewBox="0 0 24 24" fill="currentColor" className="h-5 w-5">
      <path d="M16.7 12.9c0-2.4 2-3.6 2-3.6-1.1-1.6-2.9-1.8-3.5-1.9-1.5-.1-2.9.9-3.6.9-.8 0-1.9-.9-3.2-.8-1.6 0-3.1 1-4 2.4-1.7 2.9-.4 7.3 1.2 9.7.8 1.2 1.8 2.5 3 2.4 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8 2.2-1.2 3-2.3c.9-1.4 1.3-2.7 1.3-2.8-.1 0-2.6-1-2.6-4zM14.4 5.6c.7-.8 1.1-2 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.4z" />
    </svg>
  ),
}

/* ────────────────────────────── logo mark ───────────────────────────── */
function LogoMark({ size = 'h-8 w-8' }) {
  return (
    <div className={`${size} relative grid place-items-center rounded-xl bg-gradient-to-br from-electric-500 to-indigo-600 shadow-lg shadow-electric-600/30`}>
      <span className="text-sm font-black text-white">B</span>
      <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full bg-amber-400 shadow shadow-amber-400/60" />
    </div>
  )
}

/* ──────────────────────────── download button ───────────────────────── */
function DownloadButtons({ large = false }) {
  const rel = useLatestRelease()
  const os = detectOS()

  const primary =
    os === 'mac'
      ? { label: 'Download for macOS', href: rel.mac, icon: Icon.apple }
      : { label: 'Download for Windows', href: rel.windows, icon: Icon.windows }
  const secondary =
    os === 'mac'
      ? { label: 'Windows', href: rel.windows, icon: Icon.windows }
      : { label: 'macOS', href: rel.mac, icon: Icon.apple }

  return (
    <div className={`flex flex-wrap items-center gap-4 ${large ? 'justify-center' : ''}`}>
      <a
        href={primary.href || rel.fallback}
        className={`btn-sheen group inline-flex items-center gap-3 rounded-2xl bg-gradient-to-r from-electric-500 to-indigo-600 font-semibold text-white shadow-xl shadow-electric-600/30 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-2xl hover:shadow-electric-500/40 ${
          large ? 'px-8 py-4 text-lg' : 'px-6 py-3.5'
        }`}
      >
        {primary.icon}
        {primary.label}
        {rel.version && (
          <span className="rounded-full bg-white/20 px-2 py-0.5 text-xs font-bold">v{rel.version}</span>
        )}
      </a>
      <a
        href={secondary.href || rel.fallback}
        className="glass inline-flex items-center gap-2 rounded-2xl px-5 py-3.5 font-medium text-slate-200 transition-all duration-300 hover:-translate-y-0.5 hover:border-white/25 hover:bg-white/10"
      >
        {secondary.icon}
        {secondary.label}
      </a>
      <a
        href={RELEASES_PAGE}
        className="text-sm text-slate-400 underline-offset-4 transition hover:text-slate-200 hover:underline"
      >
        All downloads →
      </a>
    </div>
  )
}

/* ─────────────────────────── hero app mockup ────────────────────────── */
function AppMockup() {
  const rows = [
    ['#INV-2041', 'Sharma Traders', '₹12,480', 'Paid'],
    ['#INV-2040', 'Café Nirvana', '₹3,150', 'Paid'],
    ['#INV-2039', 'Patel & Sons', '₹28,900', 'Due'],
    ['#INV-2038', 'GreenLeaf Mart', '₹7,620', 'Paid'],
  ]
  return (
    <div className="glass-strong relative mx-auto w-full max-w-4xl rounded-2xl p-2 shadow-2xl shadow-black/50">
      {/* window chrome */}
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="h-3 w-3 rounded-full bg-rose-400/90" />
        <span className="h-3 w-3 rounded-full bg-amber-400/90" />
        <span className="h-3 w-3 rounded-full bg-emerald-400/90" />
        <span className="ml-3 text-xs font-medium text-slate-400">BizAssist — Billing Counter</span>
        <span className="ml-auto flex items-center gap-1.5 rounded-full bg-emerald-400/10 px-2.5 py-1 text-[10px] font-bold text-emerald-300">
          <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-emerald-400" /> OFFLINE READY
        </span>
      </div>

      <div className="flex overflow-hidden rounded-xl bg-ink-900/90">
        {/* sidebar */}
        <div className="hidden w-44 shrink-0 flex-col gap-1 border-r border-white/5 p-3 sm:flex">
          <div className="mb-2 flex items-center gap-2 px-2">
            <LogoMark size="h-6 w-6" />
            <span className="text-xs font-bold text-white">BizAssist</span>
          </div>
          {['Home', 'Dashboard', 'Dashboard BIZASSIST', 'Billing Counter', 'Transactions', 'Inventory', 'GST Reports'].map(
            (item, i) => (
              <div
                key={item}
                className={`rounded-lg px-2.5 py-1.5 text-[11px] font-medium ${
                  i === 3
                    ? 'bg-electric-500/20 text-electric-400'
                    : i === 2
                      ? 'text-amber-300/90'
                      : 'text-slate-400'
                }`}
              >
                {item}
              </div>
            )
          )}
        </div>

        {/* main panel */}
        <div className="flex-1 p-4">
          <div className="mb-4 grid grid-cols-3 gap-3">
            {[
              ["Today's Sales", '₹52,150', 'text-emerald-300'],
              ['Invoices', '38', 'text-electric-400'],
              ['Dues Pending', '₹28,900', 'text-amber-300'],
            ].map(([k, v, c]) => (
              <div key={k} className="glass rounded-xl p-3">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">{k}</div>
                <div className={`mt-1 text-lg font-extrabold ${c}`}>{v}</div>
              </div>
            ))}
          </div>

          {/* mini bar chart */}
          <div className="glass mb-4 flex h-24 items-end gap-1.5 rounded-xl p-3">
            {[38, 52, 44, 65, 58, 80, 72, 90, 68, 84, 76, 95].map((h, i) => (
              <div
                key={i}
                style={{ height: `${h}%` }}
                className="flex-1 rounded-t bg-gradient-to-t from-electric-600/70 to-electric-400"
              />
            ))}
          </div>

          <div className="overflow-hidden rounded-xl border border-white/5">
            {rows.map(([id, name, amt, status], i) => (
              <div
                key={id}
                className={`flex items-center gap-3 px-3 py-2 text-[11px] ${i % 2 ? 'bg-white/[0.02]' : ''}`}
              >
                <span className="font-mono text-slate-500">{id}</span>
                <span className="flex-1 font-medium text-slate-300">{name}</span>
                <span className="font-bold text-slate-200">{amt}</span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${
                    status === 'Paid' ? 'bg-emerald-400/10 text-emerald-300' : 'bg-amber-400/10 text-amber-300'
                  }`}
                >
                  {status}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* glow under the mockup */}
      <div className="absolute -bottom-10 left-1/2 -z-10 h-24 w-3/4 -translate-x-1/2 rounded-full bg-electric-600/30 blur-3xl" />
    </div>
  )
}

/* ────────────────────────────── sections ────────────────────────────── */
function Navbar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <nav className="glass mx-auto mt-4 flex max-w-6xl items-center gap-6 rounded-2xl px-5 py-3">
        <a href="#" className="flex items-center gap-2.5">
          <LogoMark />
          <span className="text-lg font-extrabold tracking-tight text-white">
            Biz<span className="text-electric-400">Assist</span>
          </span>
        </a>
        <div className="ml-auto hidden items-center gap-7 text-sm font-medium text-slate-300 md:flex">
          <a href="#features" className="transition hover:text-white">Features</a>
          <a href="#how" className="transition hover:text-white">How it works</a>
          <a href={RELEASES_PAGE} className="transition hover:text-white">Releases</a>
        </div>
        <a
          href="#download"
          className="ml-auto rounded-xl bg-gradient-to-r from-electric-500 to-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-electric-600/25 transition hover:brightness-110 md:ml-0"
        >
          Download
        </a>
      </nav>
    </header>
  )
}

function Hero() {
  return (
    <section className="relative overflow-hidden pt-36 pb-24">
      {/* ambient orbs */}
      <div className="pointer-events-none absolute -top-32 left-1/4 h-96 w-96 animate-float-slow rounded-full bg-electric-600/25 blur-[110px]" />
      <div className="pointer-events-none absolute top-24 right-1/5 h-80 w-80 animate-float-slower rounded-full bg-indigo-600/20 blur-[100px]" />
      <div className="absolute inset-0 -z-10 bg-grid" />

      <div className="mx-auto max-w-6xl px-6 text-center">
        <Reveal>
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-semibold text-electric-400">
            <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-electric-400" />
            Now with silent auto-updates & AI insights
          </span>
        </Reveal>

        <Reveal delay={100}>
          <h1 className="mx-auto mt-7 max-w-4xl text-5xl font-black leading-[1.06] tracking-tight md:text-7xl">
            <span className="text-gradient">Billing at the speed</span>
            <br />
            <span className="text-white">of your counter.</span>
          </h1>
        </Reveal>

        <Reveal delay={200}>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-400">
            BizAssist is the offline-first billing & POS desktop app for serious retailers.
            Sub-second invoicing, GST reports, inventory and dues — with hybrid cloud sync
            backing up every keystroke. No internet? No problem.
          </p>
        </Reveal>

        <Reveal delay={300} className="mt-10">
          <div id="download" className="flex justify-center">
            <DownloadButtons large />
          </div>
          <p className="mt-4 text-xs text-slate-500">Free download · Windows 10/11 & macOS · Auto-updates forever</p>
        </Reveal>

        <Reveal delay={450} className="mt-16">
          <AppMockup />
        </Reveal>
      </div>
    </section>
  )
}

const FEATURES = [
  {
    icon: Icon.bolt,
    title: 'Sub-second execution',
    body: 'The entire engine runs natively on your machine. Invoices open, price lookups resolve and receipts print in milliseconds — even with years of history.',
    accent: 'text-amber-300 bg-amber-400/10',
  },
  {
    icon: Icon.offline,
    title: '100% offline uptime',
    body: 'Power cut the internet, not your counter. Every feature — billing, inventory, dues, reports — works fully offline. Your data lives with you, not in someone else’s cloud.',
    accent: 'text-emerald-300 bg-emerald-400/10',
  },
  {
    icon: Icon.sync,
    title: 'Hybrid cloud sync',
    body: 'When you’re online, changes stream to a secure cloud backup in the background. Switch devices, recover instantly, or run a LAN of counters off one master.',
    accent: 'text-electric-400 bg-electric-500/10',
  },
  {
    icon: Icon.chart,
    title: 'AI-powered dashboard',
    body: 'Dashboard BIZASSIST turns raw sales into answers: trends, dead stock, best hours, GST summaries — asked and answered in plain language.',
    accent: 'text-violet-300 bg-violet-400/10',
  },
  {
    icon: Icon.shield,
    title: 'Role-based lockdown',
    body: 'Cashier mode locks staff to the billing counter with shift-wise cash tallies. Owners see everything; everyone else sees exactly what you allow.',
    accent: 'text-rose-300 bg-rose-400/10',
  },
  {
    icon: Icon.update,
    title: 'Silent auto-updates',
    body: 'New versions download quietly in the background and install on your schedule. You’re always on the latest build without lifting a finger.',
    accent: 'text-cyan-300 bg-cyan-400/10',
  },
]

function Features() {
  return (
    <section id="features" className="relative py-24">
      <div className="mx-auto max-w-6xl px-6">
        <Reveal className="text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-white md:text-5xl">
            Built for the counter. <span className="text-gradient">Ready for scale.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-xl text-slate-400">
            Everything a modern shop needs, in one fast desktop app.
          </p>
        </Reveal>

        <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={i * 90}>
              <div className="glass group h-full rounded-2xl p-6 transition-all duration-300 hover:-translate-y-1.5 hover:border-white/20 hover:bg-white/[0.07]">
                <div className={`mb-5 inline-flex rounded-xl p-3 ${f.accent}`}>{f.icon}</div>
                <h3 className="text-lg font-bold text-white">{f.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{f.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function HowItWorks() {
  const steps = [
    ['Download & install', 'One installer. No servers, no setup wizards, no IT guy. You’re billing in under two minutes.'],
    ['Work fully offline', 'The engine and your data live on your machine. Internet is optional, always.'],
    ['Sync when connected', 'Hybrid sync backs up to the cloud automatically and keeps every device consistent.'],
  ]
  return (
    <section id="how" className="relative py-24">
      <div className="pointer-events-none absolute left-1/2 top-0 h-72 w-72 -translate-x-1/2 rounded-full bg-indigo-600/15 blur-[100px]" />
      <div className="mx-auto max-w-5xl px-6">
        <Reveal className="text-center">
          <h2 className="text-4xl font-extrabold tracking-tight text-white">Up and running in minutes</h2>
        </Reveal>
        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {steps.map(([t, b], i) => (
            <Reveal key={t} delay={i * 120}>
              <div className="glass relative h-full rounded-2xl p-6">
                <span className="absolute -top-4 left-6 grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-electric-500 to-indigo-600 text-sm font-black text-white shadow-lg shadow-electric-600/30">
                  {i + 1}
                </span>
                <h3 className="mt-3 font-bold text-white">{t}</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-400">{b}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function FinalCta() {
  return (
    <section className="relative py-24">
      <div className="mx-auto max-w-4xl px-6">
        <Reveal>
          <div className="glass-strong relative overflow-hidden rounded-3xl p-10 text-center md:p-14">
            <div className="pointer-events-none absolute -top-24 left-1/2 h-64 w-[120%] -translate-x-1/2 rounded-full bg-electric-600/20 blur-3xl" />
            <h2 className="text-3xl font-extrabold tracking-tight text-white md:text-4xl">
              Your counter deserves better than a browser tab.
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-slate-400">
              Join shops running BizAssist all day, every day — rain, shine or fibre cut.
            </p>
            <div className="mt-8 flex justify-center">
              <DownloadButtons large />
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="border-t border-white/5 py-10">
      <div className="mx-auto flex max-w-6xl flex-col items-center gap-6 px-6 md:flex-row">
        <div className="flex items-center gap-2.5">
          <LogoMark size="h-7 w-7" />
          <span className="font-extrabold text-white">
            Biz<span className="text-electric-400">Assist</span>
          </span>
        </div>
        <div className="flex items-center gap-6 text-sm text-slate-400 md:ml-auto">
          <a href="#features" className="transition hover:text-white">Features</a>
          <a href="#how" className="transition hover:text-white">How it works</a>
          <a href={RELEASES_PAGE} className="transition hover:text-white">Releases</a>
          <a href="mailto:rakshithananda18@gmail.com" className="transition hover:text-white">Contact</a>
        </div>
        <p className="text-xs text-slate-600 md:ml-6">© {new Date().getFullYear()} BizAssist. All rights reserved.</p>
      </div>
    </footer>
  )
}

export default function App() {
  return (
    <main className="relative min-h-screen bg-ink-950">
      <Navbar />
      <Hero />
      <Features />
      <HowItWorks />
      <FinalCta />
      <Footer />
    </main>
  )
}
