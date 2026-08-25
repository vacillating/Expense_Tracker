"""
fix_negative_rows.py — one-off: clean up the 7 negative-amount rows that
leaked into the live sheet through backfill's filtering bug (see
is_negative_settlement() in backfill_ledger.py — used to be gated behind
`_review=='TRUE'` and missed anything not flagged for review).

Gary's disposition after reviewing all 7:

  DELETE (5 rows) — incoming Zelle "别人还的 AA 钱". Money coming back isn't
  negative spending, it's cash inflow; the matching full-price charge (Gary
  paid the whole bill) stays untouched, so 餐饮 (Dine & Grocery) runs
  slightly high (~$215.50 across 4 months) — accepted as negligible rather
  than trying to reconstruct exactly which portion was his.

  KEEP AS-IS (1 row) — Sheraton -$50 deposit refund. Nets a specific,
  identifiable hotel charge — a legitimate Refund row, not touched.

  RE-TAG, DON'T DELETE (1 row) — the -$2,052.83 CMB reimbursement (谭子骁).
  The travel spending it offsets is already recorded at full price spread
  across Chase/Cathay/CMB, so deleting this would inflate August by over
  $2,000. But it doesn't correspond to any single transaction either, so it
  can't stay at transaction granularity without corrupting per-transaction
  analysis (category charts, daily average, Top 5). Moved to
  granularity=monthly_summary, category=其他 (Other), notes clarified.

Run it TWICE:
    python scripts/fix_negative_rows.py            # dry run, changes nothing
    python scripts/fix_negative_rows.py --apply    # actually writes/deletes
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import DBManager  # noqa: E402

# (date, amount_usd, notes 里的一段用来精确定位)
TO_DELETE = [
    ("2026-6-1", -100.00, "别人还的 AA 钱"),
    ("2026-6-26", -83.50, "别人还的 AA 钱"),
    ("2026-7-15", -2.00, "别人还的 AA 钱"),
    ("2026-7-20", -15.00, "别人还的 AA 钱"),
    ("2026-7-30", -15.00, "别人还的 AA 钱"),
]

KEEP_UNCHANGED = ("2026-8-11", -50.00, "酒店押金退回")

RETAG = ("2026-8-11", -2052.83, "东岸旅行代付报销")
RETAG_NEW_NOTES = "8月东岸旅行代付报销，冲抵 Chase/Cathay/招行上的旅行消费（谭子骁）— 净额调整，不对应单笔消费"


def find_one(df, date, amt, needle):
    m = df[
        (df["date"] == date)
        & ((df["amount_usd"] - amt).abs() < 0.01)
        & (df["notes"].astype(str).str.contains(needle, regex=False))
    ]
    assert len(m) == 1, f"预期精确匹配 1 行 ({date}, {amt}, {needle!r})，实际匹配 {len(m)} 行"
    return m.iloc[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = DBManager()
    df = db.get_transactions()
    print(f"表里总行数: {len(df)}")

    delete_rows = [find_one(df, *spec) for spec in TO_DELETE]
    keep_row = find_one(df, *KEEP_UNCHANGED)
    retag_row = find_one(df, *RETAG)

    print(f"\n=== 要删除的 {len(delete_rows)} 行（别人还的 AA 钱，资金回流不该在支出表里）===\n")
    for r in delete_rows:
        print(f"  {r['date']}  ${r['amount_usd']:.2f}  {r['merchant']}  notes={r['notes']!r}  id={r['id']}")

    print(f"\n=== 确认保留不动的 1 行（标准退款，对应明确一笔消费）===\n")
    print(f"  {keep_row['date']}  ${keep_row['amount_usd']:.2f}  {keep_row['merchant']}  "
          f"notes={keep_row['notes']!r}  category={keep_row['category']!r}  "
          f"granularity={keep_row['granularity']!r}  （不动）")

    print(f"\n=== 要改的 1 行（笼统冲抵，改成 monthly_summary）===\n")
    print(f"  {retag_row['date']}  ${retag_row['amount_usd']:.2f}  merchant={retag_row['merchant']!r}")
    print(f"  category:     {retag_row['category']!r} -> '其他 (Other)'")
    print(f"  granularity:  {retag_row['granularity']!r} -> 'monthly_summary'")
    print(f"  notes:        {retag_row['notes']!r}")
    print(f"           ->   {RETAG_NEW_NOTES!r}")

    if not args.apply:
        print("\nDRY RUN — 没有写入/删除任何东西。确认无误后加 --apply 重跑。")
        return

    for r in delete_rows:
        db.delete_transaction(r["id"])
    print(f"\n已删除 {len(delete_rows)} 行。")

    db.update_transaction(
        retag_row["id"],
        category="其他 (Other)",
        granularity="monthly_summary",
        notes=RETAG_NEW_NOTES,
    )
    print("已更新那笔大额冲抵行。")

    # 读回验证
    df_after = db.get_transactions()
    print(f"\n验证：表里现在总行数 = {len(df_after)}（应该是 {len(df) - len(delete_rows)}）")
    assert len(df_after) == len(df) - len(delete_rows)

    for r in delete_rows:
        assert (df_after["id"] == r["id"]).sum() == 0, f"删除失败：{r['id']} 还在表里"
    print("验证：5 行 Zelle 确认已删除")

    keep_after = df_after[df_after["id"] == keep_row["id"]].iloc[0]
    assert keep_after["amount_usd"] == keep_row["amount_usd"]
    assert keep_after["category"] == keep_row["category"]
    assert keep_after["granularity"] == keep_row["granularity"]
    print("验证：Sheraton 退款行确认没被动过")

    retag_after = df_after[df_after["id"] == retag_row["id"]].iloc[0]
    assert retag_after["category"] == "其他 (Other)"
    assert retag_after["granularity"] == "monthly_summary"
    assert retag_after["amount_usd"] == retag_row["amount_usd"], "金额不该被改动"
    print("验证：大额冲抵行确认 category/granularity 改对了，金额没变")


if __name__ == "__main__":
    main()
