"""
scripts/set_webhook.py — Telegram webhook 的一次性运维脚本，不进 Vercel
部署包（vercel.json 的 excludeFiles 已经排掉整个 scripts/）。

三个子命令：
  set     注册 webhook 地址，同时传 secret_token
              python scripts/set_webhook.py set --url https://xxx.vercel.app/api/telegram
  info    查当前 webhook 状态——排查问题时会反复用，尤其看
          last_error_message（Telegram 最近一次投递失败的原因）和
          pending_update_count（堆积了多少条还没投出去的更新）
              python scripts/set_webhook.py info
  delete  取消 webhook，用于回滚
              python scripts/set_webhook.py delete

Token 和 secret 只从环境变量读（TELEGRAM_BOT_TOKEN / TELEGRAM_WEBHOOK_SECRET），
不接受命令行参数传——命令行参数会被 shell 记进历史文件（~/.zsh_history 等），
明文密钥留在那里是不必要的暴露面。webhook 地址本身不是密钥，用 --url 传没问题。

依赖 requests——多半已经通过 gspread 的依赖链（google-auth-oauthlib ->
requests-oauthlib -> requests）装在本地环境里了；如果没有，`pip install requests`。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests

API_BASE = "https://api.telegram.org/bot{token}"


def _token() -> str:
    try:
        return os.environ["TELEGRAM_BOT_TOKEN"]
    except KeyError:
        sys.exit("环境变量 TELEGRAM_BOT_TOKEN 没设置。")


def _secret() -> str:
    try:
        return os.environ["TELEGRAM_WEBHOOK_SECRET"]
    except KeyError:
        sys.exit("环境变量 TELEGRAM_WEBHOOK_SECRET 没设置。")


def cmd_set(args: argparse.Namespace) -> None:
    url = f"{API_BASE.format(token=_token())}/setWebhook"
    resp = requests.post(url, json={"url": args.url, "secret_token": _secret()}, timeout=10)
    _print_result(resp)


def cmd_info(_: argparse.Namespace) -> None:
    url = f"{API_BASE.format(token=_token())}/getWebhookInfo"
    resp = requests.get(url, timeout=10)
    _print_result(resp)


def cmd_delete(_: argparse.Namespace) -> None:
    url = f"{API_BASE.format(token=_token())}/deleteWebhook"
    resp = requests.post(url, timeout=10)
    _print_result(resp)


def _print_result(resp: requests.Response) -> None:
    try:
        body = resp.json()
    except ValueError:
        print(f"HTTP {resp.status_code}，响应不是合法 JSON: {resp.text!r}")
        return
    print(json.dumps(body, indent=2, ensure_ascii=False))
    if not body.get("ok", False):
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="注册 webhook 地址")
    p_set.add_argument("--url", required=True, help="完整的 webhook URL，例如 https://xxx.vercel.app/api/telegram")
    p_set.set_defaults(func=cmd_set)

    p_info = sub.add_parser("info", help="查当前 webhook 状态")
    p_info.set_defaults(func=cmd_info)

    p_delete = sub.add_parser("delete", help="取消 webhook")
    p_delete.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
