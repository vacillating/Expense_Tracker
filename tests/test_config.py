"""tests/test_config.py — 时区 bug 修复的回归测试。

背景（CLAUDE.md「Known issues」/ 2026-08 事故）：app.py 原来用
datetime.today()，在 Streamlit Cloud 的 UTC 服务器时间下，晚上 8 点后
(EDT) 记账，默认日期会悄悄变成第二天。这里测的是修复后的
config.today_local() / now_local() / now_utc_iso()。

没有引入 freezegun：用 monkeypatch 把 config 模块里的 `datetime` 名字
换成一个只重写了 now() 的子类，足够覆盖这里需要的场景，不用多引一个
依赖。
"""
import datetime as dt

import pytest
from zoneinfo import ZoneInfo

import config


def _patch_now(monkeypatch, utc_instant: dt.datetime):
    """让 config.now_local() 里的 datetime.now(tz) 表现得像当前 UTC 时刻
    就是 utc_instant（必须自带 tzinfo=UTC）。"""
    assert utc_instant.tzinfo is not None, "utc_instant 必须带时区，否则下面的 astimezone 语义不对"

    class FakeDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return utc_instant
            return utc_instant.astimezone(tz)

    monkeypatch.setattr(config, "datetime", FakeDatetime)


# --- 1. 复现事故本身：UTC 凌晨 1:31 应该被看成 EDT 视角的"昨天" ---

def test_today_local_utc_after_midnight_is_still_yesterday_in_edt(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    # UTC 2026-08-28 01:31 == EDT (UTC-4) 2026-08-27 21:31 —— 就是事故报告里
    # "昨天 21:31(EDT) 记的账，表里 date 却写成 2026-08-28" 那笔的真实场景。
    utc_now = dt.datetime(2026, 8, 28, 1, 31, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    result = config.today_local()

    assert result == dt.date(2026, 8, 27)


def test_now_local_carries_configured_tzinfo(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    utc_now = dt.datetime(2026, 8, 28, 1, 31, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    result = config.now_local()

    assert result.tzinfo is not None
    assert result.utcoffset() == dt.timedelta(hours=-4)  # EDT


# --- 2. 夏令时切换边界：EST <-> EDT 在 2026-03-08 02:00 本地时间切换 ---
# (美国东部 2026 年春季 DST 从 3 月 8 日 2:00 AM EST 跳到 3:00 AM EDT，
#  也就是 UTC 07:00 那一刻，偏移量从 -5 变成 -4。)

def test_dst_boundary_before_spring_forward_is_est(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    utc_now = dt.datetime(2026, 3, 8, 6, 59, tzinfo=dt.timezone.utc)  # 07:00 前一分钟
    _patch_now(monkeypatch, utc_now)

    result = config.now_local()

    assert result.utcoffset() == dt.timedelta(hours=-5)  # 还是 EST
    assert result.date() == dt.date(2026, 3, 8)
    assert result.hour == 1 and result.minute == 59


def test_dst_boundary_after_spring_forward_is_edt(monkeypatch):
    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    utc_now = dt.datetime(2026, 3, 8, 7, 1, tzinfo=dt.timezone.utc)  # 07:00 后一分钟
    _patch_now(monkeypatch, utc_now)

    result = config.now_local()

    assert result.utcoffset() == dt.timedelta(hours=-4)  # 已经跳到 EDT
    assert result.date() == dt.date(2026, 3, 8)
    assert result.hour == 3 and result.minute == 1


# --- 3. 时区必须来自配置（环境变量），不能是硬编码：改环境变量，结果跟着变 ---

def test_timezone_comes_from_env_var_not_hardcoded(monkeypatch):
    utc_now = dt.datetime(2026, 8, 28, 1, 31, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    monkeypatch.setenv("APP_TIMEZONE", "America/New_York")
    ny_today = config.today_local()

    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")
    shanghai_today = config.today_local()

    # 同一个 UTC 瞬间，纽约还在 8/27 晚上，上海已经是 8/28 早上——
    # 光看这一个瞬间的两个结果不一样，就证明 today_local() 真的在读
    # APP_TIMEZONE，而不是哪个时区被写死在代码/模块常量里。
    assert ny_today == dt.date(2026, 8, 27)
    assert shanghai_today == dt.date(2026, 8, 28)


def test_timezone_defaults_to_america_new_york_when_unset(monkeypatch):
    monkeypatch.delenv("APP_TIMEZONE", raising=False)
    utc_now = dt.datetime(2026, 8, 28, 1, 31, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    result = config.now_local()

    assert isinstance(result.tzinfo, ZoneInfo)
    assert result.tzinfo.key == "America/New_York"
    assert result.utcoffset() == dt.timedelta(hours=-4)


# --- 4. now_utc_iso()：审计时间戳，跟 today_local() 是两条不同的路 ---

def test_now_utc_iso_is_utc_regardless_of_app_timezone(monkeypatch):
    # created_at 存 UTC，不受 APP_TIMEZONE 影响——这是跟 today_local() 刻意
    # 不一样的地方，测一下防止以后有人"顺手"把两个函数改成共用一份时区逻辑。
    monkeypatch.setenv("APP_TIMEZONE", "Asia/Shanghai")
    utc_now = dt.datetime(2026, 8, 28, 1, 31, 42, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    result = config.now_utc_iso()

    assert result == "2026-08-28T01:31:42+00:00"


def test_now_utc_iso_format_is_sortable_string(monkeypatch):
    # bot_handlers.handle_undo() 靠字符串比较 created_at 找"最新"的那行，
    # 前提是同一批新格式的时间戳字符串序 == 时间序。这里锁一下格式本身。
    utc_now = dt.datetime(2026, 1, 5, 9, 0, 0, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now)

    earlier = config.now_utc_iso()

    utc_now_later = dt.datetime(2026, 1, 5, 9, 0, 1, tzinfo=dt.timezone.utc)
    _patch_now(monkeypatch, utc_now_later)
    later = config.now_utc_iso()

    assert earlier < later  # 字符串比较，跟真实时间先后一致
