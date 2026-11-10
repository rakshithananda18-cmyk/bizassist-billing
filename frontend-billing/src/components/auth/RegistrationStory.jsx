import React from 'react'
import { CounterIcon, InventoryIcon, ReportsIcon } from '../Icons'
import { DESKTOP_DOWNLOAD_URL } from '../../config/downloadApp'
import { IS_LOCAL_APP } from '../../config'

const BENEFITS = [
  { Icon: CounterIcon, title: 'One catalogue. More ways to sell.', copy: 'Retail, wholesale and distributor prices on the same item. A counter that works the way you do.' },
  { Icon: InventoryIcon, title: 'See the whole stock story.', copy: 'Connect supplier purchases, quantities, batches and expiry dates in one workspace.' },
  { Icon: ReportsIcon, title: 'Every balance, in view.', copy: 'Keep customer and supplier dues beside invoices, receipts and part payments.' },
]

export default function RegistrationStory() {
  return <div className="registration-story">
    <span className="registration-eyebrow">MAKE ROOM FOR WHAT COMES NEXT</span>
    <h2>Start with a sale.<br /><em>Build a bigger story.</em></h2>
    <p className="registration-story-intro">Your billing, stock, purchases and payments. Finally, on the same road.</p>
    <ul className="registration-benefits">
      {BENEFITS.map(({ Icon, title, copy }) => <li key={title}>
        <span className="registration-benefit-icon"><Icon size={19} /></span>
        <div><h3>{title}</h3><p>{copy}</p></div>
      </li>)}
    </ul>
    <section className="registration-workstyle" aria-labelledby="registration-workstyle-title">
      <span className="registration-trial">14 days of Pro <span>for eligible first-time phone registrations</span></span>
      <h3 id="registration-workstyle-title">One account. Your way to work.</h3>
      <div id="cloud-storage-help">
        <p>{IS_LOCAL_APP ? 'Bill locally on this computer, even without the internet. Choose Local + Cloud to connect your desktop and browser.' : 'This browser uses the cloud database. Add the desktop app for local, offline billing.'}</p>
        <p>Local + Cloud sync requires Pro or an eligible trial. After your trial, Local billing keeps working; cloud sync needs Pro. Field Team is included during the trial.</p>
      </div>
      {!IS_LOCAL_APP && <><span className="registration-desktop-note">Recommended for POS &amp; Counters</span><a className="registration-download" href={DESKTOP_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">Download Desktop App <span aria-hidden="true">↗</span></a></>}
    </section>
    <p className="registration-account-note" id="registration-account-help">Your phone is used for recovery and trial eligibility. Email is optional.</p>
    <p className="registration-support">A little help getting started? <a href="mailto:support@staterbill.com">support@staterbill.com</a></p>
  </div>
}
