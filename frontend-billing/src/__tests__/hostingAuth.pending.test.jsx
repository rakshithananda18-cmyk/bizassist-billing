// Pending coverage scaffolds for the hosting/auth changes (audit T2–T5).
//
// These need the app's AuthProvider + MemoryRouter (and fetch mocks) to render
// Login/Register/Settings meaningfully. They're captured as `it.todo` so the
// intent is tracked and the suite stays green until the harness is added.
//
// Real, runnable tests already exist for: T1 (backend contract), T6 (loginSync),
// T7 (WebLocalOnlyNotice), T8/T9 (backend), plus logger.test.js.
import { describe, it } from 'vitest'

describe('Login staff resolution (T2)', () => {
  it.todo('shows the Staff button when local /staff-counters is empty but cloud has staff')
  it.todo('staffLogin: local failure falls back to cloud and switches the device to cloud')
  it.todo('a wrong password never falls through to the cloud as a success')
  it.todo('recent-login: an empty local result does not wipe cached staff or hide the choice')
})

describe('Signup hosting auto-config (T3)', () => {
  it.todo("signup({hosting:'hybrid'}) sets bizassist_hosting_mode=hybrid and provisions the cloud sync token")
  it.todo("signup({hosting:'local'}) stays local and navigates straight to the app")
  it.todo('setHostingMode(\"local\") persists mode WITHOUT logging the user out')
})

describe('Register two options (T4)', () => {
  it.todo('renders exactly two hosting choices: Local and Local + Cloud (no pure Cloud)')
  it.todo('forwards the chosen hosting to signup() and navigates to / (never /settings?switch=)')
})

describe('Settings two-mode switch (T5)', () => {
  it.todo('the pure-Cloud card is absent; a legacy cloud account shows as active "Local + Cloud"')
  it.todo('clicking Local switches instantly via setHostingMode (no preflight, no logout)')
  it.todo('clicking Local + Cloud while cloud is offline shows an error toast (no silent no-op)')
})
