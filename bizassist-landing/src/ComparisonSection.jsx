import React from 'react'
import Reveal from './Reveal'
import './comparisonSection.css'

// Compare documented workflows, rather than treating shared features as exclusive.
const WORKFLOWS = [
  {
    title: 'Where you work',
    stater: 'Windows or Mac at the counter. A cloud workspace in your browser. Local mode for offline billing.',
    vyapar: 'Offline desktop billing, with mobile and desktop sync options.',
    tally: 'Windows desktop, with remote access and report viewing in a browser.',
  },
  {
    title: 'Stock & purchases',
    stater: 'Items, supplier purchases, batches, expiry dates and godowns in one connected workspace.',
    vyapar: 'Inventory and purchase tracking, with low-stock alerts, batches and expiry dates.',
    tally: 'Inventory and purchase transactions, with batches and godown tracking.',
  },
  {
    title: 'Customer & supplier dues',
    stater: 'Running statements bring invoices, receipts and part payments together.',
    vyapar: 'Receivables, payables and bill-wise payment tracking.',
    tally: 'Ledger accounts, outstanding balances, and bills payable and receivable reports.',
  },
  {
    title: 'GST preparation',
    stater: 'GST invoice records, GSTR-1 and GSTR-3B summaries, plus CSV exports for review.',
    vyapar: 'GST invoices and GSTR reports, including GSTR-1 and GSTR-3B.',
    tally: 'GST reports, reconciliation, exports and connected upload options.',
  },
]

export default function ComparisonSection() {
  return <section className="m-section m-comparison" id="compare" aria-labelledby="m-comparison-title">
    <div className="m-container">
      <Reveal className="m-section-heading m-comparison-heading">
        <div><span className="m-eyebrow">COMPARE THE WAY YOU WORK</span><h2 id="m-comparison-title">Your shop deserves<br />the right fit.</h2></div>
        <p>Compare the everyday workflows. STATER Bill brings the counter, stock, purchases and customer balances into one connected flow.</p>
      </Reveal>

      <Reveal>
        <p className="m-comparison-scroll" id="m-comparison-scroll">Swipe or scroll sideways to compare all three products <span aria-hidden="true">↔</span></p>
        <div className="m-comparison-table-wrap" role="region" aria-label="STATER Bill, Vyapar and TallyPrime workflow comparison" aria-describedby="m-comparison-scroll" tabIndex={0}>
          <table className="m-comparison-table">
            <caption className="m-comparison-sr-only">Everyday business workflows in STATER Bill, Vyapar and TallyPrime</caption>
            <colgroup><col className="m-comparison-topic" /><col className="m-comparison-stater" /><col /><col /></colgroup>
            <thead><tr>
              <th scope="col">Your working day</th>
              <th scope="col" className="m-comparison-ours"><span className="m-comparison-product">STATER Bill</span><span className="m-comparison-label">COUNTER TO CLOUD</span></th>
              <th scope="col"><span className="m-comparison-product">Vyapar</span><span className="m-comparison-label">BILLING &amp; ACCOUNTING</span></th>
              <th scope="col"><span className="m-comparison-product">TallyPrime</span><span className="m-comparison-label">ACCOUNTING &amp; BUSINESS</span></th>
            </tr></thead>
            <tbody>{WORKFLOWS.map(workflow => <tr key={workflow.title}>
              <th scope="row">{workflow.title}</th>
              <td className="m-comparison-ours">{workflow.stater}</td>
              <td>{workflow.vyapar}</td>
              <td>{workflow.tally}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="m-comparison-afterword">
          <p><strong>See the fit for yourself.</strong> Walk through STATER Bill with a sample store before starting your own.</p>
          <a href="#workspaces" className="m-text-link">Watch the real app tour <span className="m-arrow" aria-hidden="true">→</span></a>
        </div>
        <details className="m-comparison-sources">
          <summary>Sources &amp; comparison details</summary>
          <p>Based on published product documentation checked <time dateTime="2026-11-10">10 Nov 2026</time>. Features depend on plan, release and configuration. STATER Bill’s GST summaries and exports support preparation and review; return filing is a separate step.</p>
          <p>Official sources: Vyapar <a href="https://vyaparapp.in/gst-accounting-pc">desktop &amp; sync</a>, <a href="https://vyaparapp.in/pricing-detail">inventory, dues &amp; GST reports</a>; TallyPrime <a href="https://help.tallysolutions.com/tallyprime-faq/">desktop &amp; inventory</a>, <a href="https://help.tallysolutions.com/browser-reports-faq-tally/">browser reports &amp; balances</a>, <a href="https://help.tallysolutions.com/gstr-3b-tallyprime/">GST workflow</a>.</p>
        </details>
      </Reveal>
    </div>
  </section>
}
