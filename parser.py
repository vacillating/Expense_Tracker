"""
parser.py — natural-language expense parsing for the Telegram bot.

Single entry point: parse_expense(text, today) -> list[dict].

No Streamlit, no pandas, no Google Sheets — this module only turns a string
into structured data. bot_handlers.py is the layer that knows what to do
with the result (build sheet rows, write them, format a receipt).

LLM provider is swappable: base_url / model / api_key all come from
environment variables, nothing is hardcoded to a specific vendor. All three
are required — missing any of them raises immediately (KeyError) rather
than silently falling back to some default. A fallback model name is
exactly the kind of thing that goes stale and points at the wrong vendor's
API without anyone noticing (DeepSeek retired the "deepseek-chat" alias
2026-07-24 in favor of deepseek-v4-flash/deepseek-v4-pro — a hardcoded
default here would already be dead and would produce a confusing error
pointed at the wrong thing).
  LLM_BASE_URL   e.g. https://api.deepseek.com/v1 (OpenAI-compatible)
  LLM_API_KEY
  LLM_MODEL      e.g. deepseek-v4-flash
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from openai import OpenAI

from config import CATEGORIES, PAYMENT_METHODS

# 商户名/关键词 -> PAYMENT_METHODS 里的规范值。用这个字典生成 prompt 里的
# 识别词提示，保证模型吐出来的字符串跟 config.py 里的值一字不差（大小写也要
# 对得上，不然写进表里会跟 SelectboxColumn 的 options 对不上）。
_PAYMENT_METHOD_KEYWORDS = {
    "WeChat": ["微信", "wechat"],
    "CMB credit": ["招行", "cmb"],
    "Chase debit": ["chase"],
    "Cathay debit": ["cathay", "国泰"],
    "cash": ["现金", "cash"],
    "BoA credit": ["boa", "bofa", "美国银行"],  # 2026-08：新开的 BoA 信用卡
    "BoA debit": ["boa", "bofa", "美国银行"],   # 2026-08：新开的 BoA 借记卡
}
# 防呆：PAYMENT_METHODS 里任何新加的值，如果忘了在上面补关键词，这里会立刻报错，
# 不会悄悄漏掉——比"prompt 里少一行提示、模型永远猜不出这个新支付方式"这种
# 静默问题要好发现得多。
_missing = set(PAYMENT_METHODS) - set(_PAYMENT_METHOD_KEYWORDS)
if _missing:
    raise RuntimeError(f"parser.py: PAYMENT_METHODS 里有值没配识别词: {_missing}")


class ParseError(Exception):
    """LLM 返回的内容不是合法 JSON、不是数组，或者条目形状不对。

    刻意不静默返回空列表——静默失败会让用户以为记上了，这是这个项目最危险
    的失败模式（'我记完账就走了，三天后发现根本没记进去'）。调用方（
    bot_handlers.py）接到这个异常应该回复用户"解析出错，请重试"这类明确提示，
    不能吞掉。
    """


_SYSTEM_PROMPT_TEMPLATE = """你是一个记账解析器。用户发来一句随手打的话，你把它转成结构化数据。

只返回一个 JSON 数组，不要任何前言、解释或 markdown 代码块。
即使只有一笔，也返回数组。无法解析出任何条目时返回空数组 []。

今天是 {today}。所有相对日期都相对这一天计算。

每个条目的字段：
  amount            数字。用户写的金额，原样。解析不出就填 null
  currency          恒定填 "USD"。用户记账时心里已经把金额换算成美元了，
                     不管原话里出现"块""元""¥"这类词，那些指的也是美元
                     口语说法，不是人民币——不要因为这些词把 currency 改
                     成别的值，永远输出 "USD"
  category          必须是下面列表里的一项，原样照抄包括括号
  merchant          花在什么上，尽量简短（如"火锅""打车"）
  notes             用户原话中对应这一笔的部分，一字不改
  payment_method    用户明确说了才填，否则填 ""
  date              YYYY-MM-DD。默认今天。除了"昨天""上周五""9月1号"这类
                     自然语言，也支持纯数字的 M.D / M/D / MM-DD 格式
                     （9.1、9/1、09-01 都是 9 月 1 日）——怎么跟金额区分见
                     下面硬约束 6，靠位置，不靠猜。
                     年份：纯数字日期不带年份时一律按【今年】算，不要因为
                     算出来的日期在未来就自作主张换成去年——用户确实会
                     提前记未来的支出（比如提前买好的机票）。真要指去年，
                     用户会明说"去年"，或者直接给完整年份（2025-12-25）。
  category_confident 布尔值。分类是明确推得出来还是靠猜

category 可选值（必须严格是这些字符串之一，一字不能改）：
{categories}

分类提示（不改变上面这份允许值列表，只是拿不准时的参考）：
  超市/杂货采购（含"中超"这类华人超市） → 餐饮 (Dine & Grocery)，
  不要归到 购物 (Shopping)——买的是食材，不是普通商品消费。

payment_method 的识别词：
{payment_method_hints}
  没提到 → ""

【硬约束，任何情况下不得违反】

1. 绝不做算术。不做除法、加减、汇率换算。
   用户打 "火锅120 AA"，amount 就是 120，不是 60。
   用户已经在付钱时算过了，你的工作是记录不是计算。

2. 绝不猜金额。"十几块""不到五十"这类模糊表达，amount 填 null。
   宁可让用户重打，也不要写一个编造的数字进账本。

3. notes 存原话，不要改写、不要清理、不要去掉"AA"之类的字眼。
   这是用户以后追溯和我们回测解析器的唯一依据。

4. 多笔的切分：用户用逗号或换行分开的才是多笔。
   "咖啡5, 咖啡6" 是两笔；"咖啡56" 是一笔 56 块。
   不要自作主张地拆分或合并。

5. 分类推不出来时，选"其他 (Other)"并把 category_confident 设为 false。
   不要追问，不要留空。

6. 一笔条目里如果出现两个数字，第一个是金额，第二个（如果长得像日期，
   即 M.D / M/D 这种形状）才可能是日期——靠位置消歧，不靠"哪个数字更
   像日期"去猜。
   "咖啡 9.1" 只有一个数字，9.1 就是金额（9.1 美元的咖啡），日期默认
   今天。"chipotle 11.63 9.1" 有两个数字，11.63 是金额，9.1 是日期
   （9 月 1 日）。这条规则专门是为了避免"两个数字都像金额也都像日期"
   时靠猜——位置固定了谁是谁，不会有歧义。
"""


def _build_system_prompt(today: date) -> str:
    categories_block = "\n".join(f"  {c}" for c in CATEGORIES)
    hint_lines = [
        f"  {'/'.join(_PAYMENT_METHOD_KEYWORDS[pm])} → {pm}" for pm in PAYMENT_METHODS
    ]
    return _SYSTEM_PROMPT_TEMPLATE.format(
        today=today.isoformat(),
        categories=categories_block,
        payment_method_hints="\n".join(hint_lines),
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.S)


def _strip_markdown_fence(text: str) -> str:
    """模型偶尔会把 JSON 包在 ```json ... ``` 或 ``` ... ``` 里，剥掉再 parse。"""
    text = text.strip()
    m = _FENCE_RE.match(text)
    return m.group(1).strip() if m else text


_REQUIRED_FIELDS = {
    "amount", "currency", "category", "merchant", "notes",
    "payment_method", "date", "category_confident",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_entry(entry: dict, raw: str) -> dict:
    """校验一条 entry，返回处理后的结果（可能被改过——见下面的分级校验）。

    分级校验，不是所有字段错了都一样严重：
      amount / date 不合法 -> 硬失败，抛 ParseError。账本里的数字/日期错了
      没法将就，宁可这一条整个失败也不能记错。
      category / payment_method 不合法 -> 软失败，回落到安全值。模型把
      "其他 (Other)" 打成 "其他(Other)"（少一个空格）这种小瑕疵，如果直接
      整条 ParseError，金额和描述明明都是对的却被一起丢掉，惩罚跟错误不
      成比例。回落不是静默——category 回落会强制 category_confident=False，
      payment_method 回落会标 payment_method_confident=False，这两个都会
      在 format_receipt() 的回执里带 ⚠️ 显示出来，用户看得见，不是"看起来
      记对了、其实记错了"。
    """
    if not isinstance(entry, dict):
        raise ParseError(f"条目不是对象: {entry!r}（原始返回: {raw!r}）")
    missing = _REQUIRED_FIELDS - entry.keys()
    if missing:
        raise ParseError(f"条目缺字段 {missing}: {entry!r}")

    # amount：硬失败。null 是合法的"没看懂金额"状态（硬约束 2），但非 null
    # 又不是数字（比如模型手滑吐了个字符串）就是真的错了，不能将就。
    amount = entry["amount"]
    if amount is not None and not isinstance(amount, (int, float)):
        raise ParseError(f"amount 不是数字也不是 null: {amount!r}（原始返回: {raw!r}）")

    # date：硬失败。格式不对会让下游 normalize_date() 处理出乱子，日期错了
    # 记账就全乱了。
    if not _DATE_RE.match(str(entry.get("date", ""))):
        raise ParseError(f"date 不是 YYYY-MM-DD 格式: {entry.get('date')!r}（原始返回: {raw!r}）")

    entry = dict(entry)  # 下面可能要改字段，不动调用方传进来的原对象

    # currency：恒为 USD，2026-08 决定（见 CLAUDE.md）。不只是 prompt 里说一下
    # 就完了——prompt 只能影响模型大概率的行为，不能保证每次都听话。这里在代码
    # 里强制覆盖，跟 category/payment_method 的兜底是同一个思路：不依赖 LLM
    # 100% 守约束，用代码兜底把"恒为 USD"这个不变量焊死。currency 列本身还留着
    # （给以后回国用），只是 parser 这条路径现在只会写 "USD"。
    entry["currency"] = "USD"

    if entry["category"] not in CATEGORIES:
        entry["category"] = "其他 (Other)"
        entry["category_confident"] = False

    entry["payment_method_confident"] = entry["payment_method"] in (*PAYMENT_METHODS, "")
    if not entry["payment_method_confident"]:
        entry["payment_method"] = ""

    return entry


def parse_expense(text: str, today: date) -> list[dict]:
    """调 LLM 把一句随手记的话解析成 0~N 条结构化记账条目。

    今天的日期由调用方传入，这个函数本身不取系统时间——这样测试才可复现。
    """
    client = OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )
    model = os.environ["LLM_MODEL"]

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _build_system_prompt(today)},
            {"role": "user", "content": text},
        ],
    )
    raw = response.choices[0].message.content or ""
    cleaned = _strip_markdown_fence(raw)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ParseError(f"LLM 返回的不是合法 JSON: {raw!r}") from e

    if not isinstance(parsed, list):
        raise ParseError(f"LLM 返回的 JSON 不是数组: {raw!r}")

    return [_validate_entry(entry, raw) for entry in parsed]
