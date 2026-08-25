"""
One-off backfill script: consolidate 2026-05-01..2026-08-23 spending
from Chase checking, Cathay (x2), WeChat Pay and CMB into the tracker schema.

This is deliberately a throwaway script, not a reusable importer.
Its job is to (a) produce a loadable CSV and (b) expose where the schema is wrong.
"""
import csv, hashlib, re, uuid, datetime as dt
from collections import defaultdict
import openpyxl

UP = "/mnt/user-data/uploads/"
OUT = "/home/claude/backfill/"

# ---- CONFIG (Gary must confirm these) --------------------------------------
WINDOW_START = dt.date(2026, 5, 1)
WINDOW_END = dt.date(2026, 8, 23)
CNY_PER_USD = 6.72          # from Project Knowledge; single fixed rate for the whole window
CREATED_AT = "2026-08-23T00:00:00"

CATEGORIES = {
    "rent": "房租 (Rent)",
    "food": "餐饮 (Dine & Grocery)",
    "transport": "交通 (Transport)",
    "shop": "购物 (Shopping)",
    "fun": "娱乐 (Entertainment)",
    "other": "其他 (Other)",
    "medical": "医疗 (Medical)",
}

# keyword -> category key. Order matters: first match wins.
RULES = [
    # 2026-08: YSI*/CLAIRMONT RESERVE 拿掉了——验证时发现这批数据里两次出现的
    # 其实是入住申请费/杂费，不是月度房租，金额也对不上真实房租。GRADGUARD/RENTERS
    # （租客保险）留着，跟房租本身还算同一类居住成本。拿掉后 YSI*/CLAIRMONT RESERVE
    # 会落到默认的 "other" + 需要人工复核，不会再被自动当成房租，这是有意的——
    # 下次再出现这个商户，应该让人看一眼再定，不该自动归类。
    (r"GRADGUARD|RENTERS", "rent"),
    (r"MTA\*|UBER|LYFT|SHELL|SPEEDWAY|PILOT|EXXON|CHEVRON|BP#|ONE9|MARATHON|CIRCLE K|QT \d|WAWA|SUNOCO|PARKING|MARTA|AMTRAK|GREYHOUND|TOLL|FUEL|COACH USA|METRO WASHINGTON|PATH TAPP|CITY OF MADISON", "transport"),
    # 2026-08: 从 "transport" 改成 "travel"——机票/酒店/Airbnb 是旅行支出，
    # 不是日常通勤，混在"交通"里语义不对，也没法单独看旅游花了多少。
    (r"AMERICAN AIR|SOUTHWES|DELTA|UNITED|FRONTIER|SPIRIT|EXPEDIA|AGODA|BOOKING|HOTEL|SHERATON|MARRIOTT|HILTON|HOSTEL|AIRBNB|去哪儿|边疆航空", "travel"),
    # 2026-08: 租车公司名字本身分不出"这次租车是旅游还是搬家/杂事"——这个信息
    # 只有 Gary 自己知道，脚本猜不出来。默认落 "transport"（保守，不主动归旅行），
    # 真正的旅游租车靠人工在导入时或者用 app 里的编辑功能改成 "旅行 (Travel)"。
    (r"BUDGET|AVIS|SIXT|NATIONAL CAR|NATIONAL RENTAL", "transport"),
    (r"STARBUCKS|DOORDASH|DD \*|GRUBHUB|UBER EATS|CHIPOTLE|CHICK FIL|CULVERS|MCDONALD|PANDA|SUBWAY|DUNKIN|KROGER|PUBLIX|WALMART|WM SUPERCENTER|ALDI|COSTCO|TRADER|H MART|HMART|99 RANCH|ENSON|WEEE|HUNGRYPANDA|HEYTEA|CAFE|COFFEE|RESTAURANT|KITCHEN|BUFFET|NOODLE|HOTPOT|POCHA|TAVERN|GRILL|PIZZA|SUSHI|KATSU|RAMEN|BAKERY|MARKET|MKT|GROCER|FOOD|TST\*|TST |MALA|LA TANG|QAHWAH|SOHAO|AMRIT|MLBB|HAN GANG|SEOUL|PICCOLA|LEBANESE|FAMOUS DAVE|SWEET SAINT|AUTHENTIC HAND|WEI AUTHENTIC|TEN SECOND|OCEAN BUFFET|SPRINGHILL MKT|UNADILLA|WAL-MART|WHOLEFDS|ALLIANCE MART|7-ELEVEN|BURGER KING|TEXAS ROADHOUSE|NOM NOM|WHAT THE PHO|EAST GARDEN|SAKURA|KILWINS|WANDOS|NORAS|BIRD ON THE ROOF|BAI WEI|YOUSEF INC|SCHUMACHER GINSENG", "food"),
    (r"WALGREENS|CVS|PHARMACY|CLINIC|HOSPITAL|DENTAL|MEDICAL|OPTOM|降压药|UNIVERSITY HEALTH SERV|WORLDTRIPS", "medical"),
    (r"MUSEU|THEATRE|THEATER|CINEMA|AMC |MOVIE|CONCERT|TICKET|ZOO|AQUARIUM|PARK ENTR|RECWELL|ABES BUGGY|DREAMSTUDIOS|腾讯体育|红包|TOP OF THE ROCK|SMITH STORE AIR-SPACE|XCAL SHOOTING|MONTAUK LT HOUSE|HAPPY WORLD SPA|FUJI HEALTH SPA|NBA STORE", "fun"),
    (r"AMAZON|AMZN|TARGET|BEST BUY|APPLE|ICLOUD|IKEA|OFFICE FURNITURE|BOOK ST|TESOLIFE|淘宝|京东|拼多多|SUPERCENTER|MAX CREEK", "shop"),
    (r"SPOTIFY|CLAUDE\.AI|ICLOUD|NETFLIX|OPENAI|CHATGPT", "other"),
    (r"AOM\.ORG|MEMBERSHIP|SUBSCRIPTION|PIRATE SHIP|USPS|FEE|SVC CHG|HOLIDAY INN", "other"),
]


def categorise(merchant):
    m = merchant.upper()
    for pat, key in RULES:
        if re.search(pat, m):
            return CATEGORIES[key], False
    return CATEGORIES["other"], True   # (category, needs_review)


# 2026-08: 原来这里把 GRADGUARD 和 YSI*/CLAIRMONT RESERVE 也并列判定成 recurring，
# 结果验证时发现两个都错了——GRADGUARD 是一次性年费（一年一次不该算 recurring，
# 会让 projection 把它当成每月固定支出，日均反而被低估）；YSI*/CLAIRMONT RESERVE
# 在这批数据里两次出现的其实是入住时的申请费/杂费，不是月度房租本身，金额也对不上
# 真实房租（$1050）。两个都从这条正则里去掉了，不是同一类东西，不该用一条正则
# 并列判定。真正按月扣费、金额稳定重复出现的才留在这里。
RECURRING = re.compile(r"SPOTIFY|CLAUDE\.AI|ICLOUD|US MOBILE|腾讯体育", re.I)


def eid(source, *parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return f"{source}:{h}"


rows = []       # confirmed expenses
questions = defaultdict(list)   # bucket -> list of dicts
skipped = defaultdict(lambda: [0, 0.0])


def add(date, category, amount, currency, merchant, notes, pm, source, ext,
        typ="Expense", needs_review=False):
    amount = round(float(amount), 2)
    usd = amount if currency == "USD" else round(amount / CNY_PER_USD, 2)
    rows.append(dict(
        id=str(uuid.uuid4()), date=date.isoformat(), type=typ, category=category,
        amount=f"{amount:.2f}", currency=currency, amount_usd=f"{usd:.2f}",
        merchant=merchant, notes=notes, payment_method=pm, source=source,
        external_id=ext,
        is_recurring="TRUE" if RECURRING.search(merchant) else "FALSE",
        created_at=CREATED_AT,
        _review="TRUE" if needs_review else "FALSE",
    ))


def in_window(d):
    return WINDOW_START <= d <= WINDOW_END


# =============================================================== CHASE ======
def clean_chase(desc):
    s = re.sub(r"\s+\d{2}/\d{2}\s*$", "", desc.strip())      # trailing txn date
    s = re.sub(r"^(TST\*|SQ \*|DD \*|PY \*|IN \*)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


with open(UP + "Chase9563_Activity_20260823.csv") as f:
    r = csv.reader(f)
    next(r)
    for line in r:
        det, pdate, desc, amt, typ, bal = line[0], line[1], line[2], line[3], line[4], line[5]
        d = dt.datetime.strptime(pdate, "%m/%d/%Y").date()
        if not in_window(d):
            continue
        amt = float(amt) if amt.strip() else 0.0
        merch = clean_chase(desc)
        ext = eid("chase", pdate, amt, desc, bal)
        if typ == "DEBIT_CARD":
            cat, rev = categorise(merch)
            if amt > 0:      # card refund posts as a positive DEBIT_CARD row
                add(d, cat, -amt, "USD", merch, "退款 (card refund)", "chase_debit",
                    "csv_chase", ext, typ="Refund", needs_review=True)
            else:
                add(d, cat, abs(amt), "USD", merch, "", "chase_debit", "csv_chase", ext,
                    needs_review=rev)
        elif typ in ("QUICKPAY_DEBIT", "QUICKPAY_CREDIT"):
            questions["zelle"].append(dict(date=d, amt=amt, desc=merch, ext=ext))
        elif typ in ("MISC_DEBIT", "MISC_CREDIT", "ATM", "FEE_TRANSACTION",
                     "BILLPAY", "LOAN_PMT", "ACH_DEBIT", "WIRE_INCOMING"):
            questions["chase_misc"].append(dict(date=d, amt=amt, desc=merch, typ=typ, ext=ext))
        else:   # ACCT_XFER, CHASE_TO_PARTNERFI, PARTNERFI_TO_CHASE
            skipped[f"chase/{typ}"][0] += 1
            skipped[f"chase/{typ}"][1] += amt


# ============================================================== CATHAY ======
def clean_cathay(desc):
    s = desc.strip()
    s = re.sub(r"^POS PURCHASE MERCHANT PURCHASE TERMINAL \d+\s*", "", s)
    s = re.sub(r"^POS REFUND MERCHANT REFUND TERMINAL \d+\s*", "", s)
    s = re.sub(r"^DDA PURCHASE\s*", "", s)
    s = re.sub(r"^PREAUTHORIZED (WD|CREDIT)\s*", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    return s


for fname, acct in [("AccountHistory__1_.csv", "4826"), ("AccountHistory.csv", "8115")]:
    with open(UP + fname) as f:
        for line in csv.DictReader(f):
            d = dt.datetime.strptime(line["Post Date"], "%m/%d/%Y").date()
            if not in_window(d):
                continue
            debit = float(line["Debit"]) if line["Debit"] else 0.0
            credit = float(line["Credit"]) if line["Credit"] else 0.0
            desc = line["Description"]
            merch = clean_cathay(desc)
            ext = eid(f"cathay{acct}", line["Post Date"], debit or credit, desc, line["Balance"])
            up = desc.upper()
            pm = f"cathay_debit_{acct}"
            if "TRSFR" in up or "FUNDS TRANSFER" in up or up.startswith("DEPOSIT") \
               or "INTEREST CREDIT" in up or "JPMORGAN" in up or "INTERACTIVE BROK" in up:
                skipped[f"cathay{acct}/transfer"][0] += 1
                skipped[f"cathay{acct}/transfer"][1] += (credit - debit)
            elif "REFUND" in up or (credit and "PIRATE SHIP" in up):
                questions["cathay_refund"].append(
                    dict(date=d, amt=credit, desc=merch, acct=acct, ext=ext))
            elif debit:
                note = "Pending (未入账)" if line["Status"] == "Pending" else ""
                cat, rev = categorise(merch)
                add(d, cat, debit, "USD", merch, note, pm, f"csv_cathay{acct}", ext,
                    needs_review=rev or bool(note))
            else:
                questions["cathay_other"].append(dict(date=d, amt=credit, desc=merch, acct=acct))


# ============================================================== WECHAT ======
ws = openpyxl.load_workbook(UP + "微信支付账单流水文件_20260501-20260824__20260824043612.xlsx",
                            read_only=True)["Sheet1"]
wx = [r for r in ws.iter_rows(values_only=True)][18:]
for r in wx:
    if not r or r[0] is None:
        continue
    ts, kind, party, item, io, amt, paym, status, txid = r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]
    d = dt.datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
    if not in_window(d):
        continue
    amt = float(str(amt).replace("¥", "").replace(",", ""))
    ext = f"wechat:{txid}"
    if "退款" in str(status):
        questions["wechat_refund"].append(dict(date=d, amt=amt, party=party, item=item,
                                               io=io, status=status))
        continue
    if kind == "商户消费" and io == "支出":
        merch = str(party)
        cat, rev = categorise(merch + " " + str(item))
        add(d, cat, amt, "CNY", merch, str(item)[:40], "wechat", "xlsx_wechat", ext,
            needs_review=rev)
    elif io == "支出":      # 转账 / 红包 out
        questions["wechat_out"].append(dict(date=d, amt=amt, party=party, item=item))
    else:                   # 收入
        questions["wechat_in"].append(dict(date=d, amt=amt, party=party, item=item, kind=kind))


# ================================================================= CMB ======
# From the 掌上生活 screenshot. Billing cycles, NOT calendar months.
CMB_CYCLES = [
    ("2026-06-07", "5月8日-6月7日", 14556.76, "6月消费"),
    ("2026-07-07", "6月8日-7月7日",  3918.00, "7月消费"),
    ("2026-08-07", "7月8日-8月7日",  8517.04, "8月消费"),
    ("2026-08-23", "8月8日至今(已入账)", 11922.42, "最新消费"),
]
for datestr, period, amt, label in CMB_CYCLES:
    d = dt.date.fromisoformat(datestr)
    add(d, CATEGORIES["other"], amt, "CNY", "招商银行附属卡 (CMB aggregate)",
        f"{label} 入账周期 {period}｜汇总录入，无明细", "cmb_credit", "manual_cmb_summary",
        eid("cmb", label, amt), needs_review=True)




# =========================================== GARY'S RULINGS (2026-08-23) =====
# Applied after the automatic pass. Each block records his decision verbatim
# so a reader can tell what was inferred vs. what he actually said.

# --- B. Zelle: 小额双向 = AA 分账，直接算餐饮消费 --------------------------
ZELLE_EXPENSE = [
    ("2026-05-05",   20.00, "Zichen Liu",   "food",      "AA 分账"),
    ("2026-05-05",   20.00, "6082137428",   "food",      "AA 分账"),
    ("2026-05-06",   36.00, "Caroline Kuo", "food",      "AA 分账"),
    ("2026-07-15",   15.24, "yuninghan2001","food",      "AA 分账"),
    ("2026-07-17",    7.83, "YUNING HAN",   "food",      "AA 分账"),
    ("2026-07-28",   35.25, "YUNING HAN",   "food",      "AA 分账"),
    ("2026-07-29",   34.75, "YUNING HAN",   "food",      "AA 分账"),
    ("2026-08-13",   60.00, "FEI",          "food",      "AA 分账（未逐笔确认）"),
    ("2026-08-10",  225.00, "YUNING HAN",   "transport", "机票钱"),
    # FEI $2,104.06 拆两笔：$899 房租 + 余下旅游分账
    ("2026-07-03",  899.00, "FEI",          "rent",      "七月房租（从 $2,104.06 中拆出）"),
    ("2026-07-03", 1205.06, "FEI",          "transport", "旅游分账（$2,104.06 − $899 房租）"),
    ("2026-06-01",  619.00, "Zichen Liu",   "rent",      "房租 + 退租扣款"),
    ("2026-07-31",  220.00, "ZICHEN",       "rent",      "退租罚款 + 电费"),
    # 6/30 打车 $130，朋友账外还了一半，实际自付 $65
    ("2026-06-30",   65.00, "7874602520",   "transport", "机场→家打车，$130 的一半（另一半朋友账外还）"),
]
for datestr, amt, who, catkey, note in ZELLE_EXPENSE:
    d = dt.date.fromisoformat(datestr)
    add(d, CATEGORIES[catkey], amt, "USD", f"Zelle → {who}", note,
        "chase_debit", "csv_chase", eid("zelle", datestr, amt, who))

# Zelle 收入 = 别人还我的 AA 钱，冲抵
ZELLE_IN = [("2026-06-01", 100.00, "ZHENGGUANG ZHOU"), ("2026-06-26", 83.50, "BOXUAN YU"),
            ("2026-07-15", 2.00, "YUNING HAN"), ("2026-07-20", 15.00, "BOXUAN YU"),
            ("2026-07-30", 15.00, "YUNING HAN")]
for datestr, amt, who in ZELLE_IN:
    d = dt.date.fromisoformat(datestr)
    add(d, CATEGORIES["food"], -amt, "USD", f"Zelle ← {who}", "别人还的 AA 钱",
        "chase_debit", "csv_chase", eid("zellein", datestr, amt, who), typ="Reimbursement")

# --- C. 微信转出：孙瑜那两笔是还招行信用卡，排除；其余是消费 ----------------
WX_EXPENSE = [
    ("2026-05-10", 100.0, "李肇宁 (Li)",  "other", "微信转账（用途未细分）"),
    ("2026-06-02",  70.0, "周正光 (景行)", "other", "微信转账（用途未细分）"),
    ("2026-06-25",  60.0, "BOREDIE",     "other", "微信转账（用途未细分）"),
    ("2026-07-21", 100.0, "BOREDIE",     "other", "微信转账（用途未细分）"),
    ("2026-08-12", 140.0, "韩语宁",       "food",  "Uber+炸鸡"),
]
for datestr, amt, who, catkey, note in WX_EXPENSE:
    d = dt.date.fromisoformat(datestr)
    add(d, CATEGORIES[catkey], amt, "CNY", who, note, "wechat", "xlsx_wechat",
        eid("wxout", datestr, amt, who), needs_review=(catkey == "other"))

# --- B2. 换汇不是消费：$200 → 陈亦潇，¥1,356 回流，两边都排除 ------------
# (Zelle 2026-07-06 −$200 YIXIAO CHEN  ↔  微信 2026-07-05 +¥1,356 陳亦瀟)

# --- C2. 微信转账收入 = 别人还我垫付的美元，冲抵消费 ----------------------
#     红包（¥96 董泽森 / ¥200×2 付汉碧 / ¥9.23 X）是家里给的钱，不是报销，不冲抵
WX_REIMBURSE = [
    ("2026-06-02",  680.0, "熊天成 (TC)",       "打枪代付"),
    ("2026-06-16",  100.0, "李肇宁 (Li)",       "代付回款"),
    ("2026-06-26",   20.0, "BOREDIE",          "代付回款"),
    ("2026-06-26",   20.0, "BOREDIE",          "代付回款"),
    ("2026-07-20",  138.2, "於雯钰 Adelyn",     "代付回款"),
    ("2026-07-23",  815.0, "李肇宁 (Li)",       "帮他充会员，事后还款"),
    ("2026-08-21", 2149.0, "欢欢姐 (子喵)",      "代付回款（用途未细分）"),
    # 红包：付汉碧 = 妈妈，是家里给的钱，不冲抵消费，整笔不进表
    ("2026-07-25",    9.23, "X",                "红包，别人还钱"),
    ("2026-08-20",   96.00, "董泽森",            "红包，别人还钱"),
]
for datestr, amt, who, note in WX_REIMBURSE:
    d = dt.date.fromisoformat(datestr)
    add(d, CATEGORIES["other"], -amt, "CNY", who, note, "wechat", "xlsx_wechat",
        eid("wxin", datestr, amt, who), typ="Reimbursement", needs_review=True)

# --- A. 8月旅行：全程 Gary 刷卡，谭子骁事后转账报销 -------------------------
TAN_TOTAL_CNY = 140 + 98 + 1120 + 588 + 644 + 35 + 299 + 10871   # = 13,795
add(dt.date(2026, 8, 11), CATEGORIES["other"], -TAN_TOTAL_CNY, "CNY",
    "谭子骁 (暮雨潇骁)", "8月东岸旅行代付报销，冲抵 Chase/Cathay/招行 上的旅行消费",
    "wechat", "xlsx_wechat", eid("tan", "trip", TAN_TOTAL_CNY), typ="Reimbursement")

# --- D. Sheraton 押金退款（Cathay 4826，8/11 已退回） -----------------------
add(dt.date(2026, 8, 11), CATEGORIES["transport"], -50.00, "USD",
    "SHERATON 570 34498 PA", "酒店押金退回", "cathay_debit_4826", "csv_cathay4826",
    eid("cathayrefund", "2026-08-11", 50.0, "SHERATON"), typ="Refund")

# --- E. 现金：5/12 取 $1,000，其中 $530 当天存进了 Cathay 两个新账户 --------
add(dt.date(2026, 5, 12), CATEGORIES["other"], 470.00, "USD", "现金 (Cash)",
    "5/12 取现 $1,000 − 当天存入 Cathay $530（400+100+30）= 推算花掉 $470",
    "cash", "manual_cash", eid("cash", "2026-05-12", 470), needs_review=True)
add(dt.date(2026, 7, 27), CATEGORIES["other"], 200.00, "USD", "现金 (Cash)",
    "7/27 取现，去向未记录", "cash", "manual_cash",
    eid("cash", "2026-07-27", 200), needs_review=True)

# ============================================================== OUTPUT ======
HEADERS = ["id", "date", "type", "category", "amount", "currency", "amount_usd",
           "merchant", "notes", "payment_method", "source", "external_id",
           "is_recurring", "created_at", "_review"]
rows.sort(key=lambda x: x["date"])
with open(OUT + "ledger_20260501_20260823.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=HEADERS)
    w.writeheader()
    w.writerows(rows)

# summary
print(f"ledger rows: {len(rows)}")
tot = sum(float(r["amount_usd"]) for r in rows)
print(f"total USD: {tot:,.2f}")
by_src = defaultdict(lambda: [0, 0.0])
for r in rows:
    by_src[r["source"]][0] += 1
    by_src[r["source"]][1] += float(r["amount_usd"])
print("\nby source:")
for k, (n, s) in sorted(by_src.items(), key=lambda kv: -kv[1][1]):
    print(f"  {k:24} {n:>4}  ${s:>10,.2f}")
by_cat = defaultdict(lambda: [0, 0.0])
for r in rows:
    by_cat[r["category"]][0] += 1
    by_cat[r["category"]][1] += float(r["amount_usd"])
print("\nby category:")
for k, (n, s) in sorted(by_cat.items(), key=lambda kv: -kv[1][1]):
    print(f"  {k:24} {n:>4}  ${s:>10,.2f}")
print(f"\nneeds review: {sum(1 for r in rows if r['_review']=='TRUE')}")
print("\nskipped (transfers etc.):")
for k, (n, s) in sorted(skipped.items()):
    print(f"  {k:34} {n:>4}  {s:>14,.2f}")
print("\nquestion buckets:")
for k, v in questions.items():
    print(f"  {k:20} {len(v)}")

import json
with open(OUT + "questions.json", "w") as f:
    json.dump({k: [{kk: str(vv) for kk, vv in d.items()} for d in v]
               for k, v in questions.items()}, f, ensure_ascii=False, indent=1)
