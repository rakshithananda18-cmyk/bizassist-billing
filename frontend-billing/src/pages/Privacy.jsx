import React from 'react'
import LegalLayout from '../layouts/LegalLayout'
import { openStoragePreferences } from '../utils/storageConsent'

export default function Privacy() {
  return (
    <LegalLayout
      title="Privacy Policy"
      subtitle="How STATER Bill collects, protects, processes, and respects your business and personal data."
      lastUpdated="November 2026"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            1. Overview & Commitment to Privacy
          </h2>
          <p>
            At <strong>Stater Bill</strong> (a product of A. Rakshit Enterprise Solutions Pvt Ltd — "ARES") ("we", "us", or "our"), we understand that financial ledgers, customer contact lists, profit margins, and inventory quantities are critical and sensitive business assets. We are firmly committed to safeguarding the privacy and confidentiality of the information you entrust to us.
          </p>
          <p>
            This Privacy Policy explains how Stater Bill collects, uses, stores, and protects data when you access or use our web application, desktop app, and cloud synchronization services. By accessing or using STATER Bill, you consent to the practices described in this policy.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            2. Information We Collect
          </h2>
          <p>We collect information in the following categories:</p>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 8 }}>
            <div>
              <strong style={{ color: 'var(--text-primary)' }}>A. Account & Business Registration Data</strong>
              <p style={{ margin: '4px 0 0 0' }}>
                When creating an account, we collect your business name, primary contact phone number, email address, physical trade address, and Goods and Services Tax Identification Number (GSTIN) where applicable. Passwords are cryptographically hashed using salted bcrypt prior to storage; we cannot view your raw password.
              </p>
            </div>

            <div>
              <strong style={{ color: 'var(--text-primary)' }}>B. Operational Business & Transaction Records</strong>
              <p style={{ margin: '4px 0 0 0' }}>
                To provide invoicing and point-of-sale functionality, the Service processes your product catalog (items, SKU codes, prices, stock levels), purchases, invoices, payments, and customer/vendor contact details.
              </p>
            </div>

            <div>
              <strong style={{ color: 'var(--text-primary)' }}>C. Technical, Device & Network Metadata</strong>
              <p style={{ margin: '4px 0 0 0' }}>
                For security, session management, and multi-device LAN auto-discovery, we collect technical identifiers such as local IP addresses (for local POS terminals discovering your counter host on the same Wi-Fi), browser user-agent, application version, and standard server access logs.
              </p>
            </div>
          </div>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            3. No Sale or Commercial Exploitation of Data
          </h2>
          <div style={{
            padding: 16,
            borderRadius: 'var(--radius-md, 8px)',
            backgroundColor: 'var(--accent-glow, rgba(193, 95, 60, 0.06))',
            borderLeft: '4px solid var(--accent, #c15f3c)',
          }}>
            <strong>Our Core Privacy Guarantee:</strong> We do NOT sell, rent, broker, or trade your business data, customer telephone numbers, or sales metrics to third-party advertisers, data aggregators, or marketing agencies under any circumstances.
          </div>
          <p style={{ marginTop: 12 }}>
            Your customer database and transaction history remain your private business records. They are processed exclusively to fulfill the billing, reporting, and synchronization features you invoke.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            4. How We Use and Process Information
          </h2>
          <p>We use the collected information solely for legitimate operational purposes:</p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Operating the billing counter, computing tax summaries, and printing receipts.</li>
            <li>Synchronizing data across your verified desktop, mobile, and browser devices.</li>
            <li>Authenticating users, maintaining session security, and preventing multi-tenant data cross-talk.</li>
            <li>Delivering system notifications, security alerts, and requested technical support.</li>
            <li>Processing optional AI queries (e.g. daily sales summaries) statelessly through secured enterprise inference APIs without retaining or training public models on your customer data.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            5. Architecture, Storage & Multi-Tenant Security
          </h2>
          <p>
            Stater Bill is engineered with privacy and tenant isolation at its core:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><strong>Local-First Storage:</strong> On the desktop client, all transactional data is stored in a local SQLite database on your physical machine. You retain offline sovereignty over your records.</li>
            <li><strong>PostgreSQL Cloud Storage:</strong> When cloud sync is active, records are stored in managed PostgreSQL instances configured with Row-Level Security (RLS). Every query is strictly scoped to your tenant identifier (`current_business_id`).</li>
            <li><strong>Transport Encryption:</strong> All data transmitted between your devices and our cloud backend is secured using modern TLS/HTTPS encryption protocols.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            6. Cookies and Local Browser Storage
          </h2>
          <p>
            Stater Bill does not set sign-in cookies or use advertising and behavioral tracking cookies. Essential browser storage (localStorage, sessionStorage and the offline database) supports:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Maintaining your signed-in session and linked cloud session.</li>
            <li>Remembering your UI preferences (light / dark mode, zoom scale, default receipt roll width).</li>
            <li>Tracking offline sync queues and outbox counts.</li>
          </ul>
          <p>
            On first use, choose Essential only or Accept all in the browser-storage notice. Optional error diagnostics and their browser device identifier stay off until you accept them. You can change your choice below; declining diagnostics does not disable billing or sign-in. A report you explicitly choose to send is sent only for that request.
          </p>
          <button type="button" className="btn btn-secondary" onClick={openStoragePreferences}>Manage storage preferences</button>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            7. Data Ownership, Portability & Deletion
          </h2>
          <p>
            In compliance with the Digital Personal Data Protection Act (DPDP Act) and international privacy best practices:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><strong>Right to Export:</strong> You can export complete copies of your inventory, sales, purchases, and contacts in universal CSV format at any time via Settings &gt; Data Migration.</li>
            <li><strong>Right to Deletion:</strong> You may request the permanent deletion of your account and cloud-stored records by contacting our grievance channel. Upon verification, your cloud tenant records will be purged within 30 days.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            8. Third-Party Service Providers
          </h2>
          <p>
            We partner with reputable infrastructure providers to operate the Service:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><strong>Vercel:</strong> Web frontend hosting and global CDN delivery.</li>
            <li><strong>Cloud Infrastructure:</strong> Managed cloud servers and database hosting (PostgreSQL) with strict enterprise access controls.</li>
            <li><strong>Groq Inc.:</strong> Ultra-low latency stateless AI model inference for opted-in automated business insights.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            9. Grievance Officer & Contact
          </h2>
          <p>
            If you have questions, feedback, or privacy-related concerns, you may contact our designated Grievance & Data Protection desk:
          </p>
          <div style={{
            marginTop: 10,
            padding: 16,
            borderRadius: 'var(--radius-md, 8px)',
            backgroundColor: 'var(--bg-1, #f4f4f1)',
            border: '1px solid var(--border, #e5e7eb)',
          }}>
            <p style={{ margin: '0 0 4px 0', fontWeight: 600 }}>A. Rakshit Enterprise Solutions Pvt Ltd (ARES) — Stater Bill Desk & Grievance Desk</p>
            <p style={{ margin: '0 0 4px 0' }}>Email: <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent)' }}>rakshithananda18@gmail.com</a></p>
            <p style={{ margin: 0 }}>Hours: Monday – Saturday, 10:00 AM – 6:00 PM IST</p>
          </div>
        </section>
      </div>
    </LegalLayout>
  )
}
