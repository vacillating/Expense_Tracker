"""
migrate_granularity.py — one-off: widen the live Google Sheet from 14 columns
to 15, adding `granularity` (transaction | monthly_summary). Every existing
row gets "transaction" — they're all itemized entries already; nothing in the
sheet today is a monthly-summary row. The first monthly_summary rows will
come from backfill_ledger.py's CMB aggregate rows, imported separately later.

Much simpler than migrate_schema.py's 6->14 migration: no re-typing, no
re-detecting is_recurring, nothing to compute. Every existing row already has
correctly-typed values for all 14 current columns; row_from_dict() carries
them through unchanged and fills the one new column from schema.DEFAULTS.

Run it TWICE:
    python scripts/migrate_granularity.py           # dry run, changes nothing
    python scripts/migrate_granularity.py --apply    # actually writes

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


def connect():
    cfg = tomllib.loads(SECRETS.read_text())
    creds = Credentials.from_service_account_info(cfg["gcp_service_account"], scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(cfg["sheet_key"])


def migrate_existing(records):
    """14-column rows -> 15-column rows. Pure function of `records` (same
    idempotency property as migrate_schema.py's version): row_from_dict()
    passes every existing field through unchanged and only ever fills
    `granularity` from schema.DEFAULTS, since no row already has that key.
    """
    return [row_from_dict(r) for r in records]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ss = connect()
    # gid=0，不是 .sheet1——理由跟 migrate_schema.py/database.py 里一样。
    ws = ss.get_worksheet_by_id(0)
    current_headers = ws.row_values(1)

    if current_headers == HEADERS:
        print("表头已经是完整的 15 列（跟 schema.HEADERS 完全一致）。")
        print("granularity 迁移已经做过了，这次不需要任何写入。")
        return

    records = ws.get_all_records()
    print(f"existing rows: {len(records)}  (columns: {current_headers})")

    new_rows = migrate_existing(records)
    payload = [HEADERS] + new_rows

    old_sum = sum(float(str(r[HEADERS.index("amount_usd")]).replace(",", "") or 0) for r in new_rows)
    granularity_idx = HEADERS.index("granularity")
    granularity_counts = {}
    for r in new_rows:
        v = r[granularity_idx]
        granularity_counts[v] = granularity_counts.get(v, 0) + 1

    print(f"  migrated rows      : {len(new_rows):>4}  ${old_sum:>10,.2f}")
    print(f"  granularity 分布   : {granularity_counts}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        print("\nFirst 2 migrated rows:")
        for r in new_rows[:2]:
            print("  ", r)
        print("\nLast 2 migrated rows:")
        for r in new_rows[-2:]:
            print("  ", r)
        return

    # 1. Backup INSIDE the same spreadsheet
    backup = f"backup_granularity_{datetime.now():%Y%m%d_%H%M}"
    ss.duplicate_sheet(source_sheet_id=ws.id, new_sheet_name=backup)
    print(f"\nbacked up to tab: {backup}")

    # 2. Rewrite the whole sheet in ONE call, RAW so nothing gets reinterpreted
    ws.clear()
    ws.update(values=payload, range_name="A1", value_input_option="RAW")
    ws.freeze(rows=1)
    print(f"wrote {len(payload)-1} data rows x {len(HEADERS)} columns")

    # 3. Verify by reading back
    check = ws.get_all_records()
    assert len(check) == len(payload) - 1, f"row count mismatch: {len(check)}"
    got = sum(float(str(r["amount_usd"]).replace(",", "") or 0) for r in check)
    assert abs(got - old_sum) < 0.05, f"sum mismatch: {got}"
    assert all(r["granularity"] == "transaction" for r in check), "granularity should be 'transaction' for every existing row"
    print(f"verified: {len(check)} rows, ${got:,.2f}, all granularity='transaction'")


if __name__ == "__main__":
    main()
