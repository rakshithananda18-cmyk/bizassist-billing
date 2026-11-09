import React from 'react'
import './adoptionSections.css'

function Arrow({ diagonal = false }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {diagonal ? <path d="M6 18 18 6M6 6h12v12" /> : <path d="M4 12h15m-6-6 6 6-6 6" />}
    </svg>
  )
}

function StoreIcon({ kind }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="1.45" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {kind === 'grocery' && <><path d="M4 13h24l-3 14H7L4 13Zm6 0 6-9 6 9M3 13h26M12 18v4m8-4v4" /></>}
      {kind === 'retail' && <><path d="M5 6h12l10 10-11 11L5 16V6Z" /><circle cx="11" cy="12" r="1.5" /><path d="m18 17 4 4m-7-1 4 4" /></>}
      {kind === 'wholesale' && <><path d="m16 3 12 7v13l-12 7L4 23V10l12-7Zm0 14 12-7M16 17 4 10m12 7v13M10 7l12 7v5" /></>}
    </svg>
  )
}

const STORE_FITS = [
  { kind: 'grocery', title: 'Grocery', copy: 'Keep everyday billing, barcodes, batches and expiry dates together.' },
  { kind: 'retail', title: 'General retail', copy: 'One item catalogue, clear stock levels and the right selling price at the counter.' },
  { kind: 'wholesale', title: 'Wholesale & distribution', copy: 'Work with price tiers, stock across godowns and connected B2B orders.' },
]

const FAQS = [
  {
    question: 'Can I keep billing when the internet goes down?',
    answer: 'The installed desktop app can run against a local backend, so your counter can keep working without the internet. The cloud app needs an internet connection. Choose Local + Cloud when you want local operations with cloud sync; synchronization needs connectivity.',
  },
  {
    question: 'What does STATER Bill do for GST reporting?',
    answer: 'Prepare GST invoices and GSTR-1 and GSTR-3B reports from your recorded transactions. Review the figures and exports with your accountant before filing. Report preparation and export are available in the app; submitting a return to the GST portal is a separate step.',
  },
  {
    question: 'What can I see in the public tour?',
    answer: 'Watch the real app move through billing, items, stock, purchases and contacts using a sample store. Selected advanced pricing and analytics details are protected in this preview, and B2B, App Settings and POS Live stay locked. Click the preview to create an account, or use Sign in if you already have one.',
  },
  {
    question: 'Can I bring my existing items and contacts?',
    answer: 'Yes. In your own store, open App Settings → Data Migration to download CSV templates for items, customers and suppliers. Arrange your existing records in the template format, then review the import preview before confirming.',
  },
  {
    question: 'Can I use it on Windows, Mac or in a browser?',
    answer: 'You can use the cloud app in a browser or choose a desktop installer for Windows or macOS. The download section shows the installers available in the current release, including Mac architecture choices when provided. Choose the build that matches your computer.',
  },
]

export default function AdoptionSections() {
  return (
    <div className="adoption">
      <section id="get-started" className="adoption-start" aria-labelledby="adoption-start-title">
        <div className="adoption__inner">
          <div className="adoption__section-heading">
            <div>
              <p className="adoption__eyebrow"><span /> A comfortable first step</p>
              <h2 id="adoption-start-title">From a look around<br />to your first bill.</h2>
            </div>
            <p className="adoption__intro">Get to know the workspace with a guided preview. Then sign in or start a trial to make it your own.</p>
          </div>

          <ol className="adoption-steps">
            <li>
              <div className="adoption-steps__top"><span className="adoption-steps__number">01</span><span className="adoption-steps__label">Look around</span><Arrow /></div>
              <h3>Watch the sample shop.</h3>
              <p>Follow the real app from Home to Contacts with sample items. Selected advanced workflows are protected in the public preview.</p>
              <a className="adoption__text-link" href="#workspaces">Watch the product tour <Arrow diagonal /></a>
            </li>
            <li>
              <div className="adoption-steps__top"><span className="adoption-steps__number">02</span><span className="adoption-steps__label">Find your setup</span><Arrow /></div>
              <h3>Choose where you work.</h3>
              <p>Use desktop for local operations, cloud for browser access, or Local + Cloud to bring them together.</p>
              <a className="adoption__text-link" href="#downloads">See your options <Arrow diagonal /></a>
            </li>
            <li>
              <div className="adoption-steps__top"><span className="adoption-steps__number">03</span><span className="adoption-steps__label">Make it yours</span><span className="adoption-steps__finish" aria-hidden="true">✓</span></div>
              <h3>Start with your own store.</h3>
              <p>Create your account, add or import your items and contacts, check opening stock, then create your first bill at the counter.</p>
              <a className="adoption__text-link" href="https://app.staterbill.com/register">Create your store <Arrow diagonal /></a>
            </li>
          </ol>
        </div>
      </section>

      <section className="adoption-stores" aria-labelledby="adoption-stores-title">
        <div className="adoption__inner">
          <div className="adoption-stores__heading">
            <p className="adoption__eyebrow">Different shops. Familiar work.</p>
            <h2 id="adoption-stores-title">Built around your day at the counter.</h2>
          </div>
          <div className="adoption-stores__list">
            {STORE_FITS.map(store => (
              <article className="adoption-stores__item" key={store.kind}>
                <StoreIcon kind={store.kind} />
                <h3>{store.title}</h3>
                <p>{store.copy}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section id="faq" className="adoption-faq" aria-labelledby="adoption-faq-title">
        <div className="adoption__inner adoption-faq__layout">
          <div className="adoption-faq__heading">
            <p className="adoption__eyebrow"><span /> Before you begin</p>
            <h2 id="adoption-faq-title">A little clarity<br />goes a long way.</h2>
            <p>Practical answers for choosing your setup and moving your store into the app.</p>
          </div>
          <div className="adoption-faq__questions">
            {FAQS.map(({ question, answer }, index) => (
              <details className="adoption-faq__item" key={question} name="stater-adoption-faq">
                <summary>
                  <span className="adoption-faq__number" aria-hidden="true">0{index + 1}</span>
                  <span>{question}</span>
                  <span className="adoption-faq__toggle" aria-hidden="true"><span /><span /></span>
                </summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
