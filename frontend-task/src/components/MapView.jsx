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
    iconSize: [30, 30],
    iconAnchor: [15, 15],
    html: `<div style="width:30px;height:30px;border-radius:50%;background:${color};color:#fff;border:2.5px solid #fff;
      box-shadow:0 2px 8px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;
      font:800 12px 'DM Sans',sans-serif">${escapeHtml(label)}</div>`,
  })
}

function agentDot() {
  return L.divIcon({
    className: '',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    html: `<div style="position:relative;width:28px;height:28px;display:flex;align-items:center;justify-content:center;">
      <div style="position:absolute;inset:0;border-radius:50%;background:rgba(37,99,235,0.35);animation:radarPulse 2s infinite;"></div>
      <div style="width:14px;height:14px;border-radius:50%;background:#2563eb;border:2.5px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.4);"></div>
    </div>`,
  })
}

/**
 * markers: [{ id, lat, lng, color, label, popup, isAgent, stopId }]
 * paths:   [{ id, points: [[lat,lng],…], color, dashArray }]
 */
export default function MapView({
  markers = [],
  paths = [],
  className = 'map',
  fitKey,
  onMarkerClick,
  centerOn,
  preserveView = false,
  children,
}) {
  const el = useRef(null)
  const map = useRef(null)
  const layer = useRef(null)
  const onClick = useRef(onMarkerClick)
  onClick.current = onMarkerClick
  const fitted = useRef(null)
  const geometryKey = JSON.stringify({ markers, paths })

  useEffect(() => {
    map.current = L.map(el.current, { zoomControl: true, attributionControl: true }).setView(INDIA, 5)
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    const g = layer.current
    if (!g) return
    g.clearLayers()
    const bounds = []
    for (const p of paths) {
      if (p.points.length > 1) {
        L.polyline(p.points, {
          color: p.color || '#c15f3c',
          weight: 4,
          opacity: 0.85,
          dashArray: p.dashArray,
        }).addTo(g)
        bounds.push(...p.points)
      }
    }
    for (const m of markers) {
      if (m.lat == null || m.lng == null) continue
      const icon = m.isAgent ? agentDot() : dot(m.color || '#c15f3c', m.label)
      const mk = L.marker([m.lat, m.lng], { icon }).addTo(g)
      if (m.popup) mk.bindPopup(m.popup)
      mk.on('click', () => onClick.current?.(m))
      bounds.push([m.lat, m.lng])
    }
    // Live GPS updates should redraw the route without undoing a user's pan.
    if (bounds.length && (!preserveView || fitted.current !== (fitKey ?? 'initial')) && !centerOn) fitRoute()
    function fitRoute() {
      if (bounds.length === 1) map.current?.setView(bounds[0], 15)
      else map.current?.fitBounds(bounds, { padding: [36, 36], maxZoom: 16 })
      fitted.current = fitKey ?? 'initial'
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometryKey, fitKey, preserveView])

  useEffect(() => {
    if (centerOn?.lat != null && centerOn?.lng != null) {
      map.current?.setView([centerOn.lat, centerOn.lng], centerOn.zoom || 15, { animate: true })
    }
  }, [centerOn])

  useEffect(() => {
    const resize = () => map.current?.invalidateSize({ pan: false })
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
    if (el.current) observer?.observe(el.current)
    resize()
    window.addEventListener('resize', resize)
    return () => { observer?.disconnect(); window.removeEventListener('resize', resize) }
  }, [className])

  return (
    <div style={{ position: 'relative' }}>
      <div ref={el} className={className} />
      {children}
    </div>
  )
}

export function escapeHtml(s) {
  return String(s ?? '').replace(
    /[&<>"']/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]),
  )
}
