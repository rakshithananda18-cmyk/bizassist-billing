/** Resume an SSE subscription across platform rotations and transient outages. */
export function createSseConnection({ fetchTicket, onEvent, onStatus, onGap, random = Math.random }) {
  let source = null, timer = null, degradedTimer = null, stopped = false
  let lastEventId = null, attempt = 0, generation = 0, degraded = false, connected = false
  const closeSource = () => { source?.close(); source = null }
  const markDown = () => {
    connected = false
    if (!degradedTimer && !degraded) degradedTimer = setTimeout(() => {
      degradedTimer = null
      if (!stopped && !connected) { degraded = true; onStatus?.('degraded') }
    }, 30000)
  }
  const schedule = rotation => {
    closeSource()
    if (stopped || timer) return
    if (!rotation) markDown()
    const delay = rotation ? random() * 1000 : Math.min(30000, 1000 * 2 ** Math.min(attempt++, 5)) * (0.7 + random() * 0.6)
    timer = setTimeout(() => { timer = null; void connect() }, Math.min(30000, delay))
  }
  const connect = async () => {
    if (stopped) return
    const run = ++generation
    closeSource()
    try {
      const target = await fetchTicket(lastEventId)
      if (stopped || run !== generation) return
      const url = new URL(typeof target === 'string' ? target : target.url, window.location.href)
      if (lastEventId) url.searchParams.set('last_event_id', lastEventId)
      const es = new EventSource(url.href)
      source = es
      const opened = () => {
        if (stopped || source !== es) return
        connected = true; attempt = 0
        clearTimeout(degradedTimer); degradedTimer = null
        const restored = degraded; degraded = false
        onStatus?.(restored ? 'restored' : 'connected')
      }
      es.onopen = opened
      es.addEventListener('hello', event => {
        if (stopped || source !== es) return
        opened()
        try {
          const hello = JSON.parse(event.data)
          if (hello.replay === 'gap' || hello.replay === 'none') {
            lastEventId = typeof hello.cursor === 'string' ? hello.cursor : null
            if (hello.replay === 'gap') onGap?.()
          }
        } catch { /* ignore malformed control frames */ }
      })
      es.addEventListener('rotate', () => { if (source === es) schedule(true) })
      es.onmessage = event => {
        if (stopped || source !== es) return
        if (event.lastEventId) lastEventId = event.lastEventId
        try { onEvent?.(JSON.parse(event.data)) } catch { /* malformed events never stop reconnects */ }
      }
      es.onerror = () => { if (source === es) schedule(false) }
    } catch { if (!stopped && run === generation) schedule(false) }
  }
  markDown()
  void connect()
  return {
    get readyState() { return source?.readyState ?? 0 },
    close() { stopped = true; generation++; clearTimeout(timer); clearTimeout(degradedTimer); closeSource() },
    reconnect() { if (!stopped) { generation++; clearTimeout(timer); timer = null; markDown(); void connect() } },
  }
}
