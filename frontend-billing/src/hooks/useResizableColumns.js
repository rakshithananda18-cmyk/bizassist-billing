// ============================================================================
// hooks/useResizableColumns.js
// ----------------------------------------------------------------------------
// Drag-to-resize columns for any <table className="data-table">, with widths
// persisted per USER and per TABLE in localStorage.
//
//   const cols = useResizableColumns({
//     tableId: 'stock.products',
//     userId : user?.id,
//     columns: ['sku', 'name', 'qty'],
//   })
//
//   <table ref={cols.tableRef} className={`data-table ${cols.tableClassName}`}>
//     <thead><tr>
//       <th {...cols.headerProps('name')}>Item Name <ColumnResizer {...cols.resizerProps('name')} /></th>
//     </tr></thead>
//
// Behaviour
//   · drag the grip          → live resize, persisted on pointer-up
//   · double-click the grip  → auto-fit that column to its widest cell
//   · cols.resetWidths()     → clear every override (back to natural widths)
//   · cols.autoFitAll()      → size every column to its content in one pass
//
// Design notes
//   · Only columns the user actually touched are stored, so a future release
//     that adds a column doesn't need a migration — unknown keys are dropped
//     on load by sanitizeWidths(allowedKeys).
//   · `table-layout: fixed` is applied ONLY once at least one column has an
//     explicit width. Untouched tables keep the browser's natural sizing.
//   · Pointer events + setPointerCapture, so a fast drag that leaves the grip
//     (or the window) still tracks correctly and always ends cleanly.
// ============================================================================
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH,
  autoFitWidth, clampWidth, clearWidths, loadWidths, nextWidth, saveWidths,
} from '../lib/columnWidths'

/** CSS.escape with a fallback — older jsdom builds (and a few embedded
 *  webviews) don't ship it, and column keys are simple identifiers anyway. */
const cssEscape = (s) => (
  typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
    ? CSS.escape(String(s))
    : String(s).replace(/["\\]/g, '\\$&')
)

export function useResizableColumns({
  tableId,
  userId = null,
  columns = [],
  minWidth = MIN_COLUMN_WIDTH,
  maxWidth = MAX_COLUMN_WIDTH,
  enabled = true,
} = {}) {
  const tableRef = useRef(null)
  const columnsKey = columns.join('|')
  const allowed = useMemo(() => columns, [columnsKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const [widths, setWidths] = useState(() =>
    enabled && tableId ? loadWidths(tableId, userId, allowed) : {}
  )

  // Re-hydrate when the identity of the table or the user changes (e.g. a
  // different owner logs in on the same counter machine).
  useEffect(() => {
    if (!enabled || !tableId) return
    setWidths(loadWidths(tableId, userId, allowed))
  }, [tableId, userId, allowed, enabled])

  // Live drag state lives in a ref: pointermove must not re-render via state.
  const dragRef = useRef(null)
  const [draggingKey, setDraggingKey] = useState(null)

  const persist = useCallback((next) => {
    setWidths(next)
    if (tableId) saveWidths(tableId, userId, next)
  }, [tableId, userId])

  // ── Measurement ───────────────────────────────────────────────────────────
  /** Index of a column key within the rendered header row (skips any column
   *  not registered with this hook, e.g. a trailing actions cell). */
  const columnIndex = useCallback((colKey) => {
    const idx = columns.indexOf(colKey)
    return idx === -1 ? null : idx
  }, [columnsKey]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Current rendered width of a column, read from the live <th>. */
  const measureCurrent = useCallback((colKey) => {
    const th = tableRef.current?.querySelector(`[data-col="${cssEscape(colKey)}"]`)
    return th ? th.getBoundingClientRect().width : null
  }, [])

  /** Intrinsic content widths for a column: the header cell plus every body
   *  cell in that position. Widths are temporarily released so scrollWidth
   *  reports the *content* width rather than the currently-forced width. */
  const measureContent = useCallback((colKey) => {
    const table = tableRef.current
    const idx = columnIndex(colKey)
    if (!table || idx == null) return []

    const th = table.querySelector(`[data-col="${cssEscape(colKey)}"]`)
    const cells = []
    if (th) cells.push(th)
    table.querySelectorAll('tbody > tr').forEach((tr) => {
      // Skip full-width rows (empty state / colspan messages).
      if (tr.children.length !== table.querySelectorAll('thead th').length) return
      const td = tr.children[idx]
      if (td) cells.push(td)
    })

    const previous = cells.map((c) => c.style.width)
    cells.forEach((c) => { c.style.width = 'auto' })
    const measured = cells.map((c) => c.scrollWidth)
    cells.forEach((c, i) => { c.style.width = previous[i] })
    return measured
  }, [columnIndex])

  // ── Drag ──────────────────────────────────────────────────────────────────
  const onPointerMove = useCallback((e) => {
    const d = dragRef.current
    if (!d) return
    const w = nextWidth(d.startWidth, d.startX, e.clientX, minWidth, maxWidth)
    if (w == null) return
    d.latest = w
    // Write straight to the DOM during the drag — smooth at 60fps and avoids
    // re-rendering a 500-row table on every pointermove. State is reconciled
    // once, on pointerup.
    const th = tableRef.current?.querySelector(`[data-col="${cssEscape(d.colKey)}"]`)
    if (th) {
      th.style.width = `${w}px`; th.style.minWidth = `${w}px`; th.style.maxWidth = `${w}px`
      // `--col-w` is what the `[style*="--col-w"]` CSS hook keys off. Some
      // tables (the POS cart) hard-code per-column widths with !important,
      // which an inline width can never beat — but an !important rule that
      // READS this property can.
      th.style.setProperty('--col-w', `${w}px`)
    }
  }, [minWidth, maxWidth])

  const endDrag = useCallback(() => {
    const d = dragRef.current
    dragRef.current = null
    setDraggingKey(null)
    document.body.classList.remove('is-col-resizing')
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
    if (!d || d.latest == null) return
    persist({ ...widthsRef.current, [d.colKey]: d.latest })
  }, [onPointerMove, persist])

  // Keep a ref of the latest widths so endDrag doesn't need them as a dep
  // (which would re-bind the window listeners mid-drag).
  const widthsRef = useRef(widths)
  useEffect(() => { widthsRef.current = widths }, [widths])

  const startResize = useCallback((colKey) => (e) => {
    if (!enabled) return
    e.preventDefault()
    e.stopPropagation()          // never trigger the header's sort handler
    const startWidth = widthsRef.current[colKey] ?? measureCurrent(colKey) ?? minWidth
    dragRef.current = { colKey, startX: e.clientX, startWidth, latest: null }
    setDraggingKey(colKey)
    document.body.classList.add('is-col-resizing')
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', endDrag)
    window.addEventListener('pointercancel', endDrag)
  }, [enabled, measureCurrent, minWidth, onPointerMove, endDrag])

  useEffect(() => () => {
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
    document.body.classList.remove('is-col-resizing')
  }, [onPointerMove, endDrag])

  // ── Auto-fit / reset ──────────────────────────────────────────────────────
  const autoFit = useCallback((colKey) => {
    const w = autoFitWidth(measureContent(colKey), undefined, minWidth, maxWidth)
    if (w == null) return
    persist({ ...widthsRef.current, [colKey]: w })
  }, [measureContent, minWidth, maxWidth, persist])

  const autoFitAll = useCallback(() => {
    const next = {}
    columns.forEach((k) => {
      const w = autoFitWidth(measureContent(k), undefined, minWidth, maxWidth)
      if (w != null) next[k] = w
    })
    persist(next)
  }, [columnsKey, measureContent, minWidth, maxWidth, persist]) // eslint-disable-line react-hooks/exhaustive-deps

  const resetWidths = useCallback(() => {
    // Release any inline widths written directly to the DOM during a drag,
    // otherwise the cleared state wouldn't visibly take effect.
    tableRef.current?.querySelectorAll('[data-col]').forEach((th) => {
      th.style.width = ''; th.style.minWidth = ''; th.style.maxWidth = ''
      th.style.removeProperty('--col-w')
    })
    setWidths({})
    if (tableId) clearWidths(tableId, userId)
  }, [tableId, userId])

  const setWidth = useCallback((colKey, px) => {
    const w = clampWidth(px, minWidth, maxWidth)
    if (w == null) return
    persist({ ...widthsRef.current, [colKey]: w })
  }, [minWidth, maxWidth, persist])

  // ── Render props ──────────────────────────────────────────────────────────
  const isCustomized = Object.keys(widths).length > 0

  const headerProps = useCallback((colKey, extra = {}) => {
    const w = widths[colKey]
    const style = w
      ? { ...extra.style, width: w, minWidth: w, maxWidth: w, '--col-w': `${w}px` }
      : extra.style
    return {
      ...extra,
      'data-col': colKey,
      className: ['resizable-th', extra.className].filter(Boolean).join(' '),
      style,
    }
  }, [widths])

  const resizerProps = useCallback((colKey) => ({
    colKey,
    active: draggingKey === colKey,
    onResizeStart: startResize(colKey),
    onAutoFit: () => autoFit(colKey),
    disabled: !enabled,
  }), [draggingKey, startResize, autoFit, enabled])

  return {
    tableRef,
    widths,
    isCustomized,
    isResizing: draggingKey != null,
    tableClassName: (isCustomized || draggingKey != null) ? 'has-fixed-cols' : '',
    headerProps,
    resizerProps,
    startResize,
    setWidth,
    autoFit,
    autoFitAll,
    resetWidths,
  }
}

export default useResizableColumns
