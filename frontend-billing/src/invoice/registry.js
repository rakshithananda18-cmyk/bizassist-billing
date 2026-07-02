// src/invoice/registry.js — the invoice template registry (plan Phase 1).
// =======================================================================
// ONE normalized payload, MANY renderers. Every template here is a PURE
// function of (payload) — no fetching, no state, no money math. Adding a
// template = one import + one entry. Unknown keys fall back to `classic`
// and the caller reports `template_fallback_used` (never a blank invoice).
import ClassicA4 from './templates/ClassicA4'
import ModernA4 from './templates/ModernA4'
import ThermalCompact from './templates/ThermalCompact'

export const FALLBACK_TEMPLATE = 'classic'

export const TEMPLATES = {
  classic: {
    key: 'classic',
    label: 'Classic',
    description: 'Standard printed GST invoice — the market-familiar layout',
    paper: 'a4',
    component: ClassicA4,
  },
  modern: {
    key: 'modern',
    label: 'BizAssist',
    description: 'Modern BizAssist invoice — clean, premium, share-ready',
    paper: 'a4',
    component: ModernA4,
  },
  thermal: {
    key: 'thermal',
    label: 'Thermal',
    description: 'Compact 80mm receipt — counter-style reprint',
    paper: 'thermal_80mm',
    component: ThermalCompact,
  },
  // NOTE: the live POS print path (components/sales/ThermalReceipt) is a separate,
  // untouched surface — this entry renders SAVED invoices from the payload.
}

/** Resolve a template entry; unknown key → classic. Returns { entry, fellBack } */
export function resolveTemplate(key) {
  const entry = TEMPLATES[key]
  if (entry) return { entry, fellBack: false }
  return { entry: TEMPLATES[FALLBACK_TEMPLATE], fellBack: key != null && key !== '' }
}

export function templateOptions() {
  return Object.values(TEMPLATES).map(({ key, label, description }) => ({ key, label, description }))
}
