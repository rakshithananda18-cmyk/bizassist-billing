import React, { useEffect, useState } from 'react'
import { CounterIcon, InventoryIcon, ReportsIcon } from '../Icons'
import { DESKTOP_DOWNLOAD_URL } from '../../config/downloadApp'
import { IS_LOCAL_APP } from '../../config'

const BENEFITS = [
  { Icon: CounterIcon, title: 'One catalogue. More ways to sell.', copy: 'Retail, wholesale and distributor prices on the same item. A counter that works the way you do.' },
  { Icon: InventoryIcon, title: 'See the whole stock story.', copy: 'Connect supplier purchases, quantities, batches and expiry dates in one workspace.' },
  { Icon: ReportsIcon, title: 'Every balance, in view.', copy: 'Keep customer and supplier dues beside invoices, receipts and part payments.' },
]

export default function RegistrationStory() {
  const [open, setOpen] = useState(() => !window.matchMedia?.('(max-width: 600px)').matches)

  useEffect(() => {
    const viewport = window.matchMedia?.('(max-width: 600px)')
    if (!viewport) return
    const update = () => setOpen(!viewport.matches)
    update()
    viewport.addEventListener('change', update)
    return () => viewport.removeEventListener('change', update)
  }, [])

  return <details className="registration-story-disclosure" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Why STATER Bill?</summary>
    <div className="registration-story">
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
      <p>{IS_LOCAL_APP ? 'Your counter can keep moving offline. Connect your browser when you choose Local + Cloud.' : 'Start in your browser. Bring the same business to your desktop when you need an offline counter.'}</p>
      {!IS_LOCAL_APP && <><span className="registration-desktop-note">Recommended for POS &amp; Counters</span><a className="registration-download" href={DESKTOP_DOWNLOAD_URL} target="_blank" rel="noopener noreferrer">Download Desktop App <span aria-hidden="true">↗</span></a></>}
    </section>
    <p className="registration-support">A little help getting started? <a href="mailto:support@staterbill.com">support@staterbill.com</a></p>
  </div>
  </details>
}
