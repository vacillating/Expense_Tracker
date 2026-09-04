"""
tests/test_telegram_webhook.py — Group A: mock 掉 bot_handlers.handle_message/
handle_undo 和 requests.post，只测 api/telegram.py 自己的逻辑（安全校验、
路由、异常 -> 回执文案的映射）。不碰真实 Sheets、不调真实 LLM、不发真实
Telegram 消息，进 CI 必须全绿。

测的是 process_webhook()，不是 handler.do_POST()——process_webhook 是纯
逻辑核心，不用伪造 BaseHTTPRequestHandler 的 socket 层（rfile/wfile 那些），
见 api/telegram.py 里的说明。
"""
import json
from unittest.mock import patch

import pytest

import api.telegram as webhook
from parser import ParseError
from sheets import RowNotFoundError, WriteVerificationError

SECRET = "test-secret-token"
ALLOWED_USER_ID = 12345
CHAT_ID = 99999


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", str(ALLOWED_USER_ID))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")


@pytest.fixture(autouse=True)
def _mock_send(monkeypatch):
    """所有测试都不应该真的发 HTTP 请求出去——统一 mock 掉 requests.post，
    记录调用参数，供断言用。"""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json})

        class _Resp:
            ok = True
            status_code = 200
            text = ""

        return _Resp()

    monkeypatch.setattr(webhook.requests, "post", fake_post)
    return calls


def _headers(secret=SECRET):
    return {"X-Telegram-Bot-Api-Secret-Token": secret}


def _body(update: dict) -> bytes:
    return json.dumps(update).encode()


def _message_update(text=None, user_id=ALLOWED_USER_ID, update_id=1, chat_id=CHAT_ID, **extra_message_fields):
    message = {"from": {"id": user_id}, "chat": {"id": chat_id}, **extra_message_fields}
    if text is not None:
        message["text"] = text
    return {"update_id": update_id, "message": message}


def _sent_texts(calls):
    return [c["json"]["text"] for c in calls]


# ---------- a) secret_token 校验 ----------

def test_wrong_secret_token_is_silently_dropped(_mock_send):
    webhook.process_webhook(_headers(secret="wrong"), _body(_message_update(text="火锅60")))
    assert _mock_send == []  # 没调用任何下游函数——包括没发任何回执


def test_missing_secret_header_is_silently_dropped(_mock_send):
    webhook.process_webhook({}, _body(_message_update(text="火锅60")))
    assert _mock_send == []


# ---------- b) 用户白名单校验 ----------

def test_user_not_in_allowlist_is_silently_dropped(_mock_send):
    webhook.process_webhook(_headers(), _body(_message_update(text="火锅60", user_id=999)))
    assert _mock_send == []


# ---------- c) 非 message 类型的 update ----------

@pytest.mark.parametrize("update", [
    {"update_id": 1, "edited_message": {"text": "改过的消息"}},
    {"update_id": 1, "channel_post": {"text": "频道消息"}},
    {"update_id": 1, "callback_query": {"id": "abc"}},
])
def test_non_message_update_is_ignored(update, _mock_send):
    webhook.process_webhook(_headers(), _body(update))
    assert _mock_send == []


def test_malformed_json_body_is_dropped(_mock_send):
    webhook.process_webhook(_headers(), b"not json")
    assert _mock_send == []


# ---------- 路由 ----------

def test_undo_command_routes_to_handle_undo(_mock_send):
    with patch.object(webhook, "handle_undo", return_value="↩️ 已撤销：...") as mock_undo:
        webhook.process_webhook(_headers(), _body(_message_update(text="/undo")))
    mock_undo.assert_called_once()
    assert _sent_texts(_mock_send) == ["↩️ 已撤销：..."]


def test_start_and_help_return_help_text(_mock_send):
    for cmd in ("/start", "/help"):
        _mock_send.clear()
        webhook.process_webhook(_headers(), _body(_message_update(text=cmd)))
        assert _sent_texts(_mock_send) == [webhook.HELP_TEXT]


def test_plain_text_routes_to_handle_message(_mock_send):
    with patch.object(webhook, "handle_message", return_value=(1, "✅ $60.00 · 餐饮")) as mock_handle:
        webhook.process_webhook(_headers(), _body(_message_update(text="火锅60", update_id=42)))
    args, kwargs = mock_handle.call_args
    assert args[0] == "火锅60"
    assert args[1] == 42  # update_id，不是 message_id
    assert _sent_texts(_mock_send) == ["✅ $60.00 · 餐饮"]


def test_handle_message_empty_reply_sends_nothing(_mock_send):
    """重复投递（幂等命中）或没解析出任何条目时，handle_message 返回
    (0, "")——这种情况不该发任何 Telegram 消息。"""
    with patch.object(webhook, "handle_message", return_value=(0, "")):
        webhook.process_webhook(_headers(), _body(_message_update(text="在吗")))
    assert _mock_send == []


def test_non_text_message_replies_with_text_only_notice(_mock_send):
    update = _message_update(photo=[{"file_id": "abc"}])  # 没有 text 字段
    webhook.process_webhook(_headers(), _body(update))
    assert _sent_texts(_mock_send) == ["暂时只支持文字"]


# ---------- 【重点】LLM/写入失败时必须回明确提示，不能静默 ----------

def test_parse_error_replies_with_clear_failure_message(_mock_send):
    with patch.object(webhook, "handle_message", side_effect=ParseError("LLM 挂了")):
        webhook.process_webhook(_headers(), _body(_message_update(text="火锅60")))
    assert _sent_texts(_mock_send) == [webhook._PARSE_FAILURE_MSG]
    assert "没记上" in webhook._PARSE_FAILURE_MSG


def test_write_verification_error_replies_with_clear_failure_message(_mock_send):
    with patch.object(webhook, "handle_message", side_effect=WriteVerificationError("落点异常")):
        webhook.process_webhook(_headers(), _body(_message_update(text="火锅60")))
    texts = _sent_texts(_mock_send)
    assert len(texts) == 1
    assert "写入校验" in texts[0]
    assert "出错了" not in texts[0]  # 不能是笼统的"出错了"


def test_row_not_found_error_replies_with_clear_failure_message(_mock_send):
    with patch.object(webhook, "handle_undo", side_effect=RowNotFoundError("id 找不到")):
        webhook.process_webhook(_headers(), _body(_message_update(text="/undo")))
    texts = _sent_texts(_mock_send)
    assert len(texts) == 1
    assert "撤销失败" in texts[0]
    assert "出错了" not in texts[0]


def test_unexpected_exception_still_replies_not_silent(_mock_send):
    """任何没预料到的异常都不能让请求变成一个用户完全看不到反馈的失败——
    这是"失败必须响亮"这条原则的兜底测试。"""
    with patch.object(webhook, "handle_message", side_effect=RuntimeError("没想到的 bug")):
        webhook.process_webhook(_headers(), _body(_message_update(text="火锅60")))
    texts = _sent_texts(_mock_send)
    assert len(texts) == 1
    assert texts[0]  # 非空，用户能看到点什么，不是完全沉默
