"""
schema.parse_row() 是唯一负责把 Google Sheets 返回的原始行（字符串/空值/不确定
的布尔表示）转成 app 能安全使用的类型化 dict 的地方。这里覆盖三类容易"静默算错
而不报错"的输入：旧的 6 列行（缺列）、空字符串数字列、以及各种形态的布尔值。
"""
import pytest

from schema import HEADERS, parse_row, row_from_dict, to_bool, to_float


def test_parse_row_old_six_column_row_fills_defaults():
    """迁移前的旧行只有 6 列，缺的 8 列必须补上默认值，而不是 KeyError。"""
    raw = {
        "id": "abc-123",
        "date": "2026-01-01",
        "type": "Expense",
        "category": "餐饮 (Dine & Grocery)",
        "amount": "12.5",
        "notes": "lunch",
    }
    out = parse_row(raw)

    assert set(out.keys()) == set(HEADERS)
    assert out["amount"] == 12.5
    assert out["currency"] == "USD"          # DEFAULTS
    assert out["merchant"] == ""             # DEFAULTS
    assert out["source"] == "manual"         # DEFAULTS
    assert out["is_recurring"] is False      # DEFAULTS
    # amount_usd 缺失时应该退回到 amount，而不是 0 或报错
    assert out["amount_usd"] == 12.5


def test_parse_row_empty_string_amount_does_not_crash():
    """Google Sheets 空单元格回来是 '' 不是 None，float('') 会直接抛异常。"""
    raw = {"id": "x", "date": "2026-01-01", "amount": "", "amount_usd": ""}
    out = parse_row(raw)

    assert out["amount"] == 0.0
    assert out["amount_usd"] == 0.0


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("TRUE", True),
        ("True", True),
        ("true", True),
        (1, True),
        ("1", True),
        ("是", True),
        ("", False),
        ("FALSE", False),
        ("False", False),
        (0, False),
        (False, False),
    ],
)
def test_is_recurring_handles_all_boolean_shapes(raw_value, expected):
    raw = {"is_recurring": raw_value}
    out = parse_row(raw)
    assert out["is_recurring"] is expected


def test_to_float_strips_currency_formatting_and_falls_back_on_junk():
    assert to_float("") == 0.0
    assert to_float(None) == 0.0
    assert to_float("$1,234.50") == 1234.50
    assert to_float("¥6.72") == 6.72
    assert to_float("not a number", default=9.0) == 9.0


def test_to_bool_only_recognises_known_true_values():
    assert to_bool("TRUE") is True
    assert to_bool("garbage") is False
    assert to_bool(None) is False


def test_row_from_dict_orders_by_headers_and_stringifies_bool():
    """row_from_dict 是唯一决定列顺序的地方——顺序一乱，写进表里的数据就全错位了。"""
    d = {"id": "x", "date": "2026-01-01", "amount": 5, "is_recurring": True}
    row = row_from_dict(d)

    assert len(row) == len(HEADERS)
    assert row[HEADERS.index("id")] == "x"
    assert row[HEADERS.index("amount")] == 5
    assert row[HEADERS.index("is_recurring")] == "TRUE"
    assert row[HEADERS.index("source")] == "manual"  # 未传时走 DEFAULTS
