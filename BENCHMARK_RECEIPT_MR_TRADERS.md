# Benchmark Receipt — M.R. Traders (real kirana thermal bill)

> A real intra-state kirana (grocery) thermal receipt supplied by a pilot retailer, used as the
> **format + pricing + GST benchmark** for BizAssist POS, the thermal print template, and the R4
> pricing refactor. Every claim below is reconciled against the printed figures.

## 1. Transcription

**Header**
- Store: **M.R. TRADERS**, Charitha Complex, Near Mandal Office, Santhipuram, Santhipuram 517423
- **GSTIN:** 37APTPV0515M1Z6  (state code 37 = Andhra Pradesh → intra-state → **CGST + SGST**)
- Phone: 7619570319 · **FSSAI:** 10122010000279
- Doc title: **TAX INVOICE**
- **Bill No:** 6470 · **Date:** 16/06/2026 · **Time:** 07:21:37 PM
- **Cashier:** POS · **Counter:** CTR2  (multi-counter shop)

**Line items** — columns `Description | MRP | Rate | Qty | Amt`, where **Amt = Rate × Qty** (Rate = actual selling price; MRP is the reference for savings).

| # | Description | MRP | Rate | Qty | Amt |
|---|---|---:|---:|---:|---:|
| 1 | AASHIR ATTA 1KG | 74.00 | 67.00 | 1 | 67.00 |
| 2 | BRU INS RS10 | 10.00 | 9.50 | 12 | 114.00 |
| 3 | C NAPTHALENE BAL | 38.00 | 30.00 | 2 | 60.00 |
| 4 | COLGATE 200G | 135.00 | 133.00 | 1 | 133.00 |
| 5 | DETTOL 60ML | 41.49 | 40.00 | 1 | 40.00 |
| 6 | GOLD WINNER 1L | 205.00 | 175.00 | 1 | 175.00 |
| 7 | GTS BULLET RICE B | 120.00 | 90.00 | 1 | 90.00 |
| 8 | TJ LAMP OIL 900ML | 230.00 | 180.00 | 1 | 180.00 |
| 9 | MEOW BALL PEN | 30.00 | 25.00 | 1 | 25.00 |
| 10 | METHI 100G | 18.00 | 15.00 | 2 | 30.00 |
| 11 | MUSTARD 250G | 75.00 | 50.00 | 1 | 50.00 |
| 12 | ODONIL 24G | 25.00 | 25.00 | 1 | 25.00 |
| 13 | SF MARIE LIGHT | 18.00 | 17.00 | 2 | 34.00 |
| 14 | SOMPU 100G | 55.00 | 40.00 | 1 | 40.00 |
| 15 | TULIPS BUDS JAR 55 | 62.00 | 60.00 | 1 | 60.00 |

**Totals block**
- `E & O.E., #Incl Gst`  → **prices are GST-inclusive**
- **Total: 1123.00**
- **(-) Cash Dis: 3.00**
- **Qty: 29 · Items: 15**
- **Total: 1120.00**
- **Payment Details — Wallet: 1120.00**

**Tax breakup** — columns `Tax% | Amt(taxable) | Gst | SGst | CGst`

| Tax % | Taxable Amt | GST | SGST | CGST |
|---:|---:|---:|---:|---:|
| 0.00 | 295.17 | 0.00 | 0.00 | 0.00 |
| 5.00 | 569.03 | 28.45 | 14.23 | 14.23 |
| 12.00 | 160.26 | 19.23 | 9.62 | 9.62 |
| 18.00 | 42.26 | 7.60 | 3.80 | 3.80 |

**Footer:** `You have Saved 200.49` · `GOODS ONCE SOLD CANNOT BE TAKEN BACK.` · `Thank You - Visit Again`

## 2. Reconciliation (the math checks out)

- **Amt column** Σ = 67+114+60+133+40+175+90+180+25+30+50+25+34+40+60 = **1123.00** ✓ (= printed Total before cash discount)
- **Payable** = 1123.00 − 3.00 cash discount = **1120.00** ✓ (= Wallet paid)
- **Qty** Σ = 1+12+2+1+1+1+1+1+1+2+1+1+2+1+1 = **29** ✓ · **Items** = 15 distinct lines ✓
- **"You have Saved 200.49"** = line savings Σ(MRP−Rate)×Qty (**197.49**) + cash discount (**3.00**) = **200.49** ✓
- **GST slabs** are internally consistent (GST = taxable × rate; CGST = SGST = GST/2): 5% → 569.03×5% = 28.45 ✓; 12% → 19.23 ✓; 18% → 7.60 ✓
- **Known ~₹1 drift:** taxable Σ (1066.72) + GST Σ (55.28) = **1122.00** vs printed **1123.00** — a ~₹0.99 rounding gap in the retailer's own POS (per-slab inclusive→taxable back-out rounding). **BizAssist's deterministic inclusive split should NOT drift like this** — a clean-books selling point.

## 3. What this validates in BizAssist (keep)

- **MRP + Rate + "You have Saved"** is the real, expected format — keep the savings display; it's not just debt.
- **GST-inclusive pricing** with per-slab taxable/CGST/SGST back-out, **multiple slabs in one bill** (0/5/12/18), **intra-state CGST = SGST**. Matches the deterministic `tax_inclusive` engine and the GSTR rate-bucketing.
- **Distinct Qty vs Items** counts; **Bill No / Date / Time / Cashier / Counter** header.

## 4. Gaps BizAssist must close (the spec)

1. **Two distinct discounts** — the model the receipt proves:
   - **Line trade discount** = `MRP − Rate`, **pre-tax** (already baked into Rate, the taxable base).
   - **Bill "Cash Discount"** = flat **post-tax** deduction (₹3 here) that does **NOT** reduce taxable value and also serves as **round-off** to a clean payable.
   - ⚠️ Today `create_sale_invoice.bill_discount` is **pre-tax, apportioned across lines (tax on net)** — that's a *different* concept. We need BOTH: keep the pre-tax apportioned discount AND add a post-tax cash-discount/round-off that leaves GST untouched.
2. **`wallet` payment mode** (alongside cash / UPI / card / credit).
3. **Counter / terminal id** (`CTR2`) — multi-counter shops.
4. **Thermal template fields:** FSSAI no., per-slab tax table, `You have Saved`, `Qty` vs `Items`, footer lines (`GOODS ONCE SOLD…`, `Thank You - Visit Again`), `#Incl Gst` flag.
5. **Round-off line** — payable rounded to a clean figure (the cash discount doubles as round-off).

## 5. Canonical pricing model (target for R4)

A sale line should carry, explicitly and separately:
```
mrp            # reference only, for the savings line  (display)
unit_price     # = "Rate"; the taxable base per unit   (money)
line_discount  # optional extra pre-tax discount on top of MRP→Rate
qty
# line taxable = (unit_price - line_discount) * qty     (GST computed on this)
```
Bill level:
```
bill_discount_pretax    # apportioned across lines, reduces taxable (existing behaviour)
cash_discount_posttax   # flat, AFTER tax, does NOT touch GST; doubles as round-off
```
This removes the "MRP-as-live-price" overloading (the qty-drift bug class in §10.2 #3) while preserving the exact receipt the retailer expects.
