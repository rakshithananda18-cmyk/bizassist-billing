# Manual test queries — verify the changes in the live chat

Type these into the chat UI. The little badge/source on each answer tells you
which path it took. Replace `<CUSTOMER>` with a real customer name from your data.

Legend of sources you may see: **db / intent** = instant, 0 tokens · **ai** =
LLM answered · **conversational** = small talk · **cached** = served from cache.

---

## 1. Routing tiers (does each question go to the right place?)

| Query | Expect |
|---|---|
| `hi` | conversational, 1-2 lines, no business data |
| `thanks` | conversational |
| `how many invoices do I have` | **db** — instant number |
| `total revenue` | **db** — a rupee figure with numbers |
| `show overdue invoices` | **db / intent** — overdue list |
| `who hasn't paid me` | **intent** — same as overdue (semantic variant) |
| `who owes me the most` | **db/intent** — top debtors |
| `low stock items` | **db** — low stock list |
| `what's running low on stock` | **intent** — same as low stock |
| `which products are expiring soon` | **db** — expiring list |
| `business summary` | **db** — snapshot |
| `draft a payment reminder for my overdue customers` | **ai** — a written message (NOT a data table) |
| `analyse my business and give me a recovery plan` | **ai** — multi-section plan (this is the heavy path) |

> Tip: the "draft/write" ones must go to **ai**, not db. The "analyse/plan/why"
> ones must go to the heavy **ai** path.

## 2. Fuzzy customer-name matching (H8 — the "nilgiris fresh" fix)

Use a REAL customer name from your data as `<CUSTOMER>`, then deliberately mistype it.

| Query | Expect |
|---|---|
| `do you know <CUSTOMER>?` | a profile/summary for that customer |
| `tell me about <CUSTOMER with a typo>` (e.g. drop a letter) | still finds the **same** customer |
| `<CUSTOMER in lower case>` info | still finds them (casing-independent) |
| `<two words of the name in reversed order>` | still finds them (word order) |
| `tell me about Zxqwerty Fictional` (a name that does NOT exist) | should NOT match a real customer — generic/AI answer |

## 3. Caching (same meaning → instant repeat; new day → fresh)

1. Ask `show overdue invoices` → note the answer.
2. Ask `who owes me money` → should be **cached** (same topic, different words), instant.
3. Ask `total revenue` → a different topic, should NOT be the overdue answer.
4. (Optional) Upload a file, then ask `total revenue` again → should recompute (cache busted), not cached.

## 4. Dates & status (look at the data pages, not chat)

- Open **Invoices** → the status filter chips (Paid / Pending / Overdue) should
  count correctly, and dates should display sensibly.
- Open **Payments** → overdue/pending totals should be right.
- If you ran the backfill migration, older rows now show clean `YYYY-MM-DD` dates too.
- Upload a CSV with messy dates (e.g. `15/01/2026`) and lowercase `overdue` status,
  then check Invoices — it should appear as a proper date and counted under Overdue.

## 5. Rate limit (the error path)

- Send messages rapidly, many in a row (past your per-minute limit).
- Expect: the rate-limit banner/notice appears (the UI reacts to the 429), and the
  chat shows a "❌ …" rate-limit message rather than hanging.

## 6. Token accounting (admin only)

- After asking a few AI questions, open **Admin → Usage**.
- The token numbers should be non-zero and should now also reflect the smaller
  "polish" and conversational calls (previously some showed as 0).

## 7. (Optional) Shadow-mode router data

Only if you want to start collecting semantic-router data:

1. Stop the server, set the env var `INTENT_ROUTER=shadow`, restart.
2. Use the app normally for a while (ask varied questions).
3. In the server console/logs, search for `[ROUTER][shadow]`.
   - Lines marked `AGREE` = the semantic router would route the same as today.
   - Lines marked `DISAGREE` = where it differs — review these to judge if the new
     router is better or worse before any cutover. Nothing about routing changes
     while in shadow mode; it only watches and logs.
