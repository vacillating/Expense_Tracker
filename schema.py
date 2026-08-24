"""
schema.py — single source of truth for the Google Sheet's columns.

Everything that reads or writes the sheet goes through here. Adding a column
later means editing HEADERS + DEFAULTS and nothing else.
"""
from __future__ import annotations

import pandas as pd

HEADERS = [
    "id",              # UUID, generated on insert
    "date",            # YYYY-MM-DD, when the money was spent
    "type",            # Expense | Refund | Reimbursement
    "category",        # one of CATEGORIES
    "amount",          # original amount, in `currency`
    "currency",        # USD | CNY
    "amount_usd",      # converted at write time and then frozen — sum THIS, never `amount`
    "merchant",        # cleaned merchant name from the channel
    "notes",           # free text, Gary's own
    "payment_method",  # cmb_credit | chase_debit | cathay_debit_4826 | ... | cash
    "source",          # manual | telegram | csv_chase | csv_cathay | xlsx_wechat | ...
    "external_id",     # stable fingerprint of the source row; makes re-import idempotent
    "is_recurring",    # TRUE/FALSE — replaces the hand-maintained FIXED_TEMPLATES matching
    "created_at",      # when the row was written (NOT when the money was spent)
    "granularity",     # transaction | monthly_summary — see note below
]

# granularity = "monthly_summary" is for when we know the total but not the breakdown
# (a card statement that can't be itemized, a channel that wasn't exported that month,
# a period nobody got around to logging in detail). It's not just for this one CMB
# backfill — any future "known total, no receipts" situation should use the same
# mechanism instead of being a one-off special case. Analysis that needs itemized
# data (daily average, projection, category charts, top-N rankings) must filter these
# out; anything that only needs a period total (Total Booked, Spent to Date, future
# month-over-month trend) should keep them.
DEFAULTS = {
    "type": "Expense",
    "currency": "USD",
    "merchant": "",
    "notes": "",
    "payment_method": "",
    "source": "manual",
    "external_id": "",
    "is_recurring": False,
    "created_at": "",
    "granularity": "transaction",
}

# Values Google Sheets can hand back for a boolean, depending on whether the cell
# is a checkbox, plain text, or empty. Normalise all of them in one place.
_TRUE = {True, 1, "TRUE", "True", "true", "1", "是"}


def to_bool(v) -> bool:
    return v in _TRUE


def normalize_date(v) -> pd.Timestamp:
    """Parse a `date` cell into a comparable, time-stripped Timestamp.

    The `date` column's Sheets number format can silently drop the leading
    zero (`"2026-5-2"` vs `"2026-05-2"` — see CLAUDE.md), so two rows for the
    same day can carry different-looking strings. Any date comparison —
    especially the Phase 3 CSV-import dedup matching by amount + date — must
    go through this instead of comparing the raw strings.
    """
    return pd.Timestamp(pd.to_datetime(v)).normalize()


def to_float(v, default: float = 0.0) -> float:
    """Empty cells come back as '' (not None, not 0) — float('') raises."""
    if v is None or v == "":
        return default
    try:
        return float(str(v).replace(",", "").replace("$", "").replace("¥", ""))
    except ValueError:
        return default


def parse_row(raw: dict) -> dict:
    """Sheet row (dict from get_all_records) -> typed dict with every key present.

    Tolerates rows written before a column existed: missing keys fall back to
    DEFAULTS, so the app keeps working between the code deploy and the sheet
    migration.
    """
    out = {h: raw.get(h, DEFAULTS.get(h, "")) for h in HEADERS}
    out["amount"] = to_float(out["amount"])
    out["amount_usd"] = to_float(out["amount_usd"], default=out["amount"])
    out["is_recurring"] = to_bool(out["is_recurring"])
    out["type"] = out["type"] or "Expense"
    out["currency"] = out["currency"] or "USD"
    return out


def row_from_dict(d: dict) -> list:
    """Typed dict -> list in HEADERS order. The ONLY place column order matters."""
    row = []
    for h in HEADERS:
        v = d.get(h, DEFAULTS.get(h, ""))
        if isinstance(v, bool):
            v = "TRUE" if v else "FALSE"
        row.append(v)
    return row
