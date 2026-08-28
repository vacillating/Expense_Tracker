"""
tests/test_parser_live.py — Group B: 真实调 LLM API，验证 parser.py 的
system prompt 在实际模型上有没有把硬约束落实。

全部标 @pytest.mark.live，默认跳过（见 tests/conftest.py 的
pytest_collection_modifyitems）。配好 LLM_BASE_URL / LLM_API_KEY /
LLM_MODEL 这三个环境变量之后跑：

    pytest tests/test_parser_live.py --run-live -v

断言故意放宽（LLM 输出有随机性，卡太死会变成噪音）——除了
test_no_arithmetic_on_split_bills 那条：AA 分账那条严格断言 amount==120，
这是硬约束 1（绝不做算术）的守门测试，不能放宽。
"""
from datetime import date, timedelta

import pytest

from parser import parse_expense

pytestmark = pytest.mark.live

TODAY = date(2026, 8, 26)


def test_simple_hotpot():
    result = parse_expense("火锅60", TODAY)
    assert len(result) == 1
    assert result[0]["amount"] == 60
    assert result[0]["category"] == "餐饮 (Dine & Grocery)"
    assert "火锅60" in result[0]["notes"]


def test_no_arithmetic_on_split_bills():
    """最重要的一条：硬约束 1 的守门测试。AA 不是除法指令，amount 必须是
    用户写的原始数字，绝不能被模型自作主张除以二。"""
    result = parse_expense("火锅120 AA", TODAY)
    assert len(result) == 1
    assert result[0]["amount"] == 120  # 不是 60


def test_comma_separated_is_two_entries():
    result = parse_expense("咖啡5, 咖啡6", TODAY)
    assert len(result) == 2
    amounts = {r["amount"] for r in result}
    assert amounts == {5, 6}


def test_no_separator_is_one_entry():
    result = parse_expense("咖啡56", TODAY)
    assert len(result) == 1
    assert result[0]["amount"] == 56


def test_relative_date_yesterday():
    result = parse_expense("昨天打车15", TODAY)
    assert len(result) == 1
    assert result[0]["date"] == (TODAY - timedelta(days=1)).isoformat()


def test_payment_method_wechat_keyword():
    result = parse_expense("买菜48 微信", TODAY)
    assert len(result) == 1
    assert result[0]["payment_method"] == "WeChat"


def test_payment_method_absent_is_empty_string():
    result = parse_expense("理发30", TODAY)
    assert len(result) == 1
    assert result[0]["payment_method"] == ""


def test_currency_cny_keyword():
    result = parse_expense("奶茶28块", TODAY)
    assert len(result) == 1
    assert result[0]["currency"] == "CNY"


def test_vague_amount_is_null_not_guessed():
    """硬约束 2 的守门测试：模糊金额必须是 null，不能编一个数字。"""
    result = parse_expense("奶茶十几块", TODAY)
    assert len(result) == 1
    assert result[0]["amount"] is None


def test_bare_number_low_confidence_category():
    result = parse_expense("60", TODAY)
    assert len(result) == 1
    assert result[0]["category_confident"] is False


def test_non_expense_message_returns_empty_list():
    result = parse_expense("在吗", TODAY)
    assert result == []
