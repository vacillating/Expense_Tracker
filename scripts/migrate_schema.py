"""
migrate_schema.py — one-off: widen the live Google Sheet from 6 columns to 14,
carrying forward every existing row's own data. Does NOT touch data/ledger_v3
or add any new rows — that's backfill_ledger.py's job (Roadmap Phase 3, not run
today). Splitting these two apart matters because they have different failure
and rerun characteristics: this script is a pure, idempotent transform of rows
that already exist; the backfill is a one-shot append that duplicates data if
you rerun it.

Run it TWICE:
    python scripts/migrate_schema.py                 # dry run, changes nothing
    python scripts/migrate_schema.py --apply         # actually writes

Requires .streamlit/secrets.toml with [gcp_service_account] and sheet_key.
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

import gspread
import tomllib
from google.oauth2.service_account import Credentials

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schema import HEADERS, row_from_dict  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SECRETS = Path(".streamlit/secrets.toml")

# Existing hand-maintained templates — used ONCE to label history, then retired.
# This is the exact (category, amount) matching CLAUDE.md flags as fragile;
# is_recurring is meant to replace it going forward, but for backfilling
# *history* there's no better signal than the templates that generated it.
FIXED_TEMPLATES = [
    ("房租 (Rent)", 600.0), ("其他 (Other)", 25.0),
    ("娱乐 (Entertainment)", 34.93), ("医疗 (Medical)", 5.0),
]


def connect():
    cfg = tomllib.loads(SECRETS.read_text())
    creds = Credentials.from_service_account_info(cfg["gcp_service_account"], scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(cfg["sheet_key"])


def is_fixed(cat, amt):
    return any(cat == c and abs(amt - a) < 0.01 for c, a in FIXED_TEMPLATES)


def migrate_existing(records):
    """Old 6-column rows -> new 14-column rows. Pure function of `records`:
    same input always produces the same output (see NOTES on idempotency
    at the bottom of this file) — as long as every row already has a
    non-empty `id` (true once the blank rows are deleted from the sheet).

    Rule: a default means 'we know it is this'; blank means 'we do not know'.
    So source='manual' (true — they were typed by hand) but payment_method=''
    (genuinely unknown; filling it in would be inventing data).
    """
    out = []
    recurring_rows = []  # for the human-readable report, not written anywhere
    for r in records:
        amt = float(str(r.get("amount", 0) or 0).replace(",", ""))
        cat = r.get("category", "")
        recurring = is_fixed(cat, amt)
        if recurring:
            recurring_rows.append({
                "date": r.get("date", ""), "category": cat,
                "amount": amt, "notes": r.get("notes", ""),
            })
        out.append(row_from_dict({
            "id": r.get("id") or "",  # 空 id 不再用 uuid4() 兜底——那是给"新增数据"用的逻辑，
                                        # 这里只搬运已有行，缺 id 说明这行本身有问题，不该悄悄编一个。
            "date": r.get("date", ""),
            "type": r.get("type") or "Expense",
            "category": cat,
            "amount": amt,
            "currency": "USD",          # confirmed: all pre-migration rows are USD
            "amount_usd": amt,
            "merchant": "",             # not recoverable from notes; leave blank
            "notes": r.get("notes", ""),
            "payment_method": "",       # unknown
            "source": "manual",
            "external_id": "",
            "is_recurring": recurring,
            "created_at": "",           # unknown; do not fake it with `date`
        }))
    return out, recurring_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ss = connect()
    # gid=0，不是 .sheet1（按索引取）——duplicate_sheet() 建的备份分页会插到索引 0，
    # 把真实数据分页挤到索引 1；gid 不受分页顺序影响，见 database.py 里同样的注释。
    ws = ss.get_worksheet_by_id(0)
    current_headers = ws.row_values(1)

    if current_headers == HEADERS:
        print("表头已经是完整的 14 列（跟 schema.HEADERS 完全一致）。")
        print("Schema 迁移已经做过了，这次不需要任何写入。")
        return

    records = ws.get_all_records()
    print(f"existing rows: {len(records)}  (columns: {current_headers})")

    new_rows, recurring_rows = migrate_existing(records)
    payload = [HEADERS] + new_rows

    old_sum = sum(float(r[HEADERS.index("amount_usd")]) for r in new_rows)
    print(f"  migrated rows     : {len(new_rows):>4}  ${old_sum:>10,.2f}")
    print(f"  recurring flagged : {len(recurring_rows)}")
    print()
    print(f"  被标为 is_recurring=True 的 {len(recurring_rows)} 行（按 FIXED_TEMPLATES 的 "
          f"(category, amount) 匹配，逐行核对）：")
    for row in recurring_rows:
        print(f"    {row['date']:<12} {row['category']:<22} "
              f"${row['amount']:>8.2f}  {row['notes']}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        print("\nFirst 2 migrated rows:")
        for r in new_rows[:2]:
            print("  ", r)
        return

    # 1. Backup INSIDE the same spreadsheet — one API call, no Drive copy needed
    backup = f"backup_schema_{datetime.now():%Y%m%d_%H%M}"
    ss.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=backup)
    print(f"\nbacked up to tab: {backup}")

    # 2. Rewrite the whole sheet in ONE call (row-by-row would blow the quota).
    #    value_input_option="RAW": we're carrying data forward verbatim, not
    #    typing it into a spreadsheet UI — USER_ENTERED would let Sheets
    #    reinterpret date-looking strings, formula-looking notes, and leading
    #    zeros. See scripts/raw_vs_user_entered_check.py for the empirical check.
    ws.clear()
    ws.update(values=payload, range_name="A1", value_input_option="RAW")
    ws.freeze(rows=1)
    print(f"wrote {len(payload)-1} data rows x {len(HEADERS)} columns")

    # 3. Verify by reading back, not by trusting the write
    check = ws.get_all_records()
    assert len(check) == len(payload) - 1, f"row count mismatch: {len(check)}"
    got = sum(float(str(r["amount_usd"]).replace(",", "") or 0) for r in check)
    assert abs(got - old_sum) < 0.05, f"sum mismatch: {got}"
    print(f"verified: {len(check)} rows, ${got:,.2f}")


if __name__ == "__main__":
    main()


# --- NOTES on idempotency --------------------------------------------------
# migrate_existing() is a pure function: given the same `records`, it produces
# byte-identical output every time. Nothing in it reads the clock or generates
# randomness (created_at is hardcoded to "", id is carried through as-is, not
# regenerated). So running this script twice against an *unmigrated* sheet
# would write the same 14-column data both times.
#
# The only actual protection against a wasted/duplicate second run is the
# header check at the top of main(): once sheet1's headers equal HEADERS, the
# script no-ops instead of re-clearing and re-writing. That's what makes a
# rerun *cheap and safe* rather than merely "would produce the same result if
# you let it run."
#
# Caveat: if any row reaching migrate_existing() has a blank `id`, the row is
# written with id="" — deliberately not patched with a fresh uuid4() per row
# (that was the old migrate_sheet.py's behavior, and it's what silently turned
# blank filler rows into fake-looking "real" transactions with a random UUID
# each run). Blank ids are being removed from the sheet by hand before this
# script runs for real, so this shouldn't come up — but if it does, the blank
# id makes each rerun's output for that one row differ only in nothing (it's
# still ""), so it doesn't actually break idempotency, it just means that row
# is visibly incomplete in the output, which is honest.
