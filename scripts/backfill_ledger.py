"""
backfill_ledger.py — one-off: append the 2026-05..08 backfill ledger
(data/ledger_v3_20260501_20260823.csv) to the Google Sheet.

NOT PART OF TODAY'S MIGRATION. This is Roadmap Phase 3 work — split out of
what used to be migrate_sheet.py because it has completely different rerun
characteristics from the schema migration: this is a pure append, and
appending the same CSV twice duplicates every row. There is no de-dup logic
here yet (that's what `external_id` is for — matching against rows already in
the sheet before appending — but it isn't implemented; add it before this
script is actually used for real, not before).

Prerequisite: the sheet must already be at the full 14-column schema
(run scripts/migrate_schema.py --apply first) — this script assumes HEADERS
order and does not widen anything itself.

Run it TWICE:
    python scripts/backfill_ledger.py                 # dry run, changes nothing
    python scripts/backfill_ledger.py --apply         # actually writes
"""
import argparse
import csv
import sys
from pathlib import Path

import gspread
import tomllib
from google.oauth2.service_account import Credentials

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from schema import HEADERS, row_from_dict  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SECRETS = Path(".streamlit/secrets.toml")
LEDGER = Path("data/ledger_v3_20260501_20260823.csv")


def connect():
    cfg = tomllib.loads(SECRETS.read_text())
    creds = Credentials.from_service_account_info(cfg["gcp_service_account"], scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(cfg["sheet_key"])


def load_ledger(now_iso: str):
    rows = []
    with LEDGER.open() as f:
        for r in csv.DictReader(f):
            r.pop("_review", None)      # helper column, not part of the schema
            r["created_at"] = r.get("created_at") or now_iso
            rows.append(row_from_dict(r))
    return rows


def main():
    import datetime as dt

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ss = connect()
    # gid=0，不是 .sheet1（按索引取）——见 database.py / migrate_schema.py 里同样的注释：
    # 备份分页会占掉索引 0，.sheet1 会连到备份而不是真实数据。
    ws = ss.get_worksheet_by_id(0)
    if ws.row_values(1) != HEADERS:
        print("sheet1 的表头还不是完整 14 列 —— 先跑 migrate_schema.py --apply。")
        sys.exit(1)

    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    rows = load_ledger(now_iso)
    total = sum(float(r[HEADERS.index("amount_usd")]) for r in rows)
    print(f"backfill ledger: {len(rows)} rows, ${total:,.2f}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        print("First 2 rows:")
        for r in rows[:2]:
            print("  ", r)
        return

    # TODO before real use: check each row's external_id against what's
    # already in the sheet and skip duplicates — this makes reruns safe.
    ws.append_rows(rows, value_input_option="RAW")
    print(f"appended {len(rows)} rows.")


if __name__ == "__main__":
    main()
