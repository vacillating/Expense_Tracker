"""
is_negative_settlement() 曾经是嵌在一次性内联脚本里、绑在 `_review=='TRUE'`
判断下面的逻辑——没被标 _review 的负数退款/代付回款会直接漏检。这里把它
钉死：不管 _review 是什么，负数的 Reimbursement/Refund 一律要被排除。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from backfill_ledger import is_negative_settlement  # noqa: E402


def test_negative_reimbursement_without_review_flag_is_excluded():
    """回归测试：这条如果红了，说明排除规则又被意外嵌套进某个条件分支里了。"""
    row = {"type": "Reimbursement", "amount": "-15.00", "_review": "FALSE"}
    assert is_negative_settlement(row) is True


def test_negative_refund_without_review_flag_is_excluded():
    row = {"type": "Refund", "amount": "-50.00", "_review": ""}
    assert is_negative_settlement(row) is True


def test_positive_reimbursement_is_not_excluded():
    row = {"type": "Reimbursement", "amount": "15.00", "_review": "FALSE"}
    assert is_negative_settlement(row) is False


def test_negative_expense_is_not_excluded():
    """只排除 Reimbursement/Refund；Expense 类型即使出现负数（比如折扣），
    不该被这条规则误伤——那是另一个问题。"""
    row = {"type": "Expense", "amount": "-5.00", "_review": "FALSE"}
    assert is_negative_settlement(row) is False


def test_missing_or_junk_amount_does_not_crash():
    assert is_negative_settlement({"type": "Refund", "amount": ""}) is False
    assert is_negative_settlement({"type": "Refund", "amount": "not a number"}) is False
