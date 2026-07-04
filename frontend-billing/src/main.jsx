import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { initTelemetry } from './utils/telemetry'

// Capture unhandled frontend errors → backend telemetry (local + cloud),
// visible in the Admin Console's Telemetry & Logs tab.
initTelemetry()

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
