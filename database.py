import gspread
import pandas as pd
import streamlit as st
import uuid
from google.oauth2.service_account import Credentials
from datetime import datetime

from schema import HEADERS, row_from_dict


class DBManager:
    def __init__(self):
        # 连接 Google Sheets
        # 我们将从 Streamlit Secrets 里读取钥匙，这样才安全
        # 只留 spreadsheets 这一个 scope：用 open_by_key 直接按表格 ID 打开，
        # 不需要在 Drive 里按名字搜索，所以不需要 drive scope。用真实凭证连过一次
        # 表验证过：只留这一个 scope 照样能正常读写。
        self.scope = ["https://www.googleapis.com/auth/spreadsheets"]

        # 尝试连接，如果连接失败(比如本地没配置)，会报错提示
        try:
            # 读取 secrets.toml (本地) 或 Streamlit Cloud Secrets (云端)
            self.creds = Credentials.from_service_account_info(
                st.secrets["gcp_service_account"], scopes=self.scope
            )
            self.client = gspread.authorize(self.creds)
            # 用 sheet_key（表格 ID）打开，而不是按名字搜索：少一次 API 调用，
            # 也不怕以后改表格名字。
            # 注意：不用 .sheet1 —— 那是按"第 0 个分页"取的，migrate_schema.py
            # 跑 duplicate_sheet() 建备份分页时，备份被插到了索引 0，把真正的数据
            # 分页挤到了索引 1，.sheet1 会连到备份而不是真实数据（实测踩过这个坑）。
            # gid=0 是这张表最早创建时的原始分页 ID，跟标题、位置都无关，
            # 只要这个分页本身没被删掉，永远指向真正的数据。
            spreadsheet = self.client.open_by_key(st.secrets["sheet_key"])
            self.sheet = spreadsheet.get_worksheet_by_id(0)
        except Exception as e:
            st.error(f"无法连接 Google Sheets，请检查 Secrets 配置。错误: {e}")

    @st.cache_data(ttl=300)
    def get_transactions(_self):
        # 获取所有数据
        # 注意：参数名用 _self 而不是 self —— st.cache_data 会跳过对下划线开头
        # 参数的哈希检查，否则 DBManager 里不可哈希的 gspread 连接对象会导致报错。
        data = _self.sheet.get_all_records()
        # 如果是空的，返回空 DataFrame 但保持完整列结构（HEADERS 是列定义唯一来源）
        if not data:
            return pd.DataFrame(columns=HEADERS)
        df = pd.DataFrame(data)
        # 确保金额是数字
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
        # 表还是旧的 6 列时，这里会把缺的 8 列补成 NaN，顺序对齐 HEADERS；
        # 表升级到 14 列之后自动就是原样。app.py 目前只读旧的 6 列，不受影响。
        return df.reindex(columns=HEADERS)

    def add_transaction(self, date, category, amount, notes, type="Expense", payment_method=""):
        # 生成一个唯一 ID (UUID)，方便以后删除
        unique_id = str(uuid.uuid4())
        row = row_from_dict({
            "id": unique_id,
            "date": date,
            "type": type,
            "category": category,
            "amount": amount,
            "amount_usd": amount,  # Quick Log 目前只收 USD，跟 amount 一致
            "notes": notes,
            "payment_method": payment_method,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        })
        self.sheet.append_row(row)
        # 写入成功后立刻让缓存失效，避免刚加的记录要等 TTL 过期才显示
        self.get_transactions.clear()

    def add_transactions_bulk(self, transactions, is_recurring: bool = False):
        # 批量添加
        # transactions 是 [(date, cat, amt, note, type)...]
        # is_recurring 由调用方决定，不在这个方法里假设"批量写入 = 固定支出"——
        # Phase 3 的 WeChat/CMB CSV 批量导入也会走这里，那些是日常消费，不是固定支出。
        # 目前唯一的调用方是 app.py 的"Load Fixed Expenses"按钮，它没传这个参数，
        # 所以还是走默认值 False；等下个 commit 切 app.py 时，那个按钮会显式传 True。
        created_at = datetime.now().isoformat(timespec="seconds")
        rows_to_add = []
        for t in transactions:
            unique_id = str(uuid.uuid4())
            # t 的顺序是 date, category, amount, notes, type
            date, category, amount, notes, type_ = t
            rows_to_add.append(row_from_dict({
                "id": unique_id,
                "date": date,
                "type": type_,
                "category": category,
                "amount": amount,
                "amount_usd": amount,
                "notes": notes,
                "created_at": created_at,
                "is_recurring": is_recurring,
            }))

        self.sheet.append_rows(rows_to_add)
        self.get_transactions.clear()

    def delete_transaction(self, transaction_id):
        # Google Sheets 删除比较麻烦，需要先找到行号
        try:
            # 找到 ID 所在的单元格
            cell = self.sheet.find(transaction_id)
            # 删除那一行
            self.sheet.delete_rows(cell.row)
            # 只有删除成功才清缓存；异常分支里数据没变，不需要清
            self.get_transactions.clear()
        except Exception as e:
            st.error(f"删除失败 (ID未找到): {e}")


@st.cache_resource
def get_db_manager() -> "DBManager":
    """DBManager 的单例工厂。gspread 连接的建立开销不小，之前每次 Streamlit
    rerun 都要重建一次，是主要的性能瓶颈。这个函数先准备好，app.py 还没切过来
    用它（那是下一个 commit），现在加进来不影响现有行为。"""
    return DBManager()
