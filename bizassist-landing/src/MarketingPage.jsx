import React, { useEffect, useState } from 'react'
import Reveal from './Reveal'
import DemoShowcaseStudio from './DemoShowcaseStudio'
import AdoptionSections from './AdoptionSections'
import ComparisonSection from './ComparisonSection'
import { useLatestRelease } from './useLatestRelease'
import './marketing.css'

const REGISTER = 'https://app.staterbill.com/register'
const LOGIN = 'https://app.staterbill.com/login'

function Arrow({ diagonal = false }) {
  return <span className="m-arrow" aria-hidden="true">{diagonal ? '↗' : '→'}</span>
}

function Navbar({ Icons, BrandLogo, theme, onToggleTheme }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = event => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [open])
  const links = [['#workspaces', 'App tour'], ['#features', 'Benefits'], ['#compare', 'Compare'], ['#downloads', 'Downloads'], ['#faq', 'FAQs']]
  return <header className="m-header">
    <nav className="m-navbar" aria-label="Main navigation">
      <a href="#" className="m-brand" aria-label="STATER Bill home"><BrandLogo size={22} showTagline={false} /></a>
      <div className="m-nav-links">{links.map(([href, label]) => <a href={href} key={href}>{label}</a>)}</div>
      <div className="m-nav-actions">
        <button className="m-theme-toggle" onClick={onToggleTheme} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}>{theme === 'dark' ? <Icons.sun className="w-4 h-4" /> : <Icons.moon className="w-4 h-4" />}</button>
        <a href={LOGIN} className="m-sign-in">Sign in</a>
        <a href={REGISTER} className="m-button m-button-small">Start free trial <Arrow /></a>
        <button className="m-menu-toggle" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="mobile-navigation" onClick={() => setOpen(value => !value)}><span /><span className={open ? 'is-open' : ''} /></button>
      </div>
    </nav>
    {open && <div className="m-mobile-nav" id="mobile-navigation">{links.map(([href, label]) => <a href={href} key={href} onClick={() => setOpen(false)}>{label}<Arrow /></a>)}<a href={REGISTER} onClick={() => setOpen(false)}>Start your free trial <Arrow /></a><a href={LOGIN} onClick={() => setOpen(false)}>Sign in <Arrow /></a></div>}
  </header>
}

function Hero({ Icons }) {
  return <section className="m-hero">
    <div className="m-hero-glow" aria-hidden="true" />
    <div className="m-container">
      <div className="m-hero-copy">
        <Reveal><div className="m-eyebrow m-hero-eyebrow"><span className="m-status-dot" /> BUILT AROUND YOUR WORKING DAY</div></Reveal>
        <Reveal delay={70}><h1>Keep your counter moving.<br /><span>Your business, in view.</span></h1></Reveal>
        <Reveal delay={140}><p className="m-hero-description"><strong>Billing, stock, purchases and payments.</strong> One connected workspace to keep the counter moving and your whole shop in view.</p></Reveal>
        <Reveal delay={210} className="m-hero-ctas">
          <a href={REGISTER} className="m-button">Start your free trial <Arrow /></a>
          <a href="#workspaces" className="m-button m-button-secondary"><Icons.play className="w-3 h-3" /> Watch the real app tour</a>
        </Reveal>
        <Reveal delay={240}><p className="m-trial-note">14-day Pro trial <span>·</span> No credit card required <span>·</span> Watch the sample tour first</p></Reveal>
        <Reveal delay={280} className="m-hero-proof">
          <div><Icons.offline className="w-5 h-5" /><div><strong>Bill without internet</strong><span>Desktop billing with local store data</span></div></div>
          <div><Icons.box className="w-5 h-5" /><div><strong>One item. Three prices.</strong><span>Retail, wholesale and distributor</span></div></div>
          <div><Icons.pillars className="w-5 h-5" /><div><strong>Keep dues in view</strong><span>Customer and supplier balances together</span></div></div>
        </Reveal>
      </div>
      <Reveal delay={320} className="m-tour-wrap" id="workspaces"><DemoShowcaseStudio /></Reveal>
      <div className="m-audience-strip"><span>MADE FOR EVERYDAY COMMERCE</span><p>Neighbourhood shops <i /> Supermarkets <i /> Retail counters <i /> Wholesale businesses</p></div>
    </div>
  </section>
}

function Features({ Icons }) {
  const features = [
    { icon: Icons.qrScan, label: 'BILLING COUNTER', title: 'Less friction at the till.', text: 'Scan or search, keep multiple bills open, adjust quantities and print the receipt. Your counter follows the way you work.' },
    { icon: Icons.box, label: 'STOCK & PURCHASES', title: 'See what came in. Know what’s left.', text: 'Keep supplier bills beside your inventory. Track quantities, batches, expiry dates and stock across godowns.' },
    { icon: Icons.chat, label: 'CONTACTS & PAYMENTS', title: 'Keep dues from getting lost.', text: 'See what customers owe and what you owe suppliers. Follow invoices, receipts and part payments in a running statement.' },
    { icon: Icons.chart, label: 'GST & CASH CONTROL', title: 'Close the day with a clearer picture.', text: 'Review the opening float, collections and closing cash. Prepare GST summaries and CSV exports for your accountant.' },
  ]
  return <section id="features" className="m-section m-features">
    <div className="m-container">
      <Reveal className="m-section-heading"><div><span className="m-eyebrow">THE DETAILS THAT MAKE A DIFFERENCE</span><h2>One flow.<br />From shelf to sale.</h2></div><p>Different workspaces, the same business. Move from a bill to stock, from a purchase to a supplier, and from a customer to their balance.</p></Reveal>
      <div className="m-feature-spotlights">
        <Reveal className="m-price-feature"><div className="m-feature-label"><Icons.box className="w-4 h-4" /><span>ONE CATALOGUE. EVERY CUSTOMER.</span></div><h3>One stock.<br />Three ways to sell.</h3><p>Retail, wholesale and distributor prices live on the same item. Choose the right price for the customer while keeping one view of your stock.</p><div className="m-pricing-flow" aria-label="One product catalogue supports retail, wholesale and distributor prices"><div className="m-catalogue-node"><Icons.box className="w-5 h-5" /><span>Your product catalogue</span></div><div className="m-price-branches"><span>Retail</span><span>Wholesale</span><span>Distributor</span></div></div><a className="m-text-link" href="#workspaces">Preview the Billing Counter <Arrow /></a></Reveal>
        <Reveal delay={90} className="m-offline-feature"><div className="m-feature-label"><Icons.offline className="w-4 h-4" /><span>DESKTOP LOCAL BILLING</span></div><div className="m-offline-symbol" aria-hidden="true"><Icons.offline className="w-12 h-12" /><span>Internet disconnected</span><div><span className="m-status-dot" /> Local billing available</div></div><h3>Your internet can take a break.<br />Your counter shouldn’t have to.</h3><p>Bill on your desktop using your local store data. Add cloud access and sync when your setup needs them.</p><a className="m-text-link" href="#offline">Find your way to work <Arrow /></a></Reveal>
      </div>
      <div className="m-feature-list">{features.map((feature, index) => <Reveal key={feature.label} delay={index * 55} className="m-feature-item"><feature.icon className="w-5 h-5" /><span className="m-eyebrow">{feature.label}</span><h3>{feature.title}</h3><p>{feature.text}</p></Reveal>)}</div>
    </div>
  </section>
}

function WorkingModes({ Icons }) {
  const modes = [
    { icon: Icons.windows, name: 'On your counter PC.', tag: 'DESKTOP', text: 'Keep local billing and inventory on the computer at your shop. Use it with your everyday counter and receipt workflow.', benefit: 'Local work, even without internet' },
    { icon: Icons.cloudSync, name: 'In your browser.', tag: 'CLOUD', text: 'Open your business workspace in a browser when you’re connected. Review the day without sitting at the main counter.', benefit: 'Your business, wherever you log in' },
    { icon: Icons.bolt, name: 'Connected together.', tag: 'LOCAL + CLOUD', text: 'Combine desktop work with cloud sync and connected counters when your plan and store setup support them.', benefit: 'A setup that grows with your shop' },
  ]
  return <section id="offline" className="m-section m-modes"><div className="m-container">
    <Reveal className="m-centered-heading"><span className="m-eyebrow">YOUR SHOP. YOUR SETUP.</span><h2>Work where your business happens.</h2><p>A main counter, a browser, or a connected setup.<br />Choose the way of working that fits your store.</p></Reveal>
    <div className="m-mode-grid">{modes.map((mode, index) => <Reveal key={mode.tag} delay={index * 70} className="m-mode"><div className="m-mode-top"><mode.icon className="w-6 h-6" /><span>{mode.tag}</span></div><h3>{mode.name}</h3><p>{mode.text}</p><div className="m-mode-benefit"><Icons.check className="w-3.5 h-3.5" />{mode.benefit}</div></Reveal>)}</div>
    <p className="m-plan-note">Cloud sync and multi-counter features depend on your plan and configuration.</p>
  </div></section>
}

function B2BSection({ Icons }) {
  return <section className="m-section m-b2b" id="b2b"><div className="m-container m-b2b-grid">
    <Reveal className="m-b2b-copy"><span className="m-eyebrow">A CLOSER CONNECTION TO YOUR SUPPLY CHAIN <span className="m-pro-tag">PRO</span></span><h2>From a supplier’s catalogue<br />to your next delivery.</h2><p>Connect with the businesses you trade with. Share selected catalogue access, set customer prices and follow orders into purchases.</p><ul><li><Icons.check className="w-4 h-4" /> Approve the businesses you connect with</li><li><Icons.check className="w-4 h-4" /> Order from connected supplier catalogues</li><li><Icons.check className="w-4 h-4" /> Follow incoming and outgoing orders</li></ul><a href={REGISTER} className="m-text-link">Explore B2B with a Pro trial <Arrow /></a><small>B2B stays locked in the public preview.</small></Reveal>
    <Reveal delay={100} className="m-supply-visual"><span className="m-diagram-label">A CONNECTED WORKFLOW</span><div className="m-supply-node"><div className="m-supply-icon"><Icons.handshake className="w-6 h-6" /></div><div><strong>Connected supplier</strong><span>Catalogue &amp; customer prices</span></div><span className="m-node-dot" /></div><div className="m-supply-connector"><span /><i>Purchase order</i><Arrow /></div><div className="m-supply-node m-supply-node-main"><div className="m-supply-icon"><Icons.box className="w-6 h-6" /></div><div><strong>Your STATER Bill workspace</strong><span>Orders, purchases &amp; stock</span></div><span className="m-node-dot" /></div><div className="m-supply-tags"><span>Connection approved</span><span>Order tracked</span><span>Purchase recorded</span></div></Reveal>
  </div></section>
}

function Downloads({ Icons }) {
  const release = useLatestRelease()
  return <section id="downloads" className="m-section m-downloads"><div className="m-container">
    <Reveal className="m-section-heading"><div><span className="m-eyebrow">YOUR NEXT STEP</span><h2>A proper home<br />for your daily work.</h2></div><p>Install STATER Bill at the counter, or open the cloud workspace in your browser. Watch the guided preview, then sign in or start a trial to explore your own store.</p></Reveal>
    <div className="m-download-grid">
      <Reveal className="m-download-card"><div className="m-download-card-top"><Icons.windows className="w-6 h-6" /><span>AT THE COUNTER {release.version && <b>v{release.version}</b>}</span></div><h3>STATER Bill for desktop</h3><p>Your billing and stock workspace, installed on your shop’s computer.</p><div className="m-download-buttons"><a href={release.windows || release.fallback} className="m-button"><Icons.windows className="w-4 h-4" /> Download for Windows <Arrow diagonal /></a>{release.macRequiresChoice ? <div className="m-mac-choices"><span><Icons.apple className="w-4 h-4" /> Mac installers</span>{release.macArm64 && <a href={release.macArm64}>Apple silicon <Arrow diagonal /></a>}{release.macIntel && <a href={release.macIntel}>Intel <Arrow diagonal /></a>}</div> : <a href={release.mac || release.fallback} className="m-button m-button-secondary"><Icons.apple className="w-4 h-4" /> {release.mac ? 'Download for Mac' : 'View Mac releases'} <Arrow diagonal /></a>}</div></Reveal>
      <Reveal delay={90} className="m-download-card m-cloud-card"><div className="m-download-card-top"><Icons.cloudSync className="w-6 h-6" /><span>IN YOUR BROWSER</span></div><h3>Your workspace.<br />A browser tab away.</h3><p>Start your trial online and get a feel for the way your business fits together.</p><a href={REGISTER} className="m-text-link">Start your free trial <Arrow /></a><a href={LOGIN} className="m-cloud-signin">Already have an account? Sign in ↗</a></Reveal>
    </div>
  </div></section>
}

function FinalCta() {
  return <section className="m-final-cta"><Reveal className="m-container"><span className="m-eyebrow">MAKE ROOM FOR A CLEARER WORKING DAY</span><h2>Your next bill.<br />A better beginning.</h2><p>See how STATER Bill fits your counter, your stock and your customers.</p><div className="m-final-buttons"><a href={REGISTER} className="m-button">Start your 14-day Pro trial <Arrow /></a><a href="#workspaces" className="m-text-link">Take another look at the app <Arrow /></a></div><span className="m-trial-note">No credit card required. Explore at your own pace.</span><p className="m-support-line">Questions before you start? <a href="mailto:support@staterbill.com">support@staterbill.com <Arrow diagonal /></a></p></Reveal></section>
}

function Footer({ BrandLogo }) {
  return <footer className="m-footer"><div className="m-container"><div className="m-footer-top"><div><BrandLogo size={24} showTagline={false} /><p>Built around the business<br />you run every day.</p><a className="m-footer-support" href="mailto:support@staterbill.com">support@staterbill.com <Arrow diagonal /></a></div><div className="m-footer-links"><div><strong>Explore</strong><a href="#workspaces">App tour</a><a href="#features">Benefits</a><a href="#compare">Compare software</a><a href="#b2b">B2B network</a><a href="#downloads">Downloads</a></div><div><strong>Get started</strong><a href={REGISTER}>Start free trial</a><a href={LOGIN}>Sign in</a><a href="#faq">Questions &amp; answers</a><a href="mailto:support@staterbill.com">Email support</a></div><div><strong>The details</strong><a href="https://app.staterbill.com/terms">Terms</a><a href="https://app.staterbill.com/privacy">Privacy &amp; storage</a><a href="https://app.staterbill.com/refund-policy">Refund policy</a></div></div></div><div className="m-footer-bottom"><span>© {new Date().getFullYear()} STATER Bill · ARES</span><span>στατήρ — inspired by the original standard of trade.</span><a href="#">Back to top ↑</a></div></div></footer>
}

export default function MarketingPage({ Icons, BrandLogo, theme, onToggleTheme }) {
  useEffect(() => {
    if (!window.location.hash) return
    const anchor = window.location.hash.slice(1)
    const timer = setTimeout(() => document.getElementById(anchor)?.scrollIntoView({ behavior: 'auto' }), 100)
    return () => clearTimeout(timer)
  }, [])
  return <div className="marketing-page">
    <a className="m-skip-link" href="#main-content">Skip to content</a>
    <Navbar Icons={Icons} BrandLogo={BrandLogo} theme={theme} onToggleTheme={onToggleTheme} />
    <main id="main-content"><Hero Icons={Icons} /><Features Icons={Icons} /><WorkingModes Icons={Icons} /><ComparisonSection /><B2BSection Icons={Icons} /><AdoptionSections /><Downloads Icons={Icons} /><FinalCta /></main>
    <Footer BrandLogo={BrandLogo} />
  </div>
}
