// components/MapView.jsx — Leaflet + OpenStreetMap tiles (no API key, no bill).
// OSM's public tile server is for light use with attribution; set
// VITE_MAP_TILE_URL to a commercial/self-hosted tile URL if usage grows
// (docs/FIELD_TEAM_MASTER_PLAN.md §Maps).
import React, { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const ATTRIBUTION = import.meta.env.VITE_MAP_ATTRIBUTION || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const INDIA = [20.59, 78.96]

function dot(color, label) {
  return L.divIcon({
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<div style="width:28px;height:28px;border-radius:50%;background:${color};color:#fff;border:2px solid #fff;
      box-shadow:0 1px 4px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;
      font:700 11px 'DM Sans',sans-serif">${label ?? ''}</div>`,
  })
}

/**
 * markers: [{ id, lat, lng, color, label, popup }]
 * paths:   [{ id, points: [[lat,lng],…], color }]
 */
export default function MapView({ markers = [], paths = [], className = 'map', fitKey }) {
  const el = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)

  useEffect(() => {
    map.current = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(INDIA, 5)
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => { map.current.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const g = layer.current
    if (!g) return
    g.clearLayers()
    const bounds = []
    for (const p of paths) {
      if (p.points.length > 1) {
        L.polyline(p.points, { color: p.color || '#c15f3c', weight: 4, opacity: 0.75 }).addTo(g)
        bounds.push(...p.points)
      }
    }
    for (const m of markers) {
      if (m.lat == null || m.lng == null) continue
      const mk = L.marker([m.lat, m.lng], { icon: dot(m.color || '#c15f3c', m.label) }).addTo(g)
      if (m.popup) mk.bindPopup(m.popup)
      bounds.push([m.lat, m.lng])
    }
    if (bounds.length === 1) map.current.setView(bounds[0], 15)
    else if (bounds.length > 1) map.current.fitBounds(bounds, { padding: [30, 30], maxZoom: 16 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, JSON.stringify(markers.map(m => [m.id, m.lat, m.lng, m.label])), JSON.stringify(paths.map(p => p.points.length))])

  return <div ref={el} className={className} />
}

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}
