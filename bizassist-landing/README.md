# BizAssist Landing Page

Standalone marketing site for BizAssist. **Completely independent of the app code** — deploy this folder alone to Vercel or Cloudflare Pages.

## Run locally

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # → dist/
```

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
