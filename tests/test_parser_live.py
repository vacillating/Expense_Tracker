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


def test_boa_keyword():
    """2026-08：新开的 BoA 信用卡/借记卡，验证识别词能命中 PAYMENT_METHODS 里
    的某个 BoA 值。故意不锁死到底是 "BoA credit" 还是 "BoA debit"——
    "boa"/"bofa"/"美国银行" 这三个词本身不区分信用卡还是借记卡（config.py 里
    两个条目共享同一组识别词），这是真实存在的歧义，不是测试该断死的地方；
    这条测试守的是"至少能落到 BoA 系列而不是掉回空字符串或其他银行"。"""
    result = parse_expense("超市买菜80 boa", TODAY)
    assert len(result) == 1
    assert result[0]["payment_method"] in ("BoA credit", "BoA debit")


def test_currency_is_always_usd_regardless_of_wording():
    """2026-08 决定：Gary 记账时已经心算成美元了，currency 恒为 "USD"——
    "块""元""¥"这些词在他这里说的也是美元，不是人民币暗示。

    之前这里是 test_currency_cny_keyword，断言"奶茶28块" -> currency=="CNY"。
    那条测试测的是一个已经被否掉的行为，而且"块"本来在美式口语里就能指美元，
    这个歧义是语言里真实存在的——某几次跑挂、某几次又过，不是测试写得不好，
    是在测一件本身就没有唯一正确答案的事。现在 currency 由 _validate_entry()
    代码强制覆盖成 "USD"（见 parser.py），这条测试断的是那个兜底，不是在赌
    模型这次会不会碰巧读对。"""
    for text in ("奶茶28块", "打车¥15", "火锅60元", "咖啡5美元"):
        result = parse_expense(text, TODAY)
        assert len(result) == 1
        assert result[0]["currency"] == "USD"


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
