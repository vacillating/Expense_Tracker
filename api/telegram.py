"""
api/telegram.py — Telegram webhook 入口（Vercel Function）。

职责只有"接住 HTTP 请求 + 安全校验 + 路由"，业务逻辑（解析、写表、幂等、
撤销）全部在 bot_handlers.py 里，这里不写。选 BaseHTTPRequestHandler 而不是
Flask/FastAPI：Vercel 的 /api 目录文件式路由原生支持这个类
（https://vercel.com/docs/functions/runtimes/python/api-directory），
不用多引入一个 web 框架依赖——这个函数的路由逻辑只有一条 POST，用不上
框架级的路由/中间件能力。

这个仓库根目录同时有 pyproject.toml（这个函数的依赖清单）和 requirements.txt
（Streamlit app.py 用的，含 streamlit/pandas/plotly）——刻意的布局，不是没
整理干净。Vercel 的 Python 安装器在两者都存在且没有 lockfile 时优先读
pyproject.toml，Streamlit Cloud 只认 requirements.txt，互不干扰，Root
Directory 留默认（仓库根目录）就行，共享模块也照常能 import。细节和依据
见 CLAUDE.md Deployment 一节——改动其中任何一份清单之前先看那一节，两份
共存这件事本身就是两个部署目标各读各的这套机制生效的前提。
"""
from __future__ import annotations

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler

import requests

from bot_handlers import handle_message, handle_undo
from config import today_local
from parser import ParseError
from sheets import RowNotFoundError, WriteVerificationError

log = logging.getLogger("telegram_webhook")
logging.basicConfig(level=logging.INFO)

HELP_TEXT = (
    "记账语法：金额 + 一个词，随手打就行。\n"
    "例：火锅60、打车15 chase、奶茶28\n"
    "多笔用逗号或换行分开：咖啡5, 咖啡6\n"
    "撤销最近一条消息记的账：/undo"
)

# LLM 挂掉/网络问题这类"没能处理"的情况，统一回这条——不区分 ParseError
# 具体是哪种，用户只需要知道"这条没记上，等会儿再发"。
_PARSE_FAILURE_MSG = "❌ 解析服务没响应，这条没记上，过会儿重发一下"


def _send_message(chat_id, text: str) -> None:
    """调 Telegram Bot API 的 sendMessage，把回执发回去。

    这是一次独立的出站 HTTP 调用，跟"Telegram 的 webhook POST 本身要回
    200"是两回事——回 200 只是告诉 Telegram"这条 update 我收到了，别重投
    了"，用户真正看到的回执文字是这次调用发出去的。

    故意不让这次调用的失败往上抛：账本读写（handle_message/handle_undo）
    已经在调用这个函数之前就完成了，发回执失败不代表记账失败，不该让整个
    请求因为"发消息这一步网络抖了一下"而变成 500（那样 Telegram 会重投，
    而重投不会让 sendMessage 突然成功，只是白白多打一次 API）。失败了就
    记日志，不重试、不抛出。
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        if not resp.ok:
            log.error("sendMessage 失败: HTTP %s %s", resp.status_code, resp.text)
    except requests.RequestException as e:
        log.error("sendMessage 抛异常: %s", e)


def _secret_matches(received: str | None) -> bool:
    """常数时间比较，防止时序攻击猜出 secret_token（== 会提前在第一个不
    匹配的字符处短路返回，时序上会泄露"猜对了几位"，hmac.compare_digest
    不会）。"""
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if received is None:
        return False
    return hmac.compare_digest(received, expected)


def _is_allowed_user(user_id) -> bool:
    allowed = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "")
    try:
        return int(user_id) == int(allowed)
    except (TypeError, ValueError):
        return False


def process_webhook(headers, raw_body: bytes) -> None:
    """核心逻辑：安全校验 -> 路由 -> 发回执。不碰 socket/HTTP 细节——只要求
    `headers` 支持 `.get(name)`（真实请求传 self.headers，测试传普通
    dict 就行），方便单测直接调用，不用伪造 BaseHTTPRequestHandler 的底层
    I/O（rfile/wfile/send_response 这些跟 socket 绑定的东西）。

    对 Telegram 的 webhook POST 本身要不要回 200，由调用方（do_POST）统一
    处理——这个函数只管"安全校验 -> 路由 -> 通过 _send_message 发回执"，
    不返回值，副作用是（可能会有的）一次 _send_message 调用和日志。
    """
    # a) secret_token 校验，放在最前面——校验不过的请求，后面任何解析
    # 都没必要做。校验失败/校验通过但格式不对，一律"回 200 静默丢弃"：
    # 回非 200 只会让 Telegram（如果这条真是 Telegram 发的）重投递，
    # 伪造请求重投多少次都还是伪造的，纯粹浪费函数调用次数。但要记日志
    # ——这是我们判断"有没有人在扫这个地址"的唯一依据。这里说的"回 200"
    # 是 do_POST 对 Telegram 的 HTTP 响应，这个函数只负责在该丢弃的时候
    # 提前 return，不做任何 _send_message。
    secret = headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not _secret_matches(secret):
        log.warning("secret_token 校验失败")
        return

    try:
        update = json.loads(raw_body)
    except json.JSONDecodeError:
        log.warning("请求体不是合法 JSON，丢弃")
        return

    # c) 非 message 类型的 update（edited_message/channel_post/
    # callback_query 等）直接忽略。这一步必须先于 b)：b) 要读
    # update["message"]["from"]["id"]，如果这条 update 根本没有
    # "message" 这个 key（比如 edited_message/callback_query），
    # 直接取值会 KeyError——所以判断"是不是 message"必须先做。
    message = update.get("message")
    if not isinstance(message, dict):
        log.info("非 message 类型的 update，忽略: keys=%s", list(update.keys()))
        return

    # b) 用户白名单校验
    from_user = message.get("from") or {}
    if not _is_allowed_user(from_user.get("id")):
        log.warning("非白名单用户尝试使用: user_id=%s", from_user.get("id"))
        return

    update_id = update.get("update_id")
    chat_id = message.get("chat", {}).get("id")
    today = today_local()

    try:
        reply_text = _route(message, update_id, today)
    except ParseError:
        # parse_expense 本身的校验失败（LLM 吐出的不是合法 JSON/不是
        # 数组/条目形状不对）。bot_handlers.handle_message() 内部其实
        # 已经捕获了这一个具体异常、返回"没解析明白"的提示——这里再 catch
        # 一次是防御性的：万一以后 handle_message 的实现变了，或者
        # ParseError 从别的路径漏出来，也不能让它一路冲到这里变成
        # 未处理异常、返回 500（Telegram 会重投，且重投不会让 LLM
        # 突然解析成功）。
        log.error("ParseError: update_id=%s", update_id)
        reply_text = _PARSE_FAILURE_MSG
    except WriteVerificationError as e:
        # 写入落点校验没通过——见 sheets.py：可能真的没写上，也可能写上
        # 了但落点不对。这种不确定性必须原样传达给用户，不能笼统说
        # "出错了"，也不能自作主张说"写成功了"或"重发一次"（重发有二次
        # 写入/覆盖的风险，sheets.py 自己都不敢重试）。
        log.error("WriteVerificationError: update_id=%s, %s", update_id, e)
        reply_text = "⚠️ 写入校验没通过，不确定这条记上了没有——先去表里核对，别直接重发。"
    except RowNotFoundError as e:
        # 目前只有 /undo 路径会触发（按 id 删行时找不到对应行了，
        # 大概率是并发场景下被别的操作先删掉了）。
        log.error("RowNotFoundError: update_id=%s, %s", update_id, e)
        reply_text = "↩️ 撤销失败：要删的那一行在表里已经找不到了（可能已经被撤过一次）。"
    except Exception as e:
        # 最后一道兜底——上面三个是已知的、有具体应对文案的失败模式；
        # 这里接住任何没预料到的异常，同样原则：响亮地失败，不能让请求
        # 悄悄变成一个没有任何用户可见反馈的 500。
        log.exception("未预期的异常: update_id=%s", update_id)
        reply_text = "❌ 出错了，这条可能没记上，麻烦稍后去表里确认一下。"

    if reply_text and chat_id is not None:
        _send_message(chat_id, reply_text)


def _route(message: dict, update_id, today) -> str:
    text = message.get("text")

    if text is None:
        # 非文本消息：图片、语音、贴纸、文件……message 里没有 "text" 字段。
        return "暂时只支持文字"

    if text.startswith("/undo"):
        return handle_undo(today)

    if text in ("/start", "/help"):
        return HELP_TEXT

    _, reply = handle_message(text, update_id, today)
    return reply


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length) if length else b""
        process_webhook(self.headers, raw_body)
        self._reply_200_empty()

    def _reply_200_empty(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, format, *args):
        # 用上面配置好的 logging 模块，不用 BaseHTTPRequestHandler 默认的
        # stderr 直写——统一走一套日志，也避免每个请求都打一行访问日志噪音。
        pass
