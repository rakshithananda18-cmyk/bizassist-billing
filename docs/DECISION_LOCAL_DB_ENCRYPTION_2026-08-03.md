# Decision — local database encryption (C-1) and key custody

**Date:** 2026-08-03
**Status:** design record, **awaiting owner sign-off** — §8 is the part that needs you
**Closes:** the design half of C-1 in
[`PLATFORM_STATE_AND_PENDING_WORK_2026-08-03.md`](PLATFORM_STATE_AND_PENDING_WORK_2026-08-03.md) §4.3
**Prerequisite of:** any SQLCipher packaging work

> [`DECISION_LOCAL_POSTGRES_2026-08-03.md`](DECISION_LOCAL_POSTGRES_2026-08-03.md) §6.1
> says of this item: *"do it now or accept never."* That is the reason this
> document exists today rather than after the first paying install. It is also
> why it stops at a design: the audit's own C-1 entry says *"key custody has to
> be designed before it is worth starting."*

---

## 0. What this document decides, and what it does not

**Decides:** where the key lives, what unlocks it, what happens when that fails,
and what breaks on the way. **Does not decide:** the SQLCipher packaging work
itself — that is downstream of §8 being answered.

Everything in §2 was read from the code in this repository at `8c4fa4b`. Where a
claim is inferred rather than read, it says so.

---

## 1. The threat model, stated before the mechanism

`ARCHITECTURE.md` §2.8 justifies SQLCipher with one sentence: *"a stolen laptop ≠
a plaintext price book."* That is a good slogan and a bad specification, because
"stolen laptop" is at least five different attacks and encryption stops some and
not others. Naming them is what makes the rest of this document decidable.

| # | Attack | Plaintext today | SQLCipher + machine-bound key | SQLCipher + passphrase |
|---|---|---|---|---|
| T1 | Laptop stolen, disk pulled or booted from USB | ❌ full read | ✅ stopped | ✅ stopped |
| T2 | Laptop stolen powered on, thief has the Windows password | ❌ full read | ❌ **not stopped** | ✅ stopped |
| T3 | Malware running as the logged-in Windows user | ❌ full read | ❌ **not stopped** | ⚠️ only while locked |
| T4 | Staff member copies `bizassist.db` to a USB stick | ❌ full read | ✅ stopped | ✅ stopped |
| T5 | Backup / support bundle emailed or uploaded | ❌ full read | ✅ stopped | ✅ stopped |

**T4 and T5 are the common ones in retail**, and they are the ones a
machine-bound key actually stops. T2 and T3 need a secret that is not on the
machine, which costs a prompt — see §5.

**This table is the honest version of the marketing claim.** `PLATFORM_STATE`
§5.2 W-6 already warns not to claim encrypted-at-rest until C-1 ships; §9 below
narrows that further, because "encrypted at rest" will be read by a buyer as
covering T2 and T3, and the recommended design does not.

---

## 2. Six constraints the code imposes — measured, not assumed

Any custody scheme has to survive all six. Most naive schemes fail on 2.1.

### 2.1 The database must open **before anyone logs in**

The desktop shell spawns the backend as a child process
(`desktop/src/backend.js:74`) and the backend serves `POST /login`. Credentials
live in the `users` table **inside the database being protected**. So:

> The key cannot be derived from a password that is verified against the
> database, because the database must already be open to verify it.

A passphrase can still be used — but only by deriving the SQLCipher key from it
directly (KDF) and treating "the file decrypts" as the proof, never by checking
it against a row first.

### 2.2 Twelve scheduled jobs run with no human present

`services/scheduler.py:79-227` starts a `BackgroundScheduler` from the FastAPI
lifespan with 12 jobs, including hybrid sync and the cloud parity sweep. These
run after a reboot, at 08:00, on a till nobody has touched yet.

> A design that requires a passphrase at every start means **no background sync
> until someone types it**. That is a real product change, not a detail.

### 2.3 There is already a plaintext secret beside the database

`server_entry.py:44-50` generates and persists `<data_dir>/jwt-secret` in
plaintext, next to `<data_dir>/bizassist.db`.

> A SQLCipher key stored the same way protects against **nothing in §1**. The
> file and its key would travel together in T1, T4 and T5 alike.

This is not a criticism of `jwt-secret` — it is the precedent that makes "just
write the key to a file" feel reasonable, and it is exactly the option that must
be rejected. **`jwt-secret` has the same problem and should get the same
treatment** (§7).

### 2.4 Every audit and repair script uses raw `sqlite3.connect()`

```
backend/scan_db.py                          backend/scripts/audit_money_integrity.py
backend/dump_payments.py                    backend/scripts/audit_payment_attachment.py
backend/reconstruct_line_items.py           backend/scripts/check_outbox_rows.py
backend/scripts/clear_staff_bizids.py       backend/scripts/check_local_sync_backlog.py
```

Python's bundled `sqlite3` **cannot open a SQLCipher database**. On the day
encryption ships, every one of these fails — including the scripts the six open
data items in
[`DATA_REPAIR_STATE_2026-08-03.md`](DATA_REPAIR_STATE_2026-08-03.md) depend on.

**This is not in the C-1 entry and it is the largest piece of unbudgeted work in
the item.** It is also an argument for sequencing: finish the repair backlog
*before* encrypting, or accept re-plumbing eight scripts mid-repair.

### 2.5 Updates are silent

`desktop/package.json` ships `electron-updater` with silent auto-update. So the
plaintext → encrypted conversion runs **unattended, on a machine nobody is
watching, possibly mid-day**.

> It must be atomic, resumable, and must leave the shop able to bill if it fails.
> The same reasoning `DECISION_LOCAL_POSTGRES` §4.2 applies to `pg_upgrade`
> applies here, and it is the one thing in this document that can lose data.

### 2.6 The single-file property is load-bearing

`database/db.py:121-129` keeps WAL **off** on purpose, because backup and
transfer paths copy one file. SQLCipher preserves this — it is still one file —
so this constraint is satisfied by the mechanism, and is recorded so a later
change does not break both properties at once.

---

## 3. The options

### Option 1 — Key file beside the database ❌ **Rejected**

What `jwt-secret` does today. Stops nothing in §1: the key travels with the file.
Rejected not because it is weak but because it is **indistinguishable from
encryption that works**, which makes it worse than plaintext — it would let the
product claim T1/T4/T5 protection it does not have.

### Option 2 — Windows DPAPI, machine + user bound ✅ **Recommended baseline**

`CryptProtectData` with `CRYPTPROTECT_LOCAL_MACHINE` off, i.e. bound to the
Windows *user account*. The wrapped key sits in the data dir; unwrapping requires
that Windows user on that machine.

* Satisfies 2.1 and 2.2 — unattended start, no prompt.
* Stops T1, T4, T5. Does **not** stop T2 or T3.
* Native on Windows, which is the shipping platform.

**Its failure mode is the problem, and it is severe:** a Windows profile reset,
a machine reinstall, or restoring the data dir onto a different PC leaves the
database **permanently unreadable**. That is worse than plaintext for a shop.
Which is why Option 2 is only safe with §4.

### Option 3 — Owner passphrase at every app start ⚠️ Strongest, real cost

Key derived from a passphrase via a memory-hard KDF. Stops T2 and, while locked,
T3.

Breaks 2.2 outright: no sync, no alerts, no parity sweep until someone types it
after every reboot. For a counter that is switched on at 07:00 and used at 09:00,
that is two hours of a dead till and a support call.

**Not recommended as the default.** Worth offering as an opt-in for owners who
want it — see §4 wrapping 3.

### Option 4 — Key fetched from the cloud at startup ❌ **Rejected**

Contradicts the product. `ARCHITECTURE.md`'s pitch is offline-first billing;
`hosting_mode: None` installs have no cloud at all. A till that cannot open its
own books without the internet is the failure this product exists to avoid.

---

## 4. Recommended design — one data key, three independent wrappings

Envelope encryption, which is the standard answer and here also the *minimum*
that does not risk a shop's books:

```
DEK   32 random bytes            → the SQLCipher key. Never stored bare.
                                   Never leaves the machine.
  ├── wrapped by DPAPI (current Windows user)   → normal unattended start
  ├── wrapped by a RECOVERY CODE               → survives Windows reinstall
  └── wrapped by an owner passphrase           → OPTIONAL, opt-in, closes T2/T3
```

Any one wrapping opens the database. Losing one is not losing the data.

**Wrapping 1 (DPAPI)** is the everyday path: the backend starts, unwraps, opens
the database, the scheduler runs. No prompt, no change to how the app feels.

**Wrapping 2 (recovery code) is not optional and is the whole reason this design
has three.** A 24-character code generated at first run, shown once, with the
setup flow refusing to continue until the owner confirms they have stored it —
printed, photographed, in their existing safe. Without it, §2.5's silent update
plus a later Windows reinstall is an unrecoverable total loss of a shop's books,
and the product caused it.

**Wrapping 3 (passphrase)** is Option 3 offered to owners who want T2/T3 and
accept 2.2's cost. Off by default. Enabling it should state plainly that
background sync pauses until unlock.

### Rotation and re-wrapping

Adding, removing or changing a wrapping re-wraps the DEK only — it never
re-encrypts the database. So "the owner changed their passphrase" is a
millisecond operation on a 500 MB file, and a compromised wrapping can be
revoked without touching the data.

---

## 5. What this explicitly does not do

Stated because the gap between §1's table and the claim a salesperson will make
is where this goes wrong:

* **A thief with the Windows password reads everything** (T2), unless wrapping 3
  is enabled. On a shop till the Windows account often has no password at all.
* **Malware running as the user reads everything** (T3). The backend holds the
  DEK in process memory for as long as it runs, which is all day.
* **It is not a compliance control.** No DPDP/PCI claim rests on this.
* **The cloud copy is unaffected.** Supabase has its own storage encryption and
  RLS; this is about the file on the counter.

---

## 6. Blast radius — what breaks the day this ships

| # | Breaks | Fix | Size |
|---|---|---|---|
| 1 | **8 audit/repair scripts** using raw `sqlite3.connect()` (§2.4) | Route them through a shared opener that knows the key, or give each a `--key` path | **M — the biggest item, currently unbudgeted** |
| 2 | The plaintext → encrypted conversion, run silently (§2.5) | Atomic convert-to-temp then swap, original retained until verified, automatic fallback to plaintext on any failure | **M, and the only step that can lose data** |
| 3 | Support asking for a copy of the database | New procedure; the file is now useless without a wrapping | S |
| 4 | `pysqlcipher3` / SQLCipher binaries in the PyInstaller bundle | Packaging + a signed Windows build | **M** |
| 5 | Tests — 2,053 of them open SQLite directly | Keep test databases plaintext; encryption is opt-in by config | S |
| 6 | `jwt-secret` remains plaintext beside the encrypted DB | Wrap it with the same DPAPI helper (§7) | S |

---

## 7. Do this part now regardless of the decision — it is one file

Independent of whether SQLCipher ships, and cheap:

**Wrap `jwt-secret` with DPAPI.** `server_entry.py:44-50` writes a
`token_urlsafe(48)` in cleartext into the data dir. On a hybrid install that
secret **signs tokens the cloud accepts** — so a copy of that one file is a copy
of the shop's cloud identity, which is a materially worse leak than the price
book. It is the same DPAPI helper wrapping 1 needs, written once and used twice,
and it is a strictly smaller change than the rest of C-1.

Related and already recorded: **C-13 items 2 and 3** remain open —
`_TOKEN_FILE` in `services/sync_worker.py` is still CWD-relative, so
`cloud_sync_tokens.json` (live cloud bearer JWTs) still has one location per
invocation directory. Same data dir, same class of problem, same fix.

---

## 8. Open questions — these are yours, and they change the design

1. **Is the recovery code acceptable as a setup step?** It adds friction to
   first-run and it is the only thing standing between a Windows reinstall and a
   shop losing its books. If it is unacceptable, encryption should not ship —
   Option 2 alone is a data-loss risk dressed as a security feature.
2. **Do you want wrapping 3 (passphrase) at all in v1**, given it pauses
   background sync until someone unlocks the till?
3. **Sequencing against the repair backlog.** Encrypting breaks the 8 repair
   scripts (§2.4) that the six open data items need. Finish the repairs first, or
   fund the script re-plumbing as part of C-1?
4. **What is support's recovery story** when an owner loses both the machine and
   the recovery code? Today the honest answer is "the cloud copy, if they are on
   hybrid; nothing, if they are not." Is that acceptable, and is it written down
   for whoever answers the phone?
5. **Does this change the answer to Option B (local Postgres)?**
   `DECISION_LOCAL_POSTGRES` §4.4 rejects Postgres partly *because* it forecloses
   SQLCipher. If C-1 is declined here, that argument weakens and Option B should
   be re-scored rather than left rejected on a lapsed premise.

---

## 9. What must not be claimed until this ships and is verified

Extending `PLATFORM_STATE` §5.2 W-6, which already says not to claim
encrypted-at-rest before C-1:

* Do not say **"encrypted at rest"** without qualification. A buyer reads that as
  T2 and T3, and the recommended design covers neither by default.
* The defensible sentence is narrower and still strong: *"your database file is
  encrypted — a copied or stolen file is unreadable without this machine."*
* Do not claim it at all while the conversion (§6 item 2) is unverified on a real
  Windows install. An encryption feature that corrupts one shop's books costs
  more than the feature was ever worth.
