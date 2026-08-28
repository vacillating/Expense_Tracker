"""
diff_csv_vs_sheet.py — 只读，比对 data/ 里"本该导入"的 CSV 跟线上表，
列出 CSV 里有但表里找不到的行。不写任何东西回表。

背景：2026-08 那次数据丢失事故，被覆盖的第 559 行原来是什么已经无法从
Sheets 版本历史直接看到内容（只能看到覆盖前后的整行文本 diff，事后才
发现）。这个脚本用来检查 backfill 相关的 CSV 里是否还有其他行也在这次
事故里丢了。

只比对两个"本该被导入"的文件：
  - data/ledger_v3_20260501_20260823.csv（203 行，每行都有真实 external_id，
    用 external_id 做精确匹配）
  - data/cmb_manual_backfill_202605_202608.csv（33 行，手动录入，没有
    external_id，用 normalize_date(date) + amount_usd 做匹配）
data/ledger_v3_excluded_20260824.csv 不比——那 19 行是当初故意排除、
不导入的（重复/存疑/退款等），"表里没有"是预期状态，不是丢失。

Run: python scripts/diff_csv_vs_sheet.py
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from database import DBManager  # noqa: E402
from schema import normalize_date  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LEDGER_WITH_EXTERNAL_ID = DATA_DIR / "ledger_v3_20260501_20260823.csv"
CMB_MANUAL_NO_EXTERNAL_ID = DATA_DIR / "cmb_manual_backfill_202605_202608.csv"


def main():
    db = DBManager()
    sheet_df = db.get_transactions()
    print(f"线上表总行数: {len(sheet_df)}")
    print(f"线上表日期范围: {sheet_df['date'].min()} ~ {sheet_df['date'].max()}"
          if not sheet_df.empty else "线上表是空的")

    sheet_external_ids = set(sheet_df["external_id"].astype(str))
    # 用于日期+金额匹配：(normalize_date(date), 保留2位小数的amount_usd)
    sheet_date_amount = set()
    for _, r in sheet_df.iterrows():
        try:
            d = normalize_date(r["date"])
        except Exception:
            continue
        amt = round(float(r["amount_usd"]), 2) if str(r["amount_usd"]).strip() != "" else None
        if amt is not None:
            sheet_date_amount.add((d, amt))

    print()
    print("=" * 70)
    print(f"[1] {LEDGER_WITH_EXTERNAL_ID.name}（按 external_id 精确匹配）")
    print("=" * 70)
    missing_1 = []
    with LEDGER_WITH_EXTERNAL_ID.open() as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["external_id"] not in sheet_external_ids:
            missing_1.append(r)
    print(f"CSV 共 {len(rows)} 行，线上表里找不到 external_id 的: {len(missing_1)} 行")
    for r in missing_1:
        print(f"  {r['date']}  {r['amount']} {r['currency']} (~${r['amount_usd']})  "
              f"{r['merchant']}  external_id={r['external_id']}")

    print()
    print("=" * 70)
    print(f"[2] {CMB_MANUAL_NO_EXTERNAL_ID.name}（没有 external_id，"
          f"按 normalize_date(date) + amount_usd 匹配，不比字符串）")
    print("=" * 70)
    missing_2 = []
    with CMB_MANUAL_NO_EXTERNAL_ID.open() as f:
        rows2 = list(csv.DictReader(f))
    for r in rows2:
        try:
            d = normalize_date(r["date"])
        except Exception:
            missing_2.append((r, "日期解析失败"))
            continue
        amt = round(float(r["amount_usd"]), 2)
        if (d, amt) not in sheet_date_amount:
            missing_2.append((r, None))
    print(f"CSV 共 {len(rows2)} 行，线上表里按(日期,金额)找不到匹配的: {len(missing_2)} 行")
    for r, reason in missing_2:
        tag = f"（{reason}）" if reason else ""
        print(f"  {r['date']}  ${r['amount_usd']}  {r['notes']}{tag}")

    print()
    print("=" * 70)
    print("[3] 关于 2025-11 月底那一笔")
    print("=" * 70)
    print("上面两个文件的日期范围都只覆盖 2026-05 ~ 2026-08，不包含 2025-11。")
    print("这次比对结构性地找不到那一笔——不是查漏了，是本地根本没有覆盖")
    print("2025-11 的 CSV 可以拿来比对。那一笔应该是更早、这次会话开始之前")
    print("就已经在表里的记录（source 大概率是 'manual'，直接 Quick Log 录入的，")
    print("从来没经过任何 CSV），没有原始文件能拿来对——只能凭记忆或者别处的")
    print("记录（比如银行/微信账单本身）手动补。")


if __name__ == "__main__":
    main()
