import React, { useEffect, useId, useMemo, useState } from 'react'
import { CheckIcon, MonitorIcon, MoonIcon, SunIcon } from '../Icons'
import Modal from '../Modal'
import { useAppearance } from '../../hooks/useAppearance'
import {
  APPEARANCE_PALETTES,
  getCustomPalettes,
  saveCustomPalette,
  deleteCustomPalette,
  buildCustomPalette,
  normalizeHexColor,
  themeForeground,
} from '../../utils/appearance'
import './appearance.css'

const MODES = [
  { id: 'light', label: 'Light', Icon: SunIcon, hint: 'Bright and clear' },
  { id: 'dark', label: 'Dark', Icon: MoonIcon, hint: 'Easy on the eyes' },
  { id: 'system', label: 'System', Icon: MonitorIcon, hint: 'Match your device' },
]

function PaletteColourInput({ id, label, value, onChange, fallback }) {
  const valid = Boolean(normalizeHexColor(value))
  return (
    <div className="palette-color-row">
      <label htmlFor={id}>{label}</label>
      <div className="palette-color-inputs">
        <input type="color" aria-label={`${label} picker`} value={normalizeHexColor(value) || fallback}
          onChange={e => onChange(e.target.value)} />
        <input id={id} type="text" value={value} onChange={e => onChange(e.target.value)}
          maxLength={7} spellCheck={false} aria-invalid={!valid} aria-describedby={!valid ? `${id}-error` : undefined} />
      </div>
      {!valid && <span id={`${id}-error`} role="alert" className="palette-color-error">Enter a valid hex colour, such as #c15f3c.</span>}
    </div>
  )
}

export default function AppearanceSettings() {
  const { theme, setTheme, accent, setAccent, resolvedTheme, user, paletteLibraryKey, libraryRevision } = useAppearance()
  const customPalettes = useMemo(() => getCustomPalettes(user), [paletteLibraryKey, libraryRevision])
  const formId = useId()
  const [showAddModal, setShowAddModal] = useState(false)
  const [customName, setCustomName] = useState('')
  const [accentColor, setAccentColor] = useState('#c15f3c')
  const [sidebarColor, setSidebarColor] = useState('#f4efeb')
  const [surfaceColor, setSurfaceColor] = useState('#ffffff')

  useEffect(() => { setShowAddModal(false) }, [paletteLibraryKey])

  const validColours = [accentColor, sidebarColor, surfaceColor].every(colour => normalizeHexColor(colour))
  const savePalette = event => {
    event.preventDefault()
    if (!validColours || !customName.trim()) return
    const newPalette = buildCustomPalette(customName.trim(), {
      accent: accentColor,
      sidebar: sidebarColor,
      surface: surfaceColor,
      selection: accentColor,
    })
    saveCustomPalette(user, newPalette)
    setAccent(newPalette.id)
    setShowAddModal(false)
  }

  return (
    <section className="appearance-panel" aria-labelledby="appearance-title" id="set-appearance">
      <div className="appearance-heading">
        <div>
          <h2 id="appearance-title">Appearance</h2>
          <p>Make your workspace feel like yours.</p>
        </div>
        <span className="appearance-saved"><CheckIcon size={13} /> Saved automatically</span>
      </div>

      <fieldset className="appearance-fieldset">
        <legend>Colour mode</legend>
        <div className="appearance-mode-grid">
          {MODES.map(({ id, label, Icon, hint }) => (
            <button key={id} type="button" className={`appearance-mode ${theme === id ? 'is-selected' : ''}`}
              aria-pressed={theme === id} aria-label={`${label} mode`} onClick={() => setTheme(id)}>
              <span className={`appearance-mode-preview preview-${id}`} aria-hidden="true">
                <span className="appearance-preview-sidebar" /><span className="appearance-preview-content"><i /><i /><b /></span>
              </span>
              <span className="appearance-option-label"><Icon size={16} /><strong>{label}</strong>
                {theme === id && <CheckIcon size={14} />}
              </span>
              <span className="appearance-option-hint">{hint}</span>
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="appearance-fieldset">
        <legend>Accent palette</legend>
        <p className="appearance-field-help">Coordinated colours for navigation, buttons, and highlights in either mode.</p>

        {/* Single scrollable card row */}
        <div
          className="appearance-palette-scroll"
          onWheel={(e) => {
            if (e.deltaY !== 0 && e.currentTarget) {
              e.currentTarget.scrollLeft += e.deltaY
            }
          }}
        >
          {/* Preset palettes */}
          {APPEARANCE_PALETTES.map(palette => {
            const colours = palette[resolvedTheme]
            return (
              <button key={palette.id} type="button" className={`appearance-palette ${accent === palette.id ? 'is-selected' : ''}`}
                aria-pressed={accent === palette.id} aria-label={`${palette.name} palette`} onClick={() => setAccent(palette.id)}>
                <span className="appearance-palette-preview" aria-hidden="true" style={{ background: colours.canvas, '--preview-soft': colours.soft, '--preview-accent': colours.solid }}>
                  <span className="appearance-palette-rail"><i /><i /><i /></span>
                  <span className="appearance-palette-lines"><i /><i /><b /></span>
                </span>
                <span className="appearance-option-label"><span className="appearance-colour-dot" style={{ background: colours.accent }} />
                  <strong>{palette.name}</strong>{accent === palette.id && <CheckIcon size={14} />}
                </span>
                <span className="appearance-option-hint">{palette.description}</span>
              </button>
            )
          })}

          {/* Custom user-created palettes */}
          {customPalettes.map(palette => {
            const colours = palette[resolvedTheme] || palette.light
            return (
              <div key={palette.id} className="appearance-custom-palette">
              <button
                type="button"
                className={`appearance-palette ${accent === palette.id ? 'is-selected' : ''}`}
                aria-pressed={accent === palette.id}
                aria-label={`${palette.name} palette`}
                onClick={() => setAccent(palette.id)}
              >
                <span
                  className="appearance-palette-preview"
                  aria-hidden="true"
                  style={{
                    background: colours.canvas,
                    '--preview-soft': colours.soft,
                    '--preview-accent': colours.solid || colours.accent,
                  }}
                >
                  <span className="appearance-palette-rail"><i /><i /><i /></span>
                  <span className="appearance-palette-lines"><i /><i /><b /></span>
                </span>
                <span className="appearance-option-label">
                  <span className="appearance-colour-dot" style={{ background: colours.accent }} />
                  <strong>{palette.name}</strong>
                  {accent === palette.id && <CheckIcon size={14} />}
                </span>
                <span className="appearance-option-hint">{palette.description || 'Custom palette'}</span>
              </button>
              <button type="button" className="appearance-palette-delete" title="Delete custom palette"
                aria-label={`Delete ${palette.name} palette`}
                onClick={() => {
                  deleteCustomPalette(user, palette.id)
                  if (accent === palette.id) setAccent('terracotta')
                }}>
                ✕
              </button>
              </div>
            )
          })}

          {/* + Card for custom built */}
          <button
            type="button"
            className="appearance-palette-add"
            aria-label="Add custom palette"
            onClick={() => {
              setCustomName(`Palette ${customPalettes.length + 1}`)
              setAccentColor('#c15f3c')
              setSidebarColor('#f4efeb')
              setSurfaceColor('#ffffff')
              setShowAddModal(true)
            }}
          >
            <div className="add-icon-circle">+</div>
            <strong style={{ fontSize: '0.81rem', color: 'var(--text-primary)' }}>New Palette</strong>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Build custom</span>
          </button>
        </div>
      </fieldset>
      <p className="appearance-device-note">These preferences are saved for your account on this device.</p>

      <Modal open={showAddModal} title="Create Custom Palette" onClose={() => setShowAddModal(false)} size="palette"
        footer={<>
          <button type="button" className="btn btn-secondary" onClick={() => setShowAddModal(false)}>Cancel</button>
          <button type="submit" form={formId} className="btn btn-primary" disabled={!validColours || !customName.trim()}>Save Palette</button>
        </>}>
          <form id={formId} onSubmit={savePalette} className="palette-modal-form">
            <p style={{ margin: 0, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Choose accent and surface colours for your workspace. Your custom palette will be saved and selectable anytime.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label htmlFor={`${formId}-name`} style={{ fontSize: '0.8rem', fontWeight: 600 }}>Palette Name</label>
              <input
                id={`${formId}-name`}
                className="form-input"
                type="text"
                value={customName}
                onChange={e => setCustomName(e.target.value)}
                placeholder="e.g. Amber Sunrise"
                style={{ width: '100%' }}
              />
            </div>

            <PaletteColourInput id={`${formId}-accent`} label="Accent & Brand Colour" value={accentColor} onChange={setAccentColor} fallback="#c15f3c" />
            <PaletteColourInput id={`${formId}-sidebar`} label="Sidebar Navigation Colour" value={sidebarColor} onChange={setSidebarColor} fallback="#f4efeb" />
            <PaletteColourInput id={`${formId}-surface`} label="Card / Canvas Surface" value={surfaceColor} onChange={setSurfaceColor} fallback="#ffffff" />

            {/* Live Mini Preview */}
            <div style={{
              marginTop: 4,
              padding: 12,
              borderRadius: 8,
              border: '1px solid var(--border)',
              background: surfaceColor,
              display: 'flex',
              gap: 12,
              alignItems: 'center',
            }}>
              <div style={{
                width: 40,
                height: 48,
                borderRadius: 4,
                background: sidebarColor,
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
                padding: 4,
              }}>
                <span style={{ width: '80%', height: 3, background: accentColor, borderRadius: 2 }} />
                <span style={{ width: '60%', height: 3, background: 'rgba(0,0,0,0.15)', borderRadius: 2 }} />
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: themeForeground(normalizeHexColor(surfaceColor) || '#ffffff') }}>
                  {customName || 'Custom'} Preview
                </span>
                <button
                  type="button"
                  style={{
                    alignSelf: 'flex-start',
                    padding: '3px 10px',
                    borderRadius: 4,
                    background: accentColor,
                    color: themeForeground(normalizeHexColor(accentColor) || '#c15f3c'),
                    border: 'none',
                    fontSize: '0.72rem',
                    fontWeight: 600,
                  }}
                >
                  Action Button
                </button>
              </div>
            </div>

          </form>
      </Modal>
    </section>
  )
}
