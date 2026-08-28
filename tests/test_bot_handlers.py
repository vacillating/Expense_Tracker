"""
tests/test_bot_handlers.py — Group A: mock 掉 sheets.py 和 parser.py，测
handle_message/format_receipt/handle_undo 的纯逻辑。不碰真实 Sheets、不调
真实 LLM，进 CI 必须全绿。
"""
from datetime import date
from unittest.mock import patch

import pytest

import bot_handlers

FAKE_SHEET = object()  # sheets.connect() 返回什么这里不关心，只要能被原样传下去


@pytest.fixture(autouse=True)
def _mock_connect(monkeypatch):
    monkeypatch.setattr(bot_handlers.sheets, "connect", lambda: FAKE_SHEET)


def _entry(amount=60, category="餐饮 (Dine & Grocery)", currency="USD",
           merchant="火锅", notes="火锅60", payment_method="", date_="2026-08-26",
           confident=True, payment_confident=True):
    return {
        "amount": amount, "currency": currency, "category": category,
        "merchant": merchant, "notes": notes, "payment_method": payment_method,
        "date": date_, "category_confident": confident,
        "payment_method_confident": payment_confident,
    }


def _sheet_row(id_, notes, amount, created_at, external_id,
               date_="2026-08-26", source="telegram"):
    return {
        "id": id_, "date": date_, "type": "Expense", "category": "餐饮 (Dine & Grocery)",
        "amount": amount, "currency": "USD", "amount_usd": amount, "merchant": "",
        "notes": notes, "payment_method": "", "source": source, "external_id": external_id,
        "is_recurring": "FALSE", "created_at": created_at, "granularity": "transaction",
    }


# ---------------------------------------------------------------- handle_message

def test_row_assembly_lands_in_correct_columns():
    written = []
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.sheets.append_rows", side_effect=lambda sheet, rows: written.extend(rows)), \
         patch("bot_handlers.parse_expense", return_value=[_entry()]):
        count, receipt = bot_handlers.handle_message("火锅60", update_id=111, today=date(2026, 8, 26))

    assert count == 1
    row = written[0]
    assert row["amount"] == 60
    assert row["amount_usd"] == 60  # USD，跟 amount 一致
    assert row["currency"] == "USD"
    assert row["category"] == "餐饮 (Dine & Grocery)"
    assert row["notes"] == "火锅60"
    assert row["type"] == "Expense"
    assert row["source"] == "telegram"
    assert row["external_id"] == "tg:111:0"
    assert row["granularity"] == "transaction"
    assert row["is_recurring"] is False
    assert receipt != ""


def test_idempotent_same_update_id_processed_twice_writes_once():
    store = []

    with patch("bot_handlers.sheets.get_column",
               side_effect=lambda sheet, col: [r["external_id"] for r in store]), \
         patch("bot_handlers.sheets.append_rows", side_effect=lambda sheet, rows: store.extend(rows)), \
         patch("bot_handlers.parse_expense", return_value=[_entry()]):
        count1, reply1 = bot_handlers.handle_message("火锅60", update_id=222, today=date(2026, 8, 26))
        count2, reply2 = bot_handlers.handle_message("火锅60", update_id=222, today=date(2026, 8, 26))

    assert count1 == 1
    assert count2 == 0
    assert reply2 == ""  # 重复投递，静默跳过
    assert len(store) == 1  # 只真的写了一次


def test_idempotency_check_only_reads_external_id_column_not_whole_sheet():
    """幂等检查必须用 sheets.get_column（只读一列），不能退回 get_all_records
    （拉整张表）——这条测试锁住这个选择，不让它被悄悄改回去。"""
    with patch("bot_handlers.sheets.get_column", return_value=[]) as col_mock, \
         patch("bot_handlers.sheets.get_all_records") as all_records_mock, \
         patch("bot_handlers.sheets.append_rows"), \
         patch("bot_handlers.parse_expense", return_value=[_entry()]):
        bot_handlers.handle_message("火锅60", update_id=888, today=date(2026, 8, 26))

    col_mock.assert_called_once_with(FAKE_SHEET, "external_id")
    all_records_mock.assert_not_called()


def test_multi_entry_message_writes_n_rows_with_indexed_external_id():
    written = []
    entries = [_entry(amount=5, notes="咖啡5"), _entry(amount=6, notes="咖啡6"), _entry(amount=7, notes="咖啡7")]
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.sheets.append_rows", side_effect=lambda sheet, rows: written.extend(rows)), \
         patch("bot_handlers.parse_expense", return_value=entries):
        count, _ = bot_handlers.handle_message("咖啡5, 咖啡6, 咖啡7", update_id=333, today=date(2026, 8, 26))

    assert count == 3
    assert [r["external_id"] for r in written] == ["tg:333:0", "tg:333:1", "tg:333:2"]


def test_cny_amount_converted_at_fixed_rate():
    written = []
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.sheets.append_rows", side_effect=lambda sheet, rows: written.extend(rows)), \
         patch("bot_handlers.parse_expense", return_value=[_entry(amount=28, currency="CNY", notes="奶茶28块")]):
        bot_handlers.handle_message("奶茶28块", update_id=444, today=date(2026, 8, 26))

    row = written[0]
    assert row["currency"] == "CNY"
    assert row["amount"] == 28
    assert row["amount_usd"] == round(28 / bot_handlers.FIXED_RATE_CNY_PER_USD, 2)


def test_null_amount_entry_not_written_and_prompts_resend():
    entry = _entry()
    entry["amount"] = None
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.sheets.append_rows") as append_mock, \
         patch("bot_handlers.parse_expense", return_value=[entry]):
        count, reply = bot_handlers.handle_message("奶茶十几块", update_id=555, today=date(2026, 8, 26))

    assert count == 0
    append_mock.assert_not_called()
    assert "没看懂金额" in reply


def test_empty_entries_returns_empty_reply_and_writes_nothing():
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.sheets.append_rows") as append_mock, \
         patch("bot_handlers.parse_expense", return_value=[]):
        count, reply = bot_handlers.handle_message("在吗", update_id=666, today=date(2026, 8, 26))

    assert count == 0
    assert reply == ""
    append_mock.assert_not_called()


def test_parse_error_gives_explicit_reply_not_silent():
    """静默失败是最危险的失败模式——解析出错必须给用户明确提示，不能什么都不回。"""
    with patch("bot_handlers.sheets.get_column", return_value=[]), \
         patch("bot_handlers.parse_expense", side_effect=bot_handlers.ParseError("boom")):
        count, reply = bot_handlers.handle_message("???", update_id=777, today=date(2026, 8, 26))

    assert count == 0
    assert reply != ""
    assert "❌" in reply


# ---------------------------------------------------------------- format_receipt

def test_format_receipt_shows_payment_method_when_present():
    row = bot_handlers._entry_to_row(_entry(payment_method="Chase debit"), 1, 0, date(2026, 8, 26))
    text = bot_handlers.format_receipt([row])
    assert "Chase debit" in text


def test_format_receipt_omits_payment_method_when_simply_absent():
    """用户就是没提支付方式（合法的空字符串，payment_method_confident 保持
    默认 True）——不该显示任何提示。"""
    row = bot_handlers._entry_to_row(_entry(payment_method="", payment_confident=True), 1, 0, date(2026, 8, 26))
    text = bot_handlers.format_receipt([row])
    assert "未知" not in text
    assert "⚠️ 支付方式" not in text


def test_format_receipt_shows_warning_when_payment_method_unrecognized():
    """软失败：payment_method 被 parser 回落成空字符串（payment_method_confident
    =False）——这跟"用户没提"是两回事，必须在回执里可见，不能悄悄显示成
    什么都没说过。"""
    row = bot_handlers._entry_to_row(_entry(payment_method="", payment_confident=False), 1, 0, date(2026, 8, 26))
    text = bot_handlers.format_receipt([row])
    assert "⚠️ 支付方式没识别出来" in text


def test_format_receipt_marks_low_confidence_category():
    row = bot_handlers._entry_to_row(_entry(confident=False), 1, 0, date(2026, 8, 26))
    text = bot_handlers.format_receipt([row])
    assert "⚠️" in text


def test_format_receipt_no_warning_when_confident():
    row = bot_handlers._entry_to_row(_entry(confident=True, payment_confident=True), 1, 0, date(2026, 8, 26))
    text = bot_handlers.format_receipt([row])
    assert "⚠️" not in text


def test_format_receipt_null_amount_shows_resend_prompt_and_no_undo():
    text = bot_handlers.format_receipt([{"_unparsed": True, "notes": "奶茶十几块"}])
    assert "没看懂金额" in text
    assert "/undo" not in text  # 什么都没记，不该出现 /undo


def test_format_receipt_multiple_entries_and_single_undo():
    rows = [
        bot_handlers._entry_to_row(_entry(amount=5, notes="咖啡5"), 1, 0, date(2026, 8, 26)),
        bot_handlers._entry_to_row(_entry(amount=6, notes="咖啡6"), 1, 1, date(2026, 8, 26)),
    ]
    text = bot_handlers.format_receipt(rows)
    assert text.count("/undo") == 1
    assert "咖啡5" in text and "咖啡6" in text


def test_format_receipt_today_label():
    row = bot_handlers._entry_to_row(_entry(date_="2026-08-26"), 1, 0, date(2026, 8, 26))
    assert "今天" in bot_handlers.format_receipt([row])


def test_format_receipt_yesterday_label():
    row = bot_handlers._entry_to_row(_entry(date_="2026-08-25"), 1, 0, date(2026, 8, 26))
    assert "昨天" in bot_handlers.format_receipt([row])


# ---------------------------------------------------------------- handle_undo

def test_handle_undo_no_telegram_rows():
    with patch("bot_handlers.sheets.get_all_records", return_value=[]):
        reply = bot_handlers.handle_undo(date(2026, 8, 26))
    assert "没有可撤销" in reply


def test_handle_undo_ignores_non_telegram_rows():
    rows = [_sheet_row("a", "手动记的", 10, "2026-08-26T09:00:00", "manual:x", source="manual")]
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row") as delete_mock:
        reply = bot_handlers.handle_undo(date(2026, 8, 26))
    delete_mock.assert_not_called()
    assert "没有可撤销" in reply


def test_handle_undo_deletes_all_rows_with_same_update_id():
    rows = [
        _sheet_row("a", "旧的", 10, "2026-08-25T10:00:00", "tg:900:0"),
        _sheet_row("b", "咖啡5", 5, "2026-08-26T09:00:00", "tg:901:0"),
        _sheet_row("c", "咖啡6", 6, "2026-08-26T09:00:00", "tg:901:1"),  # 同一条消息（同一个 update_id）
    ]
    deleted_ids = []
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row", side_effect=lambda sheet, id_: deleted_ids.append(id_)):
        reply = bot_handlers.handle_undo(date(2026, 8, 26))

    assert set(deleted_ids) == {"b", "c"}
    assert "a" not in deleted_ids
    assert "咖啡5" in reply and "咖啡6" in reply
    assert "2 笔" in reply


def test_handle_undo_does_not_conflate_different_messages_with_same_created_at():
    """这是这次要修的那个 bug 的回归测试：两条不同的消息（不同 update_id）
    如果凑巧同一秒发送、created_at 完全相同，旧版靠 created_at 分组会把
    它们错误地当成"同一条消息"一起撤销。改成按 external_id 解析出的
    update_id 分组之后，只有真正同一条消息（同一个 update_id）的行才会
    被一起删。"""
    same_ts = "2026-08-26T09:00:00"
    rows = [
        _sheet_row("a", "咖啡5", 5, same_ts, "tg:901:0"),   # 消息 A
        _sheet_row("b", "打车15", 15, same_ts, "tg:902:0"),  # 消息 B，同一秒发的，但是不同消息
    ]
    deleted_ids = []
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row", side_effect=lambda sheet, id_: deleted_ids.append(id_)):
        bot_handlers.handle_undo(date(2026, 8, 26))

    # 不管 max() 在 created_at 相等时选到哪一行，重点是只删了"那一条消息"
    # 的行，不会把 A（update_id=901）和 B（update_id=902）混在一起删掉。
    assert len(deleted_ids) == 1


def test_handle_undo_single_row():
    rows = [_sheet_row("a", "打车15", 15, "2026-08-26T09:00:00", "tg:950:0")]
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row") as delete_mock:
        reply = bot_handlers.handle_undo(date(2026, 8, 26))
    delete_mock.assert_called_once_with(FAKE_SHEET, "a")
    assert "打车15" in reply


def test_handle_undo_malformed_external_id_falls_back_to_single_row_not_crash():
    """external_id 格式不对（理论上不该发生，但不能因为解析不出来就崩掉或者
    什么都不做）——保底只撤销这一行。"""
    rows = [_sheet_row("a", "打车15", 15, "2026-08-26T09:00:00", "not-a-valid-external-id")]
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row") as delete_mock:
        reply = bot_handlers.handle_undo(date(2026, 8, 26))
    delete_mock.assert_called_once_with(FAKE_SHEET, "a")
    assert "打车15" in reply


def test_handle_undo_normalizes_unpadded_date_for_display():
    """反向断言：构造一行 date 是没补零的 'yyyy-M-d' 格式（见 CLAUDE.md 那条
    Sheets 渲染坑），handle_undo 显示的时候必须走 normalize_date() 统一成
    补零格式，不能直接拼接原始字符串。"""
    rows = [_sheet_row("x", "打车", 15, "2026-08-26T09:00:00", "tg:960:0", date_="2026-8-5")]
    with patch("bot_handlers.sheets.get_all_records", return_value=rows), \
         patch("bot_handlers.sheets.delete_row"):
        reply = bot_handlers.handle_undo(date(2026, 8, 26))
    assert "2026-08-05" in reply
    assert "2026-8-5" not in reply
