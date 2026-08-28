import pandas as pd
import streamlit as st
import uuid
from datetime import datetime

import sheets
from schema import HEADERS


class DBManager:
    def __init__(self):
        # 连接细节（凭证读取、scope、gid=0 而不是 .sheet1）全部搬进了 sheets.py——
        # 这里只保留 Streamlit 特有的部分：连接失败时用 st.error 提示，而不是
        # 让异常直接往上抛，跟原来的行为一致。
        try:
            self.sheet = sheets.connect()
        except Exception as e:
            st.error(f"无法连接 Google Sheets，请检查 Secrets 配置。错误: {e}")

    @st.cache_data(ttl=300)
    def get_transactions(_self):
        # 注意：参数名用 _self 而不是 self —— st.cache_data 会跳过对下划线开头
        # 参数的哈希检查，否则 DBManager 里不可哈希的 gspread 连接对象会导致报错。
        data = sheets.get_all_records(_self.sheet)
        # 如果是空的，返回空 DataFrame 但保持完整列结构（HEADERS 是列定义唯一来源）
        if not data:
            return pd.DataFrame(columns=HEADERS)
        df = pd.DataFrame(data)
        # 确保金额是数字
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
        # amount_usd 是唯一该拿去 sum 的字段（CNY 行的 amount 是原始人民币数字，
        # 不能直接跟 USD 加在一起）。缺失/坏值时兜底成 amount 本身（历史上
        # amount_usd 空的老行，多半就是 USD 记录，amount 本身已经是对的）。
        df['amount_usd'] = pd.to_numeric(df['amount_usd'], errors='coerce')
        df['amount_usd'] = df['amount_usd'].fillna(df['amount'])
        # 表还是旧版本列数时，这里会把缺的列补成 NaN，顺序对齐 HEADERS；
        # 表升级之后自动就是原样。
        return df.reindex(columns=HEADERS)

    def add_transaction(self, date, category, amount, notes, type="Expense", payment_method=""):
        # 生成一个唯一 ID (UUID)，方便以后删除
        unique_id = str(uuid.uuid4())
        sheets.append_row(self.sheet, {
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
        # 写入成功后立刻让缓存失效，避免刚加的记录要等 TTL 过期才显示
        self.get_transactions.clear()

    def add_transactions_bulk(self, transactions, is_recurring: bool = False):
        # 批量添加
        # transactions 是 [(date, cat, amt, note, type)...]
        # is_recurring 由调用方决定，不在这个方法里假设"批量写入 = 固定支出"——
        # Phase 3 的 WeChat/CMB CSV 批量导入也会走这里，那些是日常消费，不是固定支出。
        created_at = datetime.now().isoformat(timespec="seconds")
        rows_to_add = []
        for t in transactions:
            unique_id = str(uuid.uuid4())
            # t 的顺序是 date, category, amount, notes, type
            date, category, amount, notes, type_ = t
            rows_to_add.append({
                "id": unique_id,
                "date": date,
                "type": type_,
                "category": category,
                "amount": amount,
                "amount_usd": amount,
                "notes": notes,
                "created_at": created_at,
                "is_recurring": is_recurring,
            })

        sheets.append_rows(self.sheet, rows_to_add)
        self.get_transactions.clear()

    def update_transaction(self, transaction_id, **fields):
        # 按 id 找到那一行，更新传入的字段。目前调用方（app.py 的 data_editor）
        # 只允许改 category/notes/payment_method/date —— amount 故意没开放
        # 编辑，因为 amount 联动 amount_usd/currency 换算是另一个问题，
        # 见 CLAUDE.md TODO。
        try:
            sheets.update_row(self.sheet, transaction_id, **fields)
            self.get_transactions.clear()
        except Exception as e:
            st.error(f"更新失败: {e}")

    def delete_transaction(self, transaction_id):
        # Google Sheets 删除比较麻烦，需要先找到行号
        try:
            sheets.delete_row(self.sheet, transaction_id)
            # 只有删除成功才清缓存；异常分支里数据没变，不需要清
            self.get_transactions.clear()
        except Exception as e:
            st.error(f"删除失败 (ID未找到): {e}")


@st.cache_resource
def get_db_manager() -> "DBManager":
    """DBManager 的单例工厂。gspread 连接的建立开销不小，之前每次 Streamlit
    rerun 都要重建一次，是主要的性能瓶颈。这个函数先准备好，app.py 还没切过来
    用它，现在加进来不影响现有行为。"""
    return DBManager()
