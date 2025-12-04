import gspread
import pandas as pd
import streamlit as st
import uuid
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

class DBManager:
    def __init__(self):
        # 连接 Google Sheets
        # 我们将从 Streamlit Secrets 里读取钥匙，这样才安全
        self.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # 尝试连接，如果连接失败(比如本地没配置)，会报错提示
        try:
            # 读取 secrets.toml (本地) 或 Streamlit Cloud Secrets (云端)
            self.creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], self.scope)
            self.client = gspread.authorize(self.creds)
            # 打开表格 (确保你的 Google Sheet 名字叫 'finance_db')
            self.sheet = self.client.open("finance_db").sheet1
        except Exception as e:
            st.error(f"无法连接 Google Sheets，请检查 Secrets 配置。错误: {e}")

    def get_transactions(self):
        # 获取所有数据
        data = self.sheet.get_all_records()
        df = pd.DataFrame(data)
        # 如果是空的，返回空 DataFrame 但保持列结构
        if df.empty:
            return pd.DataFrame(columns=["id", "date", "type", "category", "amount", "notes"])
        # 确保金额是数字
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
        return df

    def add_transaction(self, date, category, amount, notes, type="Expense"):
        # 生成一个唯一 ID (UUID)，方便以后删除
        unique_id = str(uuid.uuid4())
        # 添加一行 (注意顺序要和表头一致: id, date, type, category, amount, notes)
        self.sheet.append_row([unique_id, date, type, category, amount, notes])

    def add_transactions_bulk(self, transactions):
        # 批量添加
        # transactions 是 [(date, cat, amt, note, type)...]
        # 我们需要转成带 ID 的列表
        rows_to_add = []
        for t in transactions:
            unique_id = str(uuid.uuid4())
            # t 的顺序是 date, category, amount, notes, type
            # 目标顺序: id, date, type, category, amount, notes
            rows_to_add.append([unique_id, t[0], t[4], t[1], t[2], t[3]])
        
        self.sheet.append_rows(rows_to_add)

    def delete_transaction(self, transaction_id):
        # Google Sheets 删除比较麻烦，需要先找到行号
        try:
            # 找到 ID 所在的单元格
            cell = self.sheet.find(transaction_id)
            # 删除那一行
            self.sheet.delete_rows(cell.row)
        except Exception as e:
            st.error(f"删除失败 (ID未找到): {e}")