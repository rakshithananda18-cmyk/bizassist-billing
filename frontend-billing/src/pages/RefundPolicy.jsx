import React from 'react'
import LegalLayout from '../layouts/LegalLayout'

export default function RefundPolicy() {
  return (
    <LegalLayout
      title="Cancellation & Refund Policy"
      subtitle="Clear and fair terms regarding STATER Bill subscription plans, trials, and cancellations."
      lastUpdated="November 2026"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            1. Overview
          </h2>
          <p>
            At <strong>Stater Bill</strong> (operated by A. Rakshit Enterprise Solutions Pvt Ltd — "ARES"), we strive to provide dependable, transparent, and powerful billing and inventory tools. We want you to be fully confident in your investment. This Cancellation and Refund Policy outlines how subscriptions, cancellations, and refund requests are handled.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            2. 14-Day Risk-Free Pro Trial
          </h2>
          <p>
            Every new business registered on Stater Bill is entitled to an automatic <strong>14-day Pro trial</strong> with zero upfront payment obligations and no credit card required.
          </p>
          <p>
            During this trial, you enjoy full access to Pro capabilities—including hybrid cloud sync, multi-device counter access, and AI business analysis. If you choose not to upgrade to a paid Pro tier at the end of the 14 days, your account seamlessly transitions to the Free tier without interruption or unexpected charges.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            3. Subscription Cancellation
          </h2>
          <p>
            You may cancel your paid subscription at any time:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><strong>Immediate Effect:</strong> Once cancelled, automatic renewals will cease immediately.</li>
            <li><strong>Access Through Billing Period:</strong> You will retain full access to all paid features until the conclusion of your current prepaid billing cycle (monthly or annual).</li>
            <li><strong>No Cancellation Penalties:</strong> There are no cancellation fees, early termination fees, or penalty charges.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            4. Refund Eligibility & Window
          </h2>
          <p>
            We provide refunds under the following fair conditions:
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginTop: 10 }}>
            <div style={{
              padding: 14,
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--bg-1, #f4f4f1)',
              border: '1px solid var(--border, #e5e7eb)',
            }}>
              <strong>A. 7-Day Money-Back Guarantee (First-Time Subscriptions)</strong>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem' }}>
                If you purchase a paid Pro plan for the first time and find that Stater Bill does not meet your operational needs, you may request a 100% full refund within <strong>7 calendar days</strong> of the initial charge.
              </p>
            </div>

            <div style={{
              padding: 14,
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--bg-1, #f4f4f1)',
              border: '1px solid var(--border, #e5e7eb)',
            }}>
              <strong>B. Billing Errors & Duplicate Charges</strong>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem' }}>
                If a technical error causes a duplicate transaction or incorrect billing amount, we will immediately issue a complete refund for the erroneous charge upon notification.
              </p>
            </div>

            <div style={{
              padding: 14,
              borderRadius: 'var(--radius-md, 8px)',
              backgroundColor: 'var(--bg-1, #f4f4f1)',
              border: '1px solid var(--border, #e5e7eb)',
            }}>
              <strong>C. Material Service Outage</strong>
              <p style={{ margin: '4px 0 0 0', fontSize: '0.9rem' }}>
                In the rare event of prolonged, continuous cloud downtime attributable to our backend systems exceeding 72 consecutive hours, affected paid users may request a pro-rated credit or refund for that billing month.
              </p>
            </div>
          </div>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            5. Non-Refundable Scenarios
          </h2>
          <p>Refunds cannot be granted under the following circumstances:</p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Requests made after the 7-day guarantee window for recurring monthly renewals.</li>
            <li>Accounts suspended or terminated due to violations of our <a href="/terms" style={{ color: 'var(--accent)' }}>Terms of Service</a> (e.g. fraudulent billing or abuse).</li>
            <li>Third-party hardware purchases (such as thermal receipt printers or barcode scanners sourced from outside vendors).</li>
            <li>Localized merchant hardware failures or lack of local internet connectivity.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            6. How to Request a Refund
          </h2>
          <p>
            To submit a cancellation or refund request, please email our support team with:
          </p>
          <ol style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Your registered business name and phone number.</li>
            <li>Your public Business ID (found under Settings &gt; Profile).</li>
            <li>The payment transaction ID or invoice reference.</li>
            <li>A brief description of the reason for your refund request.</li>
          </ol>
          <div style={{
            marginTop: 14,
            padding: 16,
            borderRadius: 'var(--radius-md, 8px)',
            backgroundColor: 'var(--bg-1, #f4f4f1)',
            border: '1px solid var(--border, #e5e7eb)',
          }}>
            <p style={{ margin: '0 0 4px 0', fontWeight: 600 }}>A. Rakshit Enterprise Solutions Pvt Ltd (ARES) — Refund Desk</p>
            <p style={{ margin: '0 0 4px 0' }}>Email: <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent)' }}>rakshithananda18@gmail.com</a></p>
            <p style={{ margin: 0 }}>Processing Timeline: Approved refunds are credited to the original payment method (bank account, credit/debit card, or UPI) within <strong>5 to 7 business days</strong>.</p>
          </div>
        </section>
      </div>
    </LegalLayout>
  )
}
