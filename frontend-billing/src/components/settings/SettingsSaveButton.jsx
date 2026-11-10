import React from 'react'
import { CheckIcon } from '../Icons'
import './settingsSaveButton.css'

const STATES = {
  saved: { label: 'Saved', hint: 'All changes are saved automatically. Click to save again.' },
  saving: { label: 'Saving…', hint: 'Saving your latest changes.' },
  unsaved: { label: 'Save Changes', hint: 'Unsaved changes. Autosave will save shortly, or click to save now.' },
  error: { label: 'Retry Save', hint: 'Changes could not be saved. Click to retry.' },
}

export default function SettingsSaveButton({ saveStatus, saving, onSave }) {
  const state = saving ? 'saving' : saveStatus
  const { label, hint } = STATES[state] || STATES.unsaved
  return (
    <button
      type="button"
      className={`btn ${state === 'error' ? 'btn-danger' : 'btn-primary'} settings-save-button`}
      data-save-state={state}
      title={hint}
      onClick={onSave}
      disabled={state === 'saving'}
      aria-busy={state === 'saving'}
    >
      {state === 'saving'
        ? <span className="spinner settings-save-spinner" aria-hidden="true" />
        : <CheckIcon size={15} />}
      <span aria-live="polite" aria-atomic="true">{label}</span>
    </button>
  )
}
