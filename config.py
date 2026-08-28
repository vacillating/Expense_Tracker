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
]

# 定义固定支出模板
# 格式: (Category, Amount, Note) -> 不包含日期，因为日期是动态的
FIXED_TEMPLATES = [
    ("房租 (Rent)", 1050.0, "Fixed Rent"),
    ("其他 (Other)", 25.0, "US Mobile"),
    ("娱乐 (Entertainment)", 34.93, "Subscription"),
    ("医疗 (Medical)", 5.0, "降压药"),
]
