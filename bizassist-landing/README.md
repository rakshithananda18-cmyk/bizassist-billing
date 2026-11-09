# BizAssist Landing Page

Standalone marketing site for BizAssist. **Completely independent of the app code** — deploy this folder alone to Vercel or Cloudflare Pages.

The guided tour embeds the billing app itself with disposable sample data, so its screens stay aligned with the product. Deploy the updated `frontend-billing` app before this landing page; the player needs its trusted tour-message controller.

## Run locally

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # → dist/
```

Run `frontend-billing` alongside this site (port 5174 by default). Set `VITE_BILLING_APP_URL` in the landing environment to use another app URL or port. Production defaults to `https://app.staterbill.com`. For a landing preview on a different origin, set the app's `VITE_LANDING_URL` to that exact origin and allow it in the app's `frame-ancestors` hosting policy.

The six chapters use real Home, Dashboard, Billing Counter, Stock & Items, Purchases and Contacts screens. Playback pauses offscreen or in a hidden tab. Visitors can pause, replay or select a chapter while continuing to scroll the landing page. Selected advanced pricing and analytics details are protected in the public preview. App Settings, B2B and POS Live stay locked in demo mode.

The player offers guided playback. Clicking it or its trial CTA opens registration directly; existing users can choose Sign in. The name/phone form and browser-local lead flow have been removed. Application authorization remains responsible for access to account-only data and workflows; preview masking limits what the public tour shows.

## Deploy

**Vercel:** import the repo → set **Root Directory** to `bizassist-landing` → framework auto-detects Vite. (Or move this folder to its own repo — nothing in here imports app code.)

**Cloudflare Pages:** build command `npm run build`, output dir `dist`, root dir `bizassist-landing`.

## Dynamic download button

`src/useLatestRelease.js` queries
`https://api.github.com/repos/rakshithananda18-cmyk/bizassist-billing/releases/latest`
at page load and links the buttons to the newest `.exe` / `.dmg` assets published
by `.github/workflows/release.yml`. If the API is unreachable (rate limit,
offline), buttons fall back to the GitHub Releases page.

⚠ If the repo goes **private**, the anonymous Releases API stops working —
move releases to a public repo (change `GITHUB_OWNER`/`GITHUB_REPO` in
`useLatestRelease.js`) or host installers on S3/R2 and point the constants there.
