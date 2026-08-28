"""
tests/test_parser.py — Group A: mock 掉 LLM 的返回，测下游逻辑（JSON 解析、
容错、校验）。不调真实 API，进 CI 必须全绿。

真实调 LLM 的语义测试（"火锅120 AA" -> amount 必须是 120 这类）在
tests/test_parser_live.py，标了 @pytest.mark.live，默认跳过。
"""
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import parser
from parser import ParseError, parse_expense


def _fake_response(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _mock_client(content: str) -> MagicMock:
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response(content)
    return client


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")


VALID_ENTRY = {
    "amount": 60, "currency": "USD", "category": "餐饮 (Dine & Grocery)",
    "merchant": "火锅", "notes": "火锅60", "payment_method": "",
    "date": "2026-08-26", "category_confident": True,
}


def test_parses_valid_json_array():
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([VALID_ENTRY]))):
        result = parse_expense("火锅60", date(2026, 8, 26))
    assert result == [dict(VALID_ENTRY, payment_method_confident=True)]


def test_strips_markdown_code_fence_with_json_tag():
    wrapped = "```json\n" + json.dumps([VALID_ENTRY]) + "\n```"
    with patch("parser.OpenAI", return_value=_mock_client(wrapped)):
        result = parse_expense("火锅60", date(2026, 8, 26))
    assert result == [dict(VALID_ENTRY, payment_method_confident=True)]


def test_strips_markdown_code_fence_without_json_tag():
    wrapped = "```\n" + json.dumps([VALID_ENTRY]) + "\n```"
    with patch("parser.OpenAI", return_value=_mock_client(wrapped)):
        result = parse_expense("火锅60", date(2026, 8, 26))
    assert result == [dict(VALID_ENTRY, payment_method_confident=True)]


def test_empty_array_is_valid_not_an_error():
    with patch("parser.OpenAI", return_value=_mock_client("[]")):
        result = parse_expense("在吗", date(2026, 8, 26))
    assert result == []


def test_invalid_json_raises_parse_error_not_silent_empty_list():
    with patch("parser.OpenAI", return_value=_mock_client("这不是 JSON")):
        with pytest.raises(ParseError):
            parse_expense("火锅60", date(2026, 8, 26))


def test_non_array_json_raises_parse_error():
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps({"amount": 60}))):
        with pytest.raises(ParseError):
            parse_expense("火锅60", date(2026, 8, 26))


def test_unknown_category_soft_fails_to_other_with_low_confidence():
    """软失败：分类不合法不该把整条账（金额、描述都是对的）一起丢掉，
    回落到"其他 (Other)"，靠 category_confident=False 让这个回落在回执里
    可见（不是静默）。"""
    bad = dict(VALID_ENTRY, category="其他(Other)", category_confident=True)  # 少一个空格，非法值
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([bad]))):
        result = parse_expense("火锅60", date(2026, 8, 26))
    assert result[0]["category"] == "其他 (Other)"
    assert result[0]["category_confident"] is False
    assert result[0]["amount"] == 60  # 其他字段不受影响


def test_unknown_payment_method_soft_fails_to_empty_string():
    bad = dict(VALID_ENTRY, payment_method="支付宝")  # 不在 config.PAYMENT_METHODS 里
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([bad]))):
        result = parse_expense("火锅60", date(2026, 8, 26))
    assert result[0]["payment_method"] == ""
    assert result[0]["payment_method_confident"] is False
    assert result[0]["category_confident"] is True  # payment_method 的问题不该连累 category


def test_valid_payment_method_is_confident():
    ok = dict(VALID_ENTRY, payment_method="Chase debit")
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([ok]))):
        result = parse_expense("火锅60 chase", date(2026, 8, 26))
    assert result[0]["payment_method_confident"] is True


def test_non_numeric_amount_hard_fails():
    """硬失败：amount 不是数字也不是 null，账本数字会直接错，不能将就。"""
    bad = dict(VALID_ENTRY, amount="sixty")
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([bad]))):
        with pytest.raises(ParseError):
            parse_expense("火锅60", date(2026, 8, 26))


def test_malformed_date_hard_fails():
    """硬失败：日期格式不对会让下游 normalize_date() 处理出乱子。"""
    bad = dict(VALID_ENTRY, date="Aug 26 2026")
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([bad]))):
        with pytest.raises(ParseError):
            parse_expense("火锅60", date(2026, 8, 26))


def test_missing_field_raises_parse_error():
    incomplete = {"amount": 60}  # 缺 category/notes/... 一大堆
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([incomplete]))):
        with pytest.raises(ParseError):
            parse_expense("火锅60", date(2026, 8, 26))


def test_null_amount_entry_passes_validation():
    """amount=null 是合法的（表示"没看懂金额"），不该在 parser 这层报错——
    是 bot_handlers 那层决定怎么处理 null amount。"""
    entry = dict(VALID_ENTRY, amount=None)
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([entry]))):
        result = parse_expense("奶茶十几块", date(2026, 8, 26))
    assert result[0]["amount"] is None


def test_system_prompt_includes_today():
    prompt = parser._build_system_prompt(date(2026, 8, 26))
    assert "2026-08-26" in prompt


def test_system_prompt_includes_all_categories_from_config():
    prompt = parser._build_system_prompt(date(2026, 8, 26))
    for c in parser.CATEGORIES:
        assert c in prompt


def test_system_prompt_includes_all_payment_methods_from_config():
    prompt = parser._build_system_prompt(date(2026, 8, 26))
    for pm in parser.PAYMENT_METHODS:
        assert pm in prompt


@pytest.mark.parametrize("missing_var", ["LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"])
def test_missing_required_env_var_raises_not_silently_defaults(monkeypatch, missing_var):
    """三个环境变量都是必填的，缺任何一个都要立刻炸，不能悄悄用某个默认值
    顶上——一个过期的默认 model 名字只会指向错误的地方，比明确报错更难查。"""
    monkeypatch.delenv(missing_var, raising=False)
    with patch("parser.OpenAI", return_value=_mock_client(json.dumps([VALID_ENTRY]))):
        with pytest.raises(KeyError):
            parse_expense("火锅60", date(2026, 8, 26))
