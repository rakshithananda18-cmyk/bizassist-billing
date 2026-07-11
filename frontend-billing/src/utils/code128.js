// src/utils/code128.js — minimal, dependency-free Code 128-B barcode encoder.
// ===========================================================================
// Emits the bar/space module widths for a value so LabelPrintModal can render
// crisp SVG barcodes offline (no CDN, works in the packaged desktop app).
// Code set B covers ASCII 32–126 — everything a SKU/EAN-as-text needs. Scanners
// read Code 128 universally, so labels printed here scan straight into the POS
// search box.
//
// Standard tables (Code 128 spec): each value 0–105 maps to six alternating
// bar/space widths totalling 11 modules; STOP (106) is seven widths (13).

const WIDTHS = [
  '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312',
  '132212', '221213', '221312', '231212', '112232', '122132', '122231', '113222',
  '123122', '123221', '223211', '221132', '221231', '213212', '223112', '312131',
  '311222', '321122', '321221', '312212', '322112', '322211', '212123', '212321',
  '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
  '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121',
  '313121', '211331', '231131', '213113', '213311', '213131', '311123', '311321',
  '331121', '312113', '312311', '332111', '314111', '221411', '431111', '111224',
  '111422', '121124', '121421', '141122', '141221', '112214', '112412', '122114',
  '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
  '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112',
  '421211', '212141', '214121', '412121', '111143', '111341', '131141', '114113',
  '114311', '411113', '411311', '113141', '114131', '311141', '411131', '211412',
  '211214', '211232',
]
const START_B = 104
const STOP = '2331112'

/** Sanitize to Code-128-B-encodable ASCII (32–126). */
export function sanitizeBarcodeValue(value) {
  return String(value || '')
    .split('')
    .filter(ch => ch.charCodeAt(0) >= 32 && ch.charCodeAt(0) <= 126)
    .join('')
    .slice(0, 48)
}

/**
 * Encode `value` → array of {width, bar} modules (bar=true means ink).
 * Returns null for an empty/unencodable value.
 */
export function encodeCode128B(value) {
  const text = sanitizeBarcodeValue(value)
  if (!text) return null

  const values = [START_B]
  for (const ch of text) values.push(ch.charCodeAt(0) - 32)
  let checksum = START_B
  for (let i = 1; i < values.length; i++) checksum += values[i] * i
  values.push(checksum % 103)

  let pattern = ''
  for (const v of values) pattern += WIDTHS[v]
  pattern += STOP

  const modules = []
  for (let i = 0; i < pattern.length; i++) {
    modules.push({ width: Number(pattern[i]), bar: i % 2 === 0 })
  }
  return modules
}

/**
 * Render `value` as an SVG string (bars only — caption is the caller's job).
 * `height` in px of the target coordinate system; module width = 1 unit,
 * viewBox width = total modules + 2×quiet zone (10 modules each side).
 */
export function code128Svg(value, { height = 40 } = {}) {
  const modules = encodeCode128B(value)
  if (!modules) return null
  const QUIET = 10
  const total = modules.reduce((s, m) => s + m.width, 0) + QUIET * 2
  let x = QUIET
  let rects = ''
  for (const m of modules) {
    if (m.bar) rects += `<rect x="${x}" y="0" width="${m.width}" height="${height}" fill="#000"/>`
    x += m.width
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${height}" preserveAspectRatio="none" style="width:100%;height:100%;display:block">${rects}</svg>`
}
