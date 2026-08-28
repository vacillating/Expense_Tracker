"""
bot_handlers.py — Telegram bot business logic. No network/HTTP framework
code here — this is what gets unit tested without a live network. The
webhook entry point (not written yet, see CLAUDE.md TODO) is a thin layer
that reads the Telegram update, calls handle_message()/handle_undo(), and
posts the reply back.

Uses sheets.py directly, not database.py — database.py wraps things with
Streamlit's @st.cache_data/@st.cache_resource, which a serverless function
(no Streamlit runtime) can't use and shouldn't need; it also drags in
pandas, which this bot's bundle doesn't want.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import sheets
from parser import ParseError, parse_expense
from schema import normalize_date

# 跟 CLAUDE.md 里记的历史 backfill 用的同一个固定汇率（scripts/build_ledger.py
# 里也是这个数字）。换算在这里做，不在 LLM 里做——parser.py 的硬约束 1 就是
# "绝不做算术"，汇率换算也是算术，同样的道理不能让模型来算。
FIXED_RATE_CNY_PER_USD = 6.72


def _amount_usd(amount: float, currency: str) -> float:
    if currency == "CNY":
        return round(amount / FIXED_RATE_CNY_PER_USD, 2)
    return amount


def _date_label(date_str: str, today: date) -> str:
    """给回执用的日期显示："今天"/"昨天"/"MM-DD"。用 normalize_date() 解析——
    这个日期字符串是 LLM 刚生成的（格式固定是 YYYY-MM-DD），本身不会有
    CLAUDE.md 里说的那个 Sheets 补零问题，但统一走 normalize_date() 没有
    坏处，也跟这段代码里其他要读表里已有 date 值的地方（handle_undo）用
    同一套解析逻辑，不用维护两份。
    """
    d = normalize_date(date_str).date()
    if d == today:
        return "今天"
    if d == today - timedelta(days=1):
        return "昨天"
    return d.strftime("%m-%d")


def _entry_to_row(entry: dict, update_id, index: int, today: date) -> dict:
    """parser.py 吐出来的一条 entry -> schema 的行（外加三个额外 key，
    category_confident / payment_method_confident / _date_label，只给
    format_receipt 用于显示，真正写表时 schema.row_from_dict() 只认
    HEADERS 里的列名，这三个额外字段会被自动忽略，不会真的写进表——
    不需要专门去掉）。
    """
    amount = entry["amount"]
    currency = entry.get("currency") or "USD"
    entry_date = entry.get("date") or today.isoformat()
    return {
        "id": str(uuid.uuid4()),
        "date": entry_date,
        "type": "Expense",
        "category": entry["category"],
        "amount": amount,
        "currency": currency,
        "amount_usd": _amount_usd(amount, currency),
        "merchant": entry.get("merchant", ""),
        "notes": entry.get("notes", ""),
        "payment_method": entry.get("payment_method", ""),
        "source": "telegram",
        "external_id": f"tg:{update_id}:{index}",
        "is_recurring": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "granularity": "transaction",
        # 下面三个不是 schema 列，只给 format_receipt 用：
        "category_confident": entry.get("category_confident", True),
        "payment_method_confident": entry.get("payment_method_confident", True),
        "_date_label": _date_label(entry_date, today),
    }


def handle_message(text: str, update_id, today: date) -> tuple[int, str]:
    """解析一条消息，把能记的都记下来。返回 (实际写入的行数, 回执文本)。

    幂等：同一个 update_id 已经处理过的，直接跳过、不重复写、不重复回执。
    Telegram 在没及时收到 200 时会重投递同一条 update，不做这层会记两遍账。
    external_id（格式 "tg:{update_id}:{i}"）当初定义的就是"确定性指纹"，
    正好是它的用途——查表里有没有以这个 update_id 开头的 external_id，
    有就说明处理过了。
    """
    sheet = sheets.connect()
    # 只读 external_id 这一列，不用 get_all_records() 拉整张表（15 列 ×
    # 几百行）——serverless 的超时预算经不起每条消息都读一遍全表，行数
    # 只会涨不会跌。
    existing_external_ids = sheets.get_column(sheet, "external_id")
    prefix = f"tg:{update_id}:"
    if any(str(v).startswith(prefix) for v in existing_external_ids):
        return 0, ""  # 重复投递，静默跳过，不重复发回执

    try:
        entries = parse_expense(text, today)
    except ParseError:
        return 0, "❌ 没解析明白，麻烦换个说法再发一次。"

    if not entries:
        return 0, ""

    receipt_items = []
    rows_to_write = []
    for i, entry in enumerate(entries):
        if entry.get("amount") is None:
            # 硬约束 2：绝不猜金额。这种条目不写表，回执里提示用户重发。
            receipt_items.append({"_unparsed": True, "notes": entry.get("notes") or text})
            continue
        row = _entry_to_row(entry, update_id, i, today)
        rows_to_write.append(row)
        receipt_items.append(row)

    if rows_to_write:
        sheets.append_rows(sheet, rows_to_write)

    return len(rows_to_write), format_receipt(receipt_items)


def format_receipt(rows: list[dict]) -> str:
    """把 handle_message 组装好的条目（写成功的行 + 没看懂金额的条目）格式化
    成回执文本。

    规则：
    - payment_method 为空且没有识别失败（用户本来就没说）就不显示那一段，
      不显示"未知"；payment_method_confident 为 false（识别失败被回落成
      空）时改显示 ⚠️ 提示，不是悄悄什么都不显示——软失败不是静默失败
    - category_confident 为 false 时分类后面加 ⚠️
    （这两个 confident 字段都不是表里的列，只用于这里显示——15 列里没有
      它们，要加列得走 CLAUDE.md 里两次提交的规则，今晚不做）
    - amount 缺失（_unparsed 标记）的条目改成提示重发
    - 多笔时每笔一行，/undo 整条消息只出现一次（撤销的是这条消息产生的
      全部行，不是某一笔）
    """
    if not rows:
        return ""

    lines = []
    any_written = False
    for r in rows:
        if r.get("_unparsed"):
            lines.append(f'❓ 没看懂金额："{r["notes"]}"\n   重发一条带具体数字的')
            continue

        any_written = True
        category = r["category"]
        if not r.get("category_confident", True):
            category += " ⚠️"

        symbol = "¥" if r["currency"] == "CNY" else "$"
        line = f"✅ {symbol}{float(r['amount']):.2f} · {category} · {r['_date_label']}\n   {r['notes']}"
        if r.get("payment_method"):
            line += f"\n   {r['payment_method']}"
        elif not r.get("payment_method_confident", True):
            line += "\n   ⚠️ 支付方式没识别出来"
        lines.append(line)

    if any_written:
        lines.append("/undo")
    return "\n".join(lines)


def _update_id_from_external_id(external_id) -> str | None:
    """external_id 格式是 'tg:{update_id}:{i}'。解析不出来（格式不对，或者
    以后出现别的 source 用别的前缀）就返回 None，不崩——调用方自己决定
    解析失败时怎么办。"""
    parts = str(external_id).split(":")
    if len(parts) != 3 or parts[0] != "tg":
        return None
    return parts[1]


def handle_undo(today: date) -> str:
    """撤销"最近一条消息"产生的全部行（一条消息解析出好几笔的话，一起撤销）。

    "最近一条消息"用 external_id（格式 'tg:{update_id}:{i}'）精确定义，
    不是靠 created_at 精确到秒去猜——同一条消息解析出的多笔，update_id
    一定相同；不同消息即使凑巧同一秒发送，update_id 也一定不同，不会
    像之前那版一样被误判成"同一条消息"。

    做法：先按 created_at 找出最新的那一行（这一步只用来定位"最近是哪次
    操作"，不是最终依据），从它的 external_id 解析出 update_id，再删掉
    所有 external_id 以 'tg:{update_id}:' 开头的行。

    created_at 比较用普通字符串比较，不走 normalize_date()——created_at
    是这段代码自己生成的 ISO 时间戳（datetime.now().isoformat(timespec=
    "seconds")），永远是补零的 "YYYY-MM-DDTHH:MM:SS"，本身就能正确排序；
    normalize_date() 还会把时间戳按天取整（内部调用 .normalize()），反而
    会丢掉"同一天内谁更晚"这个信息，用在这里是错的。
    """
    sheet = sheets.connect()
    records = sheets.get_all_records(sheet)
    telegram_rows = [r for r in records if r.get("source") == "telegram"]
    if not telegram_rows:
        return "没有可撤销的记录。"

    latest_row = max(telegram_rows, key=lambda r: r.get("created_at", ""))
    update_id = _update_id_from_external_id(latest_row.get("external_id"))
    if update_id is None:
        # 最新那行的 external_id 格式不对——理论上不该发生（source='telegram'
        # 的行都是 handle_message 自己写的），但解析失败不该导致整个撤销
        # 操作崩掉或者什么都不做，保底只撤销这一行。
        to_delete = [latest_row]
    else:
        to_delete = [r for r in telegram_rows
                     if _update_id_from_external_id(r.get("external_id")) == update_id]

    for r in to_delete:
        sheets.delete_row(sheet, r["id"])

    lines = []
    for r in to_delete:
        date_display = normalize_date(r["date"]).strftime("%Y-%m-%d")
        lines.append(f"   {date_display}  {r['notes']}（${float(r['amount']):.2f}）")

    header = f"↩️ 已撤销 {len(to_delete)} 笔：" if len(to_delete) > 1 else "↩️ 已撤销："
    return header + "\n" + "\n".join(lines)
