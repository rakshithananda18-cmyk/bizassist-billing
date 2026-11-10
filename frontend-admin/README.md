# BizAssist administration

The private STATER Bill operations workspace for business support, adoption, usage, diagnostics, and platform maintenance.

Run commands from `frontend-admin`:

```sh
npm install
npm run dev
npm test
npm run build
```

Development runs at `http://localhost:5175/admin/login` and uses the backend at `http://localhost:8001` by default. Set `VITE_API_URL` to override the backend and `VITE_BILLING_URL` to override the merchant sign-in destination. Use an assigned administrator account; two-factor authentication appears when required by the backend.

The shared workspace palette, sidebar, controls, tables, and responsive behavior live in `src/styles/experience.css`. The overview, business directory, and sign-in screen have dedicated style files. Both light and dark themes respect the saved admin preference, with reduced motion support.

Overview figures come from the business directory response. Infrastructure readings distinguish unavailable data from measured zero; cloud cost figures are labelled estimates. Failed refreshes retain known data with a retry action. Tests cover these states, authentication and two-factor flows, directory actions, and keyboard/mobile navigation.
