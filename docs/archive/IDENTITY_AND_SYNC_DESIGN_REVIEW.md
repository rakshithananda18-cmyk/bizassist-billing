# Identity & Sync — Design Review and Recommendation

*Date: 2026-06-26. Question: how should a business's identity (account + BizID) and its data be created and reconciled across a local (on-device SQLite) backend and a cloud (Postgres) backend, given that **cloud can be queried from anywhere but local cannot be reached from outside the machine**, including the offline-registration case.*

Companion: [`SYNC_MIGRATION_AUDIT.md`](SYNC_MIGRATION_AUDIT.md) · [`MANUAL_TEST_PLAN.md`](MANUAL_TEST_PLAN.md) · [`MASTER_PLAN_CORE.md`](MASTER_PLAN_CORE.md)

---

## 1. The problem, stated precisely

The same business can come into existence on **two independent databases**:
- Register on the **web** → a cloud account + a cloud BizID.
- Register on the **downloaded app** → a local account + a local BizID.

Today each DB mints its own BizID (`generate_bizid` checks collisions only **within its own DB**), and entity rows use per-DB autoincrement integer ids. That creates three risks:
1. **Duplicate identity** — one real business, two accounts/BizIDs.
2. **Cross-DB BizID collision** — two *different* businesses randomly get the same `BA-XXXXXX`; matching on it could mis-route data (cross-tenant).
3. **Entity-id collision** — local `invoice id=10` ≠ cloud `invoice id=10`.

This is the classic **"two-ID problem"**: an id you can mint locally while offline is *not* safe to use as a global key. ([danlew](https://blog.danlew.net/2017/03/09/the-two-id-problem/), [Eric Elliott](https://medium.com/javascript-scene/identity-crisis-how-modern-applications-generate-unique-ids-39562736f557))

## 2. The constraint that decides the architecture

**Cloud is publicly reachable; local is not.** The cloud (HF Space) can be queried by anyone — including the downloaded app, which has internet. The local backend (`localhost:8001`) can never be reached from the cloud or another device.

Consequence: **you never query local from outside. Cloud must be the registry / source of authority for identity.** Local always *defers to* and *reconciles with* cloud. There is no symmetric "check both" — there is "always check cloud; local catches up when it can."

## 3. How comparable systems solve this

| Pattern | What they do | Takeaway for us |
|---|---|---|
| **Local-first / sync engines** (PouchDB/Couchbase, RxDB, Firebase offline, Actual Budget) | Clients generate **globally-unique IDs** (UUID/ULID/Cuid2) so offline-created rows never collide on sync; the server is the registry. ([Couchbase](https://www.couchbase.com/blog/offline-first-more-reliable-mobile-apps/), [UUID/Wikipedia](https://en.wikipedia.org/wiki/Universally_unique_identifier)) | Use a **globally-unique key** for synced entities — don't use the local autoincrement id as the cross-DB key. |
| **Offline-first mobile** (Android Architecture, Mendix, Dynamics) | **Defer writes** to a queue, **reconcile on reconnect**; the **network resolves conflicts** (last writer wins). ([Android](https://developer.android.com/topic/architecture/data-layer/offline-first), [Mendix](https://docs.mendix.com/refguide/mobile/building-efficient-mobile-apps/offlinefirst-data/synchronization/)) | Offline registration is fine **if** it's provisional and reconciled against the cloud on first connect. |
| **Auth / identity systems** (Auth0, Ory, WorkOS, Descope) | **Link-on-login**: two accounts are merged only after the user **authenticates** into both. **Never silently auto-merge by email** — it's an account-takeover vector. ([WorkOS](https://workos.com/blog/lessons-in-safe-identity-linking), [Ory](https://www.ory.com/blog/secure-account-linking-iam-sso-oidc-saml), [Auth0](https://auth0.com/docs/manage-users/user-accounts/user-account-linking/link-user-accounts)) | Linking a local account to a cloud account must require **cloud login**. Show *minimal* info before auth (no business details — enumeration/PII risk). |
| **Cloud SMB tools** (QuickBooks Online, Zoho, Square) | The **cloud account is the identity**; the device app is a cache/POS that signs in to that one account. | "Cloud-issued identity, device mirrors it" is the dominant, proven shape. |

Two consistent lessons emerge: **(a) global identity must be issued by a single authority (the cloud) or be a UUID; (b) merging identities must be verified by authentication, never inferred silently.**

## 4. Candidate approaches (pros / cons)

**A. Local-first, reconcile later** — create local account + provisional BizID; claim/link with cloud on connect.
- ✅ Works fully offline; respects "Local Only" users.
- ❌ Most moving parts (provisional state, claim, collision reassignment); BizID unverified until reconciled.

**B. Cloud-first, local mirror** — when online, create the account on **cloud first** (cloud mints BizID), then mirror to local.
- ✅ BizID unique & authoritative from creation; duplicate-check is inherent (cloud enforces email/phone); "owner on both" is automatically one account.
- ❌ Requires internet at signup → still needs an offline fallback.

**C. Dual-write at registration** — create on local and cloud simultaneously.
- ✅ Data present on both immediately.
- ❌ If you write local *first*, you reintroduce collision; if cloud-first, it's just (B). Two-phase write also needs failure handling (cloud ok, local fails, or vice-versa).

**D. Hybrid: cloud-first when online, provisional-local + reconcile when offline** — (B) with (A) as the offline fallback, plus link-on-login.
- ✅ Best of both: authoritative & unique online, still works offline, respects privacy opt-out.
- ❌ Slightly more to build (but each piece is small and you already have most of the sync plumbing).

## 5. Recommendation — **Approach D**, with three concrete rules

> **Cloud is the identity authority. Local is a fast, offline-capable mirror. Identities merge only by verified login. Synced entities carry a globally-unique key, not a local autoincrement id.**

Three rules that make it correct:

**Rule 1 — BizID is cloud-issued (single authority); registration needs a one-time network connection.**
Registration always goes through the cloud, so creating an account requires the device to be **online once**; the cloud mints the BizID and the device stores it. Because the BizID is never minted locally, the cross-DB collision risk is removed **by construction** — not merely mitigated. After that one-time registration, the app runs **fully offline** and syncs when it reconnects. *(If you later decide to support fully-offline first-registration, it would use a **`provisional`** BizID claimed from cloud on first connect — cloud reassigns on collision — but that is an optional mode, not the default.)*

**Rule 2 — Synced entities get a globally-unique `uid` (the two-ID solution).**
Keep the fast local integer `id` for local use, but add a `uid` (UUID/ULID) generated at row creation and **sync on `uid`**, not on `id`. This kills entity-id collisions without converting every primary key. (Your migration already has the *id-remap* path as an interim measure; `uid` is the durable fix.)

**Rule 3 — Linking is verified, never silent.**
To attach a local registration to an existing cloud account, the user **logs into the cloud account** (proves ownership). Before auth, show only "an account with this email already exists — log in to continue." Never auto-merge by email/username alone.

### How registration behaves per entry point

> **Registration requires a one-time network connection.** Accounts and BizIDs are always created on the cloud (the single authority), so the device must be online to *register*. Everything **after** registration — billing, reports, POS — works fully offline and syncs on reconnect.

| Entry point | Flow |
|---|---|
| **Web (browser → cloud)** | Check cloud for email/phone → exists ⇒ **log in**; else create cloud account + BizID. |
| **App, first-time, online** | `POST /api/identity/check {email/phone}` to **cloud** → exists ⇒ **log in & sync down** (adopt cloud BizID, mirror data); else cloud creates account + BizID and the app mirrors it locally. |
| **Already registered on the web, then downloads the app** | No new registration — the user just **logs in → data syncs down** to the device. *(This is the case you asked about: register on the URL, then download → direct login + sync. Correct.)* |
| **App, offline at first registration** | **Not supported** — registration needs the one-time connection. The app asks the user to connect once; after that it works offline. |
| **Privacy / fully-offline shop (optional, later)** | If you choose to support it, offer an explicit "Local Only" account with a **provisional** BizID, reconciled if/when they ever connect. Not part of the default flow. |

This directly answers your worries: **"local can't be queried"** → you never query local, you always reconcile *toward* cloud; **"what if no network"** → registration needs a **one-time** connection (the account/BizID is cloud-issued), and **everything after registration works offline**, with sync catching up on reconnect; **"register on web then download the app"** → just log in and the data syncs down — no duplicate account.

### Login (after registration) — local-first

Registration is online (cloud-issued); **login is local-first** on the downloaded app, so daily use is fast and offline-capable.

| Situation | Where login happens |
|---|---|
| **Account already on this device** (synced before) | **Local** backend — works offline. The user row, *including the password hash*, was mirrored during registration/sync-down, so the device can authenticate on its own. |
| **First login on a fresh device** (app installed, never synced) | **Cloud** (needs internet, once) — there's no local user yet. On success the account + data sync down; every login afterward is local/offline. |
| **Web app (browser)** | **Cloud** always — there is no local backend in the browser. |

Notes:
- **Tokens are interchangeable** — shared `JWT_SECRET` means a token minted by local is valid for cloud sync calls and vice-versa.
- **Password change while offline:** if the password is changed on cloud while the device is offline, the **previous** password still works locally until the next sync updates the user row (last-write-wins). This is the normal offline-first trade-off.
- **Mode interplay:** Local/Hybrid → login local (Hybrid syncs in the background); Cloud-only mode → login cloud.

**After login: identity check + divergence nudge — data sync stays gated.** Cloud data is subscription-gated, so login must **not** silently pull the dataset down. Two read-only, best-effort actions run (Local & Hybrid, downloaded app, online; Cloud mode skipped):
- **BizID consistency check** — read `/profile` on both backends and compare `public_id`; on mismatch, log a warning (the unify happens during backup/migration).
- **Divergence sense + nudge** — compare a cheap **`/api/migrate/count` total** on local vs cloud (counts only, no data). If the cloud has more records, fire a `cloud-data-available` event → a **one-time popup** (`SyncNudgeModal`) offers **"Sync now"** (the gated Cloud → Local merge) or "Later". It never auto-pulls — it just surfaces that this device may be behind.
*(Implemented as `reconcileBizIdOnLogin` in `utils/loginSync.js` + `SyncNudgeModal` mounted in `AppLayout`.)*

**Full data sync is explicit / gated** — it happens only when the user runs it (**Settings → "Cloud → Local Sync"** or **"Local → Cloud Sync"**) or during a **migration**. Both buttons are **disabled offline** (they need the cloud) with a "connect to sync" hint.

**Merge rule = non-destructive Last-Write-Wins.** The sync buttons call `/api/migrate/import?merge=true`:
- row only on the source → **added**; row only on the destination → **kept**;
- row on both → the one with the newer `updated_at` wins; **nothing is blindly overwritten**.
This is row-level LWW (not field-level — the newer whole row wins; full field-merge/CRDT is out of scope for a single-owner business). Migration keeps its **mirror/overwrite** and **remap** modes for the deliberate "make an exact copy" / "merge into an existing account" cases.

This keeps subscription-gated cloud data from flowing to a local copy automatically, while letting the user pull/push it deliberately and safely. The fresh-device login also shows a popup pointing to **"Cloud → Local Sync."**

### Known gap (being cleared): "username already exists on cloud" + fresh-device login

When the cloud already has your username and you try to register on the app, cloud `/signup` returns **400** and the app says *"log in instead."* But on a **fresh device** there's no local user yet, so a local-first login would fail too — leaving you unable to register *or* log in. Two pieces close this:

1. **Pre-check** — `POST /api/identity/check {username}` → `{ "exists": true|false }` only (no PII; minimal to avoid account enumeration). The signup form calls it and branches early: *"This account exists → Log in"* vs *"Create new."*
2. **Login cloud-fallback + local mirror** — when local login finds no local user, the app tries the **cloud** login; on success it creates the **local mirror** of the account (same username + the cloud's BizID, identity only), then logs in locally. Subsequent logins are local/offline.

Data stays gated: the fresh-device mirror is **identity only** — the actual business data is pulled later, deliberately, via **"Cloud → Local Sync."** Linking always requires the password (cloud login); never auto-link by username alone. *(Status: ✅ implemented — `POST /api/identity/check` (`routes/auth.py`); login cloud-fallback + local-mirror creation (`AuthContext.login`); and the **signup form "Log in instead" branch** — `Register.jsx` pre-checks the username against the cloud on blur and steers existing accounts to login.)*

### Free identity vs. paid hosting (so this fits the business model)
A **cloud account/identity + BizID is free** (it's the network spine, and lets you upsell). **Cloud hosting / live multi-device sync / AI is the paid tier.** Auto-creating the cloud identity at registration does **not** give away the paid product.

## 6. Why not the simpler options

- **Pure local-first (A)** keeps the collision/duplicate problem alive and makes "same owner on both" a perennial reconciliation headache.
- **Username-only matching** (today) works *only because* you reused the username; it's a coincidence, not a guarantee, and silent username/email merge is the documented takeover risk.
- **Convert all PKs to UUID now** is correct in spirit but a heavy migration; the **add-a-`uid`-column** approach (Rule 2) gets the same safety incrementally.

## 7. Implementation roadmap (incremental, low-risk)

1. ✅ **Resolver guard (done):** BizID match now also requires the **username** to agree, in both `_resolve_owner_id` (migrate) and `_resolve_business_id_by_username` (sync) → a chance BizID collision can no longer mis-route.
2. ✅ **Cloud-authoritative BizID + network-gated registration (done):** on the downloaded app, signup registers on the **cloud first** (mints the BizID), then **mirrors locally with that BizID** (`SignupRequest.public_id`); registration requires a one-time connection. Login/signup now return `public_id`. Collision risk removed by construction.
3. **`uid` on synced entities:** add a UUID column (nullable, backfilled), switch sync/migrate match keys from `id` → `uid`. Keep integer `id` for local speed.
4. ✅ **Identity-check + link-on-login UX (done):** `POST /api/identity/check`; the signup form pre-checks the username against the cloud and shows "Log in instead" for existing accounts; login cloud-fallback creates the local mirror (register-on-web → download → direct login covered).
5. **(Optional) fully-offline registration:** only if you decide to support no-internet shops — `provisional` BizID + claim-on-connect (cloud reassigns on collision).

Steps 1–2 remove the *risk*; 3 removes the *entity collision*; 4 removes the *duplicate account*; 5 is an optional add-on for offline-only shops.

---

## Sources
- [The Two ID Problem — Dan Lew](https://blog.danlew.net/2017/03/09/the-two-id-problem/)
- [Identity Crisis: How Modern Applications Generate Unique IDs — Eric Elliott](https://medium.com/javascript-scene/identity-crisis-how-modern-applications-generate-unique-ids-39562736f557)
- [Universally Unique Identifier — Wikipedia](https://en.wikipedia.org/wiki/Universally_unique_identifier)
- [Offline-First, More Reliable Mobile Apps — Couchbase](https://www.couchbase.com/blog/offline-first-more-reliable-mobile-apps/)
- [Build an offline-first app — Android Developers](https://developer.android.com/topic/architecture/data-layer/offline-first)
- [Offline Synchronization — Mendix](https://docs.mendix.com/refguide/mobile/building-efficient-mobile-apps/offlinefirst-data/synchronization/)
- [Lessons in safe identity linking — WorkOS](https://workos.com/blog/lessons-in-safe-identity-linking)
- [Secure account linking — Ory](https://www.ory.com/blog/secure-account-linking-iam-sso-oidc-saml)
- [Link User Accounts — Auth0](https://auth0.com/docs/manage-users/user-accounts/user-account-linking/link-user-accounts)
- [Securely Merging OAuth Identities — Descope](https://www.descope.com/blog/post/descope-flows-securely-merging-oauth-identities)
