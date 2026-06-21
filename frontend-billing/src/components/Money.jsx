// src/components/Money.jsx — render an amount as Indian-rupee text.
// Wraps the shared `fmt` so money looks identical everywhere and can be styled
// (e.g. dim a zero, colour a negative) from one place later.
import React from 'react'
import { fmt } from '../utils/format'

export default function Money({ value, className = '', dimZero = false }) {
  const isZero = value == null || Number(value) === 0
  const cls = `${className}${dimZero && isZero ? ' text-muted' : ''}`.trim()
  return <span className={cls}>{fmt(value)}</span>
}
