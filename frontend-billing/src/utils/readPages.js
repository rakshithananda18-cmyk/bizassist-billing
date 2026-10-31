// Follow the server's continuation contract; never silently truncate a catalogue.
export async function readList(authFetch, path, { signal } = {}) {
  const response = await authFetch(path, ...(signal ? [{ signal }] : []))
  if (!response.ok) throw new Error(`Records unavailable: HTTP ${response.status}`)
  const data = await response.json()
  if (!Array.isArray(data)) throw new Error('The server returned an invalid record list')
  return data
}

export async function readAllPages(authFetch, path, { pageSize = 500, signal } = {}) {
  const rows = [], seen = new Set()
  const [pathname, query = ''] = path.split('?')
  for (let page = 1; ; page++) {
    if (signal?.aborted) throw new DOMException('Cancelled', 'AbortError')
    const params = new URLSearchParams(query)
    params.set('page', page); params.set('per_page', pageSize)
    const response = await authFetch(`${pathname}?${params}`, ...(signal ? [{ signal }] : []))
    if (!response.ok) throw new Error(`Records unavailable: HTTP ${response.status}`)
    const data = await response.json()
    const items = Array.isArray(data) ? data : data?.items
    if (!Array.isArray(items)) throw new Error('The server returned an invalid page')
    if (!items.length) {
      if (data?.total != null && rows.length < Number(data.total)) throw new Error('A server page is missing; refresh to retry')
      break
    }
    let added = 0
    for (const item of items) {
      const key = item.uid || item.id || item.invoice_no
      if (key != null && seen.has(String(key))) continue
      if (key != null) seen.add(String(key))
      rows.push(item); added++
    }
    if (!added) throw new Error('The server repeated a page; refresh to retry')
    if (data?.total != null) {
      if (!Number.isFinite(Number(data.total)) || Number(data.total) < 0) throw new Error('The server returned an invalid record count')
      if (rows.length >= Number(data.total)) break
    } else if (items.length < pageSize) break
  }
  return rows
}
