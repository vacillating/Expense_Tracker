import sqlite3
import pandas as pd
from datetime import datetime

class DBManager:
    def __init__(self, db_path="finance.db"):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def init_db(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                notes TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def add_transaction(self, date, category, amount, notes, type="Expense"):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO transactions (date, type, category, amount, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (date, type, category, amount, notes))
        conn.commit() # <--- 这一行很重要，负责保存新增
        conn.close()

    def add_transactions_bulk(self, transactions):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.executemany('''
            INSERT INTO transactions (date, category, amount, notes, type)
            VALUES (?, ?, ?, ?, ?)
        ''', transactions)
        conn.commit()
        conn.close()

    def get_transactions(self):
        conn = self.get_connection()
        # 读取时包含 ID，但在前端隐藏
        df = pd.read_sql_query("SELECT * FROM transactions", conn)
        conn.close()
        return df

    def delete_transaction(self, transaction_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        # 执行删除
        cursor.execute('DELETE FROM transactions WHERE id = ?', (transaction_id,))
        # ！！！关键点在此！！！
        conn.commit()  # <--- 之前可能缺了这行，导致删除没保存
        # ！！！！！！！！！！
        conn.close()