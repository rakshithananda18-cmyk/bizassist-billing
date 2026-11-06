import React from 'react'
import LegalLayout from '../layouts/LegalLayout'

export default function Terms() {
  return (
    <LegalLayout
      title="Terms of Service"
      subtitle="Please read these terms carefully before accessing or using Stater Bill."
      lastUpdated="November 2026"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            1. Agreement to Terms
          </h2>
          <p>
            These Terms of Service ("Terms") constitute a legally binding agreement between you (whether individually or on behalf of a business, enterprise, or entity, referred to as "User", "Merchant", or "you") and <strong>STATER Bill</strong> by ARES Pvt Ltd ("STATER Bill", "we", "us", or "our"), governing your access to and use of the STATER Bill software, web application (<a href="https://staterbill.com" style={{ color: 'var(--accent)' }}>staterbill.com</a>), desktop client, application programming interfaces (APIs), and related services (collectively, the "Service").
          </p>
          <p>
            By registering for an account, downloading the desktop application, or using the web billing dashboard, you acknowledge that you have read, understood, and agreed to be bound by these Terms and our <a href="/privacy" style={{ color: 'var(--accent)' }}>Privacy Policy</a>. If you do not agree to these Terms, you must immediately discontinue use of the Service.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            2. Nature and Scope of Service
          </h2>
          <p>
            Stater Bill is a multi-platform, local-first point-of-sale (POS), billing, inventory management, and business assistance platform designed to facilitate:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Point-of-Sale (POS) counter billing and thermal/A4 invoice printing.</li>
            <li>Real-time and offline stock/inventory tracking and purchases ledger.</li>
            <li>Customer and vendor contact management with balance ledgers.</li>
            <li>Hybrid local-to-cloud synchronization between desktop counters and cloud dashboards.</li>
            <li>B2B electronic document exchange and automated invoice sharing.</li>
            <li>Tax computation assistance and GST summary reports (GSTR-1 / GSTR-3B).</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            3. Tax, Invoicing & Legal Compliance Disclaimer
          </h2>
          <div style={{
            padding: 16,
            borderRadius: 'var(--radius-md, 8px)',
            backgroundColor: 'var(--accent-glow, rgba(193, 95, 60, 0.06))',
            borderLeft: '4px solid var(--accent, #c15f3c)',
            marginBottom: 12,
          }}>
            <strong>Important Legal Notice:</strong> Stater Bill provides calculation, record-keeping, and document rendering tools. Stater Bill is NOT a chartered accountant, certified tax advisor, auditor, or government tax collection authority.
          </div>
          <p>
            You are exclusively responsible for ensuring that:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>All applicable Goods and Services Tax (GST), Value Added Tax (VAT), sales tax, and cess rates applied to your items and services comply with prevailing laws and statutory notifications.</li>
            <li>Your business GSTIN, legal name, registered trade address, and Harmonized System of Nomenclature (HSN) / SAC codes are accurate on every invoice.</li>
            <li>Invoice sequence numbering complies with your jurisdiction’s legal guidelines (e.g. unique sequential numbers within a financial year).</li>
            <li>All tax liabilities, filings, and statutory declarations submitted to relevant tax departments are verified by your authorized accountant or legal representative.</li>
          </ul>
          <p>
            Stater Bill and ARES disclaim all liability for penalties, fines, audits, or interest assessed by tax authorities resulting from incorrect tax rates, faulty configurations, or erroneous invoices generated through the Service.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            4. Account Registration, Staff Security & Multi-Tenant Access
          </h2>
          <p>
            When creating an account, you agree to provide true, accurate, and current information, including a valid business phone number and email address. You are responsible for safeguarding the credentials associated with your account, including Owner passwords, 2FA/TOTP authenticator tokens, and staff cashier PINs.
          </p>
          <p>
            Any action performed using your business identifier (BizID) or user tokens will be deemed authorized by you. If you discover unauthorized access or a security breach, you agree to notify us immediately at <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent)' }}>rakshithananda18@gmail.com</a>.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            5. Offline Architecture, Hybrid Sync & Data Backup
          </h2>
          <p>
            Stater Bill employs a local-first design. On desktop installations, records are stored locally in an embedded database (SQLite), allowing the billing counter to operate seamlessly without an internet connection.
          </p>
          <p>
            When internet connectivity is available, the hybrid sync worker reconciles local mutations with the cloud database (Postgres). While we implement robust two-phase synchronization, conflict resolution, and encryption in transit, you acknowledge that:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Hardware failure, operating system corruption, disk crashes, or ungraceful machine power-offs on your local device may result in unrecoverable data if hybrid cloud sync was disabled or not completed.</li>
            <li>You should regularly export your data via the Data Migration & CSV Export tools in Settings as an offline safeguard.</li>
            <li>STATER Bill and ARES are not liable for data loss arising from local hardware malfunctions, operating system updates, or third-party computer viruses.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            6. Free Tier, Pro Subscriptions & Billing
          </h2>
          <p>
            Stater Bill provides both free tier access and premium ("Pro") subscription plans:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li><strong>Free Tier:</strong> Free accounts have access to essential billing features with designated usage limits (e.g. invoice volumes, multi-device cloud sync quotas, or AI query limits). We reserve the right to modify or adjust free tier thresholds with reasonable prior notice.</li>
            <li><strong>Pro Subscriptions:</strong> Pro plans unlock enhanced capabilities including unlimited multi-device cloud synchronization, AI business insights, automated cloud backups, and dedicated priority support.</li>
            <li><strong>Trials:</strong> Eligible new businesses may receive a 14-day Pro trial without requiring payment details. Upon trial expiry, accounts continue on the Free tier unless a Pro plan is activated.</li>
          </ul>
          <p>
            Detailed refund terms are specified in our <a href="/refund-policy" style={{ color: 'var(--accent)' }}>Refund & Cancellation Policy</a>.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            7. Ownership of Data and Intellectual Property
          </h2>
          <p>
            <strong>Your Data:</strong> You retain complete and exclusive ownership of all business records, inventory catalogs, customer lists, price lists, and financial transactions entered into or generated through the Service ("User Data"). We do not sell, rent, or monetize your User Data.
          </p>
          <p>
            <strong>Our Intellectual Property:</strong> All software code, user interface designs, logos, algorithms, and documentation are the exclusive property of A. Rakshit Enterprise Solutions Pvt Ltd (ARES) and protected by copyright and intellectual property laws. You may not decompile, reverse-engineer, resell, or distribute the cloud service without written authorization.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            8. Acceptable Use and Restrictions
          </h2>
          <p>
            You agree not to use STATER Bill to:
          </p>
          <ul style={{ paddingLeft: 20, margin: '8px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
            <li>Generate fraudulent, forged, or fictitious invoices for tax evasion or money laundering.</li>
            <li>Interfere with, bypass, or overburden our cloud infrastructure, rate limiters, or server APIs.</li>
            <li>Attempt to probe, reverse engineer, or gain unauthorized access to other merchants’ isolated tenant databases.</li>
            <li>Transmit malware, viruses, or disruptive scripts through public invoice viewer or import endpoints.</li>
          </ul>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            9. Warranty Disclaimer & Limitation of Liability
          </h2>
          <p>
            THE SERVICE IS PROVIDED ON AN "AS IS" AND "AS AVAILABLE" BASIS WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED. TO THE FULLEST EXTENT PERMISSIBLE UNDER APPLICABLE LAW, STATER BILL AND ARES DISCLAIM ALL WARRANTIES, INCLUDING MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.
          </p>
          <p>
            IN NO EVENT SHALL ARES PVT LTD OR STATER BILL, ITS DEVELOPERS, OR OPERATORS BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES (INCLUDING LOSS OF PROFITS, DATA, USE, GOODWILL, OR BUSINESS INTERRUPTION) ARISING OUT OF OR IN CONNECTION WITH THE USE OR INABILITY TO USE THE SERVICE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGES. IN ALL CASES, OUR AGGREGATE LIABILITY SHALL BE LIMITED TO THE AMOUNT PAID BY YOU FOR THE SERVICE IN THE TWELVE (12) MONTHS PRECEDING THE CLAIM.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            10. Termination
          </h2>
          <p>
            You may terminate your account at any time by contacting support or discontinuing use. ARES may suspend or terminate your access immediately if you violate these Terms, engage in fraudulent behavior, or fail to satisfy applicable subscription obligations. Upon termination, you may export your data prior to account closure.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            11. Governing Law & Dispute Resolution
          </h2>
          <p>
            These Terms shall be governed by and construed in accordance with the laws of India, without regard to conflict of law principles. Any legal disputes arising under these Terms shall be subject to the exclusive jurisdiction of the competent courts in Bengaluru, Karnataka, India.
          </p>
        </section>

        <section>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
            12. Contact Information
          </h2>
          <p>
            For any questions, legal notices, or clarifications regarding these Terms, please reach out to us at:
          </p>
          <div style={{
            marginTop: 10,
            padding: 16,
            borderRadius: 'var(--radius-md, 8px)',
            backgroundColor: 'var(--bg-1, #f4f4f1)',
            border: '1px solid var(--border, #e5e7eb)',
          }}>
            <p style={{ margin: '0 0 4px 0', fontWeight: 600 }}>A. Rakshit Enterprise Solutions Pvt Ltd (ARES) — Stater Bill</p>
            <p style={{ margin: '0 0 4px 0' }}>Email: <a href="mailto:rakshithananda18@gmail.com" style={{ color: 'var(--accent)' }}>rakshithananda18@gmail.com</a></p>
            <p style={{ margin: 0 }}>Support Hours: Monday – Saturday, 10:00 AM – 6:00 PM IST</p>
          </div>
        </section>
      </div>
    </LegalLayout>
  )
}
