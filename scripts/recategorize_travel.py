"""
recategorize_travel.py — one-off: fix category on rows that should be
"旅行 (Travel)" but got imported as "交通 (Transport)" or (one case)
"娱乐 (Entertainment)".

Three groups, matched as precisely as possible (not a broad keyword sweep):

  A. Flights/hotels/Airbnb/Agoda/Expedia already imported via backfill_ledger.py
     (source in csv_chase/csv_cathay4826/csv_cathay8115), matched on `merchant`.
     Expected: exactly 33 rows.
  B. Four specific vacation car rentals from the CMB manual batch, matched by
     exact (date, amount_usd, a distinctive notes substring) — NOT a bare
     "BUDGET|AVIS|SIXT|NATIONAL" sweep, because two of those same merchants
     also cover a moving-truck rental that must NOT be recategorized (see
     the explicit exclusion check below).
  C. The one CMB "EXPEDIA" row — its merchant field is blank (CMB manual rows
     put the description in `notes`, not `merchant`), so group A's merchant
     regex can't see it; matched by source + date + amount instead.

Explicitly prints the 3 rows that must stay "交通 (Transport)" (moving-truck
rentals) as a visible check that they were NOT swept up.

Run it TWICE:
    python scripts/recategorize_travel.py            # dry run, changes nothing
    python scripts/recategorize_travel.py --apply    # actually writes
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import DBManager  # noqa: E402

NEW_CATEGORY = "旅行 (Travel)"

FLIGHT_HOTEL_RE = re.compile(
    r"AMERICAN AIR|SOUTHWES|DELTA|UNITED|FRONTIER|SPIRIT|EXPEDIA|AGODA|BOOKING|"
    r"HOTEL|SHERATON|MARRIOTT|HILTON|HOSTEL|AIRBNB|去哪儿|边疆航空",
    re.I,
)
IMPORTED_SOURCES = {"csv_chase", "csv_cathay4826", "csv_cathay8115"}

# (date, amount_usd, notes 里的一段用来精确定位)
VACATION_RENTALS = [
    ("2026-05-11", 386.30, "带家人旅行"),
    ("2026-05-16", 231.23, "SIXT"),
    ("2026-05-23", 209.41, "SIXT"),
    ("2026-05-08", 117.29, "BUDGET RENTAL LICEN"),
]

# 必须留在 "交通 (Transport)" 的行——搬家租车，不是旅游。只用来核对，不做任何改动。
MUST_NOT_CHANGE = [
    ("2026-08-08", 316.96, "BUDGET"),
    ("2026-08-14", 224.70, "租车"),
    ("2026-07-29", 157.72, "AVIS"),
]

CMB_EXPEDIA = ("2026-05-18", 141.64, "manual_cmb_summary")


def find_matches(df):
    a_rows = df[
        df["source"].isin(IMPORTED_SOURCES)
        & df["merchant"].astype(str).str.contains(FLIGHT_HOTEL_RE, na=False)
    ]

    b_ids = []
    for date, amt, needle in VACATION_RENTALS:
        m = df[
            (df["date"] == date)
            & ((df["amount_usd"] - amt).abs() < 0.01)
            & (df["notes"].astype(str).str.contains(re.escape(needle)))
        ]
        assert len(m) == 1, f"预期精确匹配 1 行 ({date}, {amt}, {needle!r})，实际匹配 {len(m)} 行"
        b_ids.append(m.iloc[0])

    c_date, c_amt, c_source = CMB_EXPEDIA
    c_match = df[
        (df["date"] == c_date)
        & ((df["amount_usd"] - c_amt).abs() < 0.01)
        & (df["source"] == c_source)
    ]
    assert len(c_match) == 1, f"CMB Expedia 行预期匹配 1 行，实际匹配 {len(c_match)} 行"

    return a_rows, b_ids, c_match.iloc[0]


def find_excluded(df):
    rows = []
    for date, amt, needle in MUST_NOT_CHANGE:
        m = df[
            (df["date"] == date)
            & ((df["amount_usd"] - amt).abs() < 0.01)
            & (df["notes"].astype(str).str.contains(re.escape(needle)))
        ]
        assert len(m) == 1, f"预期精确匹配 1 行 ({date}, {amt}, {needle!r})，实际匹配 {len(m)} 行"
        rows.append(m.iloc[0])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = DBManager()
    df = db.get_transactions()
    print(f"表里总行数: {len(df)}")

    a_rows, b_rows, c_row = find_matches(df)
    excluded = find_excluded(df)

    assert len(a_rows) == 33, f"机票/酒店组预期 33 行，实际 {len(a_rows)} 行"

    all_targets = list(a_rows.iterrows()) + [(None, r) for r in b_rows] + [(None, c_row)]
    print(f"\n=== 要改成 '{NEW_CATEGORY}' 的 {len(all_targets)} 行 ===\n")
    for _, r in all_targets:
        print(f"  {r['date']}  {r['category']!r} -> {NEW_CATEGORY!r}  "
              f"${r['amount_usd']:.2f}  merchant={r['merchant']!r}  notes={r['notes']!r}")

    print(f"\n=== 核对：这 3 行必须保持 '交通 (Transport)' 不变（搬家租车） ===\n")
    for r in excluded:
        assert r["category"] == "交通 (Transport)", f"预期还是交通，实际是 {r['category']!r}"
        print(f"  {r['date']}  {r['category']!r}（不动）  ${r['amount_usd']:.2f}  notes={r['notes']!r}")

    if not args.apply:
        print("\nDRY RUN — 没有写入任何东西。确认无误后加 --apply 重跑。")
        return

    for _, r in all_targets:
        db.update_transaction(r["id"], category=NEW_CATEGORY)
    print(f"\n已更新 {len(all_targets)} 行为 '{NEW_CATEGORY}'。")

    # 读回验证
    df_after = db.get_transactions()
    travel_count = (df_after["category"] == NEW_CATEGORY).sum()
    print(f"验证：表里现在 category='{NEW_CATEGORY}' 的行数 = {travel_count}")
    assert travel_count == len(all_targets), "更新后数量对不上"
    for r in excluded:
        after = df_after[df_after["id"] == r["id"]].iloc[0]
        assert after["category"] == "交通 (Transport)", "排除的行被误改了！"
    print("验证：3 行搬家租车确认没被误改，还是 '交通 (Transport)'")


if __name__ == "__main__":
    main()
