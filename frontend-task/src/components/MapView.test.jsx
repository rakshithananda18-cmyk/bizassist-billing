// @vitest-environment jsdom
import React from 'react'
import { cleanup, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({
  setView: vi.fn(), fitBounds: vi.fn(), invalidateSize: vi.fn(), remove: vi.fn(),
  polyline: vi.fn(), marker: vi.fn(), map: vi.fn(), clearLayers: vi.fn(), clicks: [],
}))
vi.mock('leaflet', () => ({ default: {
  map: (...args) => { state.map(...args); const map = { setView: (...values) => { state.setView(...values); return map }, fitBounds: state.fitBounds, invalidateSize: state.invalidateSize, remove: state.remove }; return map },
  tileLayer: () => ({ addTo() {} }),
  layerGroup: () => ({ addTo() { return this }, clearLayers: state.clearLayers }),
  divIcon: options => options,
  polyline: (...args) => { state.polyline(...args); return { addTo() {} } },
  marker: (...args) => { state.marker(...args); return { addTo() { return this }, bindPopup() {}, on(_event, callback) { state.clicks.push(callback) } } },
} }))
import MapView from './MapView'
beforeEach(() => { vi.clearAllMocks(); state.clicks = [] })
afterEach(cleanup)
describe('interactive map updates', () => {
  it('centers when only the GPS/focus target changes and retains attribution', () => {
    const markers = [{ id: 1, lat: 12, lng: 77 }]
    const view = render(<MapView markers={markers} />)
    state.setView.mockClear()
    view.rerender(<MapView markers={markers} centerOn={{ lat: 13, lng: 78, zoom: 16 }} />)
    expect(state.setView).toHaveBeenCalledWith([13, 78], 16, { animate: true })
    expect(state.map.mock.calls[0][1].attributionControl).toBe(true)
  })
  it('redraws changed coordinates/colors of equal length without undoing a manual pan', () => {
    const markers = [{ id: 1, lat: 12, lng: 77, color: '#111', label: '<shop>' }]
    const view = render(<MapView preserveView markers={markers} paths={[{ points: [[12, 77], [13, 78]] }]} fitKey="route-1" />)
    state.fitBounds.mockClear()
    view.rerender(<MapView preserveView markers={[{ ...markers[0], color: '#222' }]} paths={[{ points: [[12, 77], [14, 79]] }]} fitKey="route-1" />)
    expect(state.polyline.mock.lastCall[0]).toEqual([[12, 77], [14, 79]])
    expect(state.marker.mock.lastCall[1].icon.html).toContain('#222')
    expect(state.marker.mock.lastCall[1].icon.html).toContain('&lt;shop&gt;')
    expect(state.fitBounds).not.toHaveBeenCalled()
    view.rerender(<MapView markers={markers} fitKey="route-2" className="map expanded" />)
    expect(state.invalidateSize).toHaveBeenCalled()
  })
  it('uses the current click callback without rebuilding unchanged markers', () => {
    const first = vi.fn(), second = vi.fn(), markers = [{ id: 1, lat: 12, lng: 77 }]
    const view = render(<MapView markers={markers} onMarkerClick={first} />)
    view.rerender(<MapView markers={markers} onMarkerClick={second} />)
    state.clicks[0]()
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith(markers[0])
  })
})
