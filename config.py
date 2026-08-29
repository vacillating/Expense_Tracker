"""
config.py — categories, payment methods, fixed-expense templates.

Shared between app.py (Streamlit) and parser.py / bot_handlers.py (the
Telegram bot — no Streamlit dependency). Zero dependencies beyond the
stdlib, on purpose: importing app.py directly from the bot would execute
its top-level Streamlit calls and try to connect to Google Sheets outside
of a Streamlit run context.

Moved out of app.py 2026-08 — this was already a TODO item (CLAUDE.md's
"no hardcoded personal values scattered through the code" rule).
"""
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# 2026-08 时区 bug：Streamlit Cloud 跑在 UTC，app.py 原来直接用
# datetime.today() 当"今天"，晚上 8 点之后（EDT）记账，服务器那边已经
# 是第二天了——日期悄悄错一天，界面上显示的就是错的，完全没有报错。
#
# 时区从环境变量读，不硬编码：Gary 现在在亚特兰大，以后可能搬回国，
# 到时候改一个环境变量就行，不用改代码、不用重新部署两次。
#
# 故意不在模块加载时就把这个存成模块级常量（TIMEZONE = ZoneInfo(...)）：
# 那样 os.environ.get() 只在 import 的一瞬间读一次，之后哪怕环境变量
# 变了也不会生效（测试里 monkeypatch.setenv 也一样，不 reload 模块的话
# 读不到新值）。改成每次调用时现读，一次 ZoneInfo() 构造开销很小，换来
# 的是"改环境变量，结果立刻跟着变"，不用重启进程也不用 reload 模块。
DEFAULT_TIMEZONE_NAME = "America/New_York"


def _timezone_name() -> str:
    return os.environ.get("APP_TIMEZONE", DEFAULT_TIMEZONE_NAME)


def now_local() -> datetime:
    """当前时间，配置时区（APP_TIMEZONE，默认 America/New_York）下，带时区标识。"""
    return datetime.now(ZoneInfo(_timezone_name()))


def today_local() -> date:
    """当前时区下的"今天"。所有需要判断"今天几号"的地方都应该调这个——
    Quick Log 表单默认日期、Dashboard 的 is_current_month/days_passed、
    Telegram bot 传给 parse_expense() 的 today——不要各自
    datetime.today()/date.today()，那样会悄悄用服务器的时区（Streamlit
    Cloud 是 UTC），跟用户实际所在的时区不一致。全项目只有这一个地方
    决定"今天"是哪天，以后时区逻辑要改也只用改这一个函数。"""
    return now_local().date()


def now_utc_iso() -> str:
    """当前 UTC 时间，ISO 8601 格式，带时区标识（+00:00 后缀）。

    专给 created_at 这类审计时间戳用，跟 today_local() 是两回事，不要
    混为一谈：today_local() 答的是"用户视角的今天是哪天"（要跟着
    TIMEZONE 变），created_at 答的是"这行数据是什么时候写的"（存 UTC
    更规范——不管以后 TIMEZONE 怎么配置，历史上写下的审计时间戳的绝对
    时刻不会因此改变；需要按本地时区显示的话，展示层再用 TIMEZONE 转，
    不要在存的时候就转成本地时间，那样时区一变老数据就全错了）。

    注意：表里在这个改动之前写的 created_at 是不带时区标识的裸字符串
    （历史上 Streamlit Cloud 服务器本身就是 UTC，所以老数据数值上也是
    UTC，只是没有显式标注 +00:00）。这个函数只影响新写入的行，不会去
    改老数据——老数据格式不统一是已知的、暂时接受的状态。
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


CATEGORIES = [
    "房租 (Rent)",
    "餐饮 (Dine & Grocery)",
    "交通 (Transport)",
    "购物 (Shopping)",
    "娱乐 (Entertainment)",
    "其他 (Other)",
    "医疗 (Medical)",
    "旅行 (Travel)",  # 2026-08：机票/酒店/度假租车单独一类，不跟日常通勤混在"交通"里
]

# 支付方式选项
PAYMENT_METHODS = [
    "CMB credit",
    "Chase debit",
    "Cathay debit",
    "WeChat",
    "cash",
    "BoA credit",  # 2026-08：新开的 Bank of America 信用卡
    "BoA debit",   # 2026-08：新开的 Bank of America 借记卡
]

# payment_method -> 分析用的粗粒度分组，按"钱从哪来"分，不是按银行品牌分：
#   招行(父亲还款) —— 人民币，父亲垫付，需要跟他交代的那部分
#   美国卡         —— 从自己的美元余额出，不管具体是哪张卡
#   微信           —— 单独一组（目前只有 WeChat 一个值，先占位）
#   现金           —— 唯一的数据黑洞，花了什么完全没记录
#
# 只在这里（配置层）分组，不写进表里的任何一列——具体记的是哪张卡，
# 分组随时能在这一层合并，但反过来不行：如果表里直接记的就是"美国卡"，
# 以后想知道某一笔到底是 Chase 还是 BoA 刷的，这个信息已经永久丢了。
# 粒度是单向的，所以数据层永远存最细的，粗粒度只在展示/分析层现算。
PAYMENT_METHOD_GROUPS = {
    "CMB credit": "招行(父亲还款)",
    "Chase debit": "美国卡",
    "Cathay debit": "美国卡",
    "BoA credit": "美国卡",
    "BoA debit": "美国卡",
    "WeChat": "微信",
    "cash": "现金",
}
# 防呆：PAYMENT_METHODS 里任何新加的值，如果忘了在上面补分组，这里立刻报错，
# 跟 parser.py 里 payment_method 识别词那个防呆检查同款——新支付方式漏配置
# 是"看起来正常运行、分析结果悄悄不完整"的那类问题，模块加载时就该炸出来，
# 不该等到某天做汇总统计时才发现漏了一笔的分组。
_missing_groups = set(PAYMENT_METHODS) - set(PAYMENT_METHOD_GROUPS)
if _missing_groups:
    raise RuntimeError(f"config.py: PAYMENT_METHODS 里有值没配 PAYMENT_METHOD_GROUPS: {_missing_groups}")

# 定义固定支出模板
# 格式: (Category, Amount, Note) -> 不包含日期，因为日期是动态的
FIXED_TEMPLATES = [
    ("房租 (Rent)", 1050.0, "Fixed Rent"),
    ("其他 (Other)", 25.0, "US Mobile"),
    ("娱乐 (Entertainment)", 34.93, "Subscription"),
    ("医疗 (Medical)", 5.0, "降压药"),
]
