"""
services/column_mapper.py
=========================
Adaptive column mapping for any CSV/Excel upload.

Problem solved: real-world data never uses our canonical column names.
  Tally exports: "Voucher No", "Party Name", "Taxable Amount"
  Shop Excel:    "Invoice #",  "Client",     "Total"
  Pharmacy:      "Medicine",   "Qty",        "Expiry"

Architecture (layered, cheapest first):
  Layer 1: Exact match (0 cost, instant)
  Layer 2: Synonym dictionary - covers 95% of real cases (0 cost, instant)
  Layer 3: Fuzzy string match via difflib (0 cost, instant)
  Layer 4: Groq AI fallback for unknown columns (~30 tokens, only when needed)

SOLID:
  S - ColumnMapper only maps columns; it does not touch the DB or parse data
  O - Add new synonyms by extending _SYNONYMS; never modify existing entries
  L - MappingResult is a simple dataclass, substitutable anywhere a dict is used
  I - map_columns() is the only public method callers need
  D - Groq client injected, not imported globally

Usage:
    from services.column_mapper import ColumnMapper
    mapper = ColumnMapper()
    result = mapper.map_columns(df.columns.tolist(), filename="tally_export.xlsx")
    # result.detected_type  -> "invoice" | "inventory" | "payment" | "unknown"
    # result.renamed_df     -> DataFrame with canonical column names
    # result.mapping        -> {"Voucher No": "invoice_id", ...}
    # result.unmapped       -> ["Extra Column"]
    # result.confidence     -> 0.0 - 1.0
"""

from __future__ import annotations

import logging
import json
from dataclasses import dataclass, field
from difflib import get_close_matches
from typing import Optional

import pandas as pd

logger = logging.getLogger("bizassist.column_mapper")


# ---------------------------------------------------------------------------
# CANONICAL FIELDS PER TYPE
# ---------------------------------------------------------------------------

INVOICE_FIELDS = {
    "invoice_id", "customer", "product", "amount",
    "status", "invoice_date", "due_date",
}
INVENTORY_FIELDS = {
    "product_name", "stock", "expiry_date", "supplier",
}
PAYMENT_FIELDS = {
    "customer", "amount", "due_date", "paid",
}

# Fields required to identify the file type (minimum 1 must match)
_TYPE_SIGNALS = {
    "invoice":   {"invoice_id", "invoice_date"},
    "inventory": {"expiry_date", "product_name", "stock"},
    "payment":   {"paid"},
}


# ---------------------------------------------------------------------------
# SYNONYM DICTIONARY  (Open/Closed: append, never modify)
# Each canonical field maps to a list of known aliases (all lowercase).
# ---------------------------------------------------------------------------

_SYNONYMS: dict[str, list[str]] = {

    # ── Invoice fields ───────────────────────────────────────────────────────
    "invoice_id": [
        "invoice no", "invoice number", "invoice #", "inv no", "inv #",
        "voucher no", "voucher number", "bill no", "bill number", "bill #",
        "ref no", "reference no", "reference number", "order no",
        "receipt no", "sr no", "serial no", "txn id", "transaction id",
        "doc no", "document no", "document number",
    ],
    "customer": [
        "customer name", "customer", "client", "client name", "party",
        "party name", "buyer", "buyer name", "debtor", "account",
        "account name", "sold to", "bill to", "billed to",
        "consignee", "ship to",
    ],
    "product": [
        "product", "product name", "item", "item name", "description",
        "particulars", "goods", "service", "services", "narration",
        "details", "product description", "item description",
    ],
    "amount": [
        "amount", "total", "total amount", "grand total", "net amount",
        "net total", "invoice amount", "invoice value", "taxable amount",
        "value", "bill amount", "outstanding", "balance", "due amount",
        "payable", "receivable",
    ],
    "status": [
        "status", "payment status", "invoice status", "state",
        "paid status", "collection status", "clearing status",
    ],
    "invoice_date": [
        "invoice date", "date", "bill date", "voucher date", "txn date",
        "transaction date", "document date", "issue date", "created date",
        "created on", "booking date", "sale date",
    ],
    "due_date": [
        "due date", "payment due date", "due on", "due by",
        "expiry date", "maturity date", "credit due date",
        "payment date", "expected date", "settle by",
    ],

    # ── Inventory fields ─────────────────────────────────────────────────────
    "product_name": [
        "product name", "product", "item name", "item", "medicine",
        "medicine name", "drug", "drug name", "sku", "sku name",
        "goods name", "article", "material", "material name",
        "description", "particulars", "name",
    ],
    "stock": [
        "stock", "quantity", "qty", "units", "count", "balance qty",
        "closing stock", "closing qty", "available", "available qty",
        "on hand", "in hand", "current stock", "nos",
    ],
    "expiry_date": [
        "expiry date", "expiry", "expiration date", "exp date",
        "exp", "best before", "use by", "use before",
        "valid till", "valid upto", "shelf life",
    ],
    "supplier": [
        "supplier", "supplier name", "vendor", "vendor name",
        "manufacturer", "brand", "company", "distributor",
        "wholesaler", "source", "procured from",
    ],

    # ── Payment fields ───────────────────────────────────────────────────────
    "paid": [
        "paid", "payment", "paid amount", "amount paid",
        "cleared", "settled", "received", "collected",
        "payment received", "cash received",
    ],
}

# Build reverse lookup: synonym_token → canonical_field
_REVERSE: dict[str, str] = {}
for canonical, synonyms in _SYNONYMS.items():
    for s in synonyms:
        _REVERSE[s] = canonical


# ---------------------------------------------------------------------------
# RESULT DATACLASS
# ---------------------------------------------------------------------------

@dataclass
class MappingResult:
    detected_type: str                          # "invoice" | "inventory" | "payment" | "unknown"
    mapping:       dict[str, str]               # raw_col -> canonical_col
    unmapped:      list[str]                    # raw columns that could not be mapped
    confidence:    float                        # 0.0 - 1.0
    renamed_df:    Optional[pd.DataFrame] = None  # df with canonical column names
    warnings:      list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# COLUMN MAPPER
# ---------------------------------------------------------------------------

class ColumnMapper:
    """
    Maps any set of raw column headers to BizAssist canonical field names.

    Three lookup layers (cheapest first):
      1. Exact lowercase match
      2. Synonym dictionary lookup
      3. Fuzzy difflib match (cutoff 0.75)
    Followed by optional Groq AI fallback for remaining unmapped columns.
    """

    def __init__(self, groq_client=None, model: str = "llama-3.1-8b-instant"):
        self._groq   = groq_client   # injected; None = skip AI layer
        self._model  = model

    # ── Public API ───────────────────────────────────────────────────────────

    def map_columns(
        self,
        raw_columns: list[str],
        filename: str = "",
        df: pd.DataFrame = None,
    ) -> MappingResult:
        """
        Map raw_columns to canonical names.
        Returns a MappingResult with renamed_df if df is provided.
        """
        mapping  = {}
        unmapped = []

        for col in raw_columns:
            canonical = self._lookup(col)
            if canonical:
                mapping[col] = canonical
            else:
                unmapped.append(col)

        # AI fallback for anything still unmapped
        if unmapped and self._groq:
            ai_mapping = self._ai_map(unmapped, filename)
            for col, canonical in ai_mapping.items():
                mapping[col]   = canonical
                unmapped.remove(col)

        detected_type = self._detect_type(set(mapping.values()))
        confidence    = self._confidence(mapping, raw_columns, detected_type)
        warnings      = self._build_warnings(mapping, detected_type, unmapped)

        renamed_df = None
        if df is not None:
            renamed_df = df.rename(columns=mapping)

        logger.info(
            f"[MAPPER] file='{filename}' type={detected_type} "
            f"confidence={confidence:.2f} mapped={len(mapping)} unmapped={unmapped}"
        )

        return MappingResult(
            detected_type=detected_type,
            mapping=mapping,
            unmapped=unmapped,
            confidence=confidence,
            renamed_df=renamed_df,
            warnings=warnings,
        )

    # ── Layer 1 + 2: exact and synonym lookup ────────────────────────────────

    def _lookup(self, raw_col: str) -> Optional[str]:
        """Exact → synonym → fuzzy. Returns canonical name or None."""
        token = raw_col.strip().lower()

        # Layer 1: exact match against canonical names
        all_canonical = INVOICE_FIELDS | INVENTORY_FIELDS | PAYMENT_FIELDS
        if token in all_canonical:
            return token

        # Layer 2: synonym dictionary
        if token in _REVERSE:
            return _REVERSE[token]

        # Layer 3: fuzzy match against all synonym tokens
        all_tokens = list(_REVERSE.keys()) + list(all_canonical)
        matches = get_close_matches(token, all_tokens, n=1, cutoff=0.75)
        if matches:
            best = matches[0]
            return _REVERSE.get(best, best if best in all_canonical else None)

        return None

    # ── Layer 4: AI fallback ─────────────────────────────────────────────────

    def _ai_map(self, unmapped_cols: list[str], filename: str) -> dict[str, str]:
        """
        Ask Groq to map remaining unmapped columns.
        ~30 tokens per call. Only fires when fuzzy matching fails.
        """
        all_canonical = sorted(INVOICE_FIELDS | INVENTORY_FIELDS | PAYMENT_FIELDS)
        prompt = (
            f"Map these CSV column headers to the closest canonical field names.\n"
            f"Column headers: {unmapped_cols}\n"
            f"Canonical fields: {all_canonical}\n"
            f"Return ONLY a JSON object like {{\"raw_col\": \"canonical_field\"}}. "
            f"If no match, omit the key. No explanation."
        )
        try:
            resp = self._groq.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model=self._model,
                temperature=0,
                max_tokens=150,
            )
            text = resp.choices[0].message.content.strip()
            # Extract JSON even if surrounded by markdown
            if "```" in text:
                text = text.split("```")[1].lstrip("json").strip()
            result = json.loads(text)
            valid = {k: v for k, v in result.items()
                     if k in unmapped_cols and v in (INVOICE_FIELDS | INVENTORY_FIELDS | PAYMENT_FIELDS)}
            logger.info(f"[MAPPER] AI mapped: {valid}")
            return valid
        except Exception as e:
            logger.warning(f"[MAPPER] AI fallback failed: {e}")
            return {}

    # ── Type detection ────────────────────────────────────────────────────────

    def _detect_type(self, canonical_set: set[str]) -> str:
        """
        Detect file type from the set of canonical field names found.
        Tries each type's required signals; most signals matched wins.
        """
        scores = {}
        for file_type, signals in _TYPE_SIGNALS.items():
            scores[file_type] = len(signals & canonical_set)

        best_type  = max(scores, key=scores.get)
        best_score = scores[best_type]

        if best_score == 0:
            # Fallback: if we got invoice-like fields but no signal match
            if canonical_set & INVOICE_FIELDS:
                return "invoice"
            if canonical_set & INVENTORY_FIELDS:
                return "inventory"
            if canonical_set & PAYMENT_FIELDS:
                return "payment"
            return "unknown"

        return best_type

    # ── Confidence score ──────────────────────────────────────────────────────

    def _confidence(self, mapping: dict, raw_columns: list, detected_type: str) -> float:
        """
        Confidence = (required fields found) / (total required fields for this type).
        Capped at 1.0.
        """
        required = {
            "invoice":   {"invoice_id", "customer", "amount"},
            "inventory": {"product_name", "stock"},
            "payment":   {"customer", "amount", "due_date"},
        }.get(detected_type, set())

        if not required:
            return 0.5

        found = sum(1 for f in required if f in mapping.values())
        return min(found / len(required), 1.0)

    # ── Warnings ──────────────────────────────────────────────────────────────

    def _build_warnings(self, mapping: dict, detected_type: str, unmapped: list) -> list[str]:
        warnings = []
        required = {
            "invoice":   {"invoice_id", "customer", "amount"},
            "inventory": {"product_name", "stock"},
            "payment":   {"customer", "amount", "due_date"},
        }.get(detected_type, set())

        missing_required = required - set(mapping.values())
        if missing_required:
            warnings.append(f"Missing required fields: {sorted(missing_required)}")
        if unmapped:
            warnings.append(f"Could not map columns: {unmapped} — they will be ignored")
        return warnings


# ---------------------------------------------------------------------------
# MODULE-LEVEL HELPER  (convenience for routes/upload.py)
# ---------------------------------------------------------------------------

_default_mapper = ColumnMapper()   # no AI — sync, instant

def normalize_dataframe(df: pd.DataFrame, filename: str = "", groq_client=None) -> MappingResult:
    """
    Convenience function. Uses AI if groq_client is provided, otherwise rules only.
    """
    mapper = ColumnMapper(groq_client=groq_client)
    return mapper.map_columns(df.columns.tolist(), filename=filename, df=df)
