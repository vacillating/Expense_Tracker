import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
from database import DBManager
from io import BytesIO

# Page Config
st.set_page_config(page_title="Personal Finance Manager v2.2", layout="wide")

# Initialize DB
db = DBManager()

# Constants
CATEGORIES = [
    "房租 (Rent)", 
    "餐饮 (Dine & Grocery)", 
    "交通 (Transport)", 
    "购物 (Shopping)", 
    "娱乐 (Entertainment)", 
    "其他 (Other)", 
    "医疗（Medical)"
]

# Title
st.title("💰 Personal Finance Manager v2.2")

# Navigation
page = st.sidebar.radio("Navigation", ["➕ 记一笔 (Quick Log)", "📊 看账本 (Dashboard)"])

# Shared Sidebar Filters (Global or Dashboard specific? User asked for split. Let's keep filters global for Dashboard, but maybe hide for Quick Log to keep it clean?)
# "Quick Log" should be clean.
# Let's put filters inside the Dashboard logic or keep them sidebar but only show if Dashboard.

if page == "📊 看账本 (Dashboard)":
    st.sidebar.header("Filters")
    today = datetime.today()
    current_year = today.year
    years = list(range(current_year - 5, current_year + 6))
    selected_year = st.sidebar.selectbox("Year", years, index=5)

    months = ["All", "January", "February", "March", "April", "May", "June", 
              "July", "August", "September", "October", "November", "December"]
    selected_month = st.sidebar.selectbox("Month", months, index=today.month)

    # Monthly Setup
    st.sidebar.markdown("---")
    st.sidebar.header("Monthly Setup")
    monthly_budget = st.sidebar.number_input("Monthly Budget ($)", value=2000.0, step=100.0)

    if st.sidebar.button("Load Fixed Expenses"):
        if selected_month == "All":
            target_date = today.strftime("%Y-%m-%d")
            st.sidebar.warning(f"Month not selected. Adding to current date: {target_date}")
        else:
            month_index = months.index(selected_month)
            target_date = datetime(selected_year, month_index, 1).strftime("%Y-%m-%d")
        
        fixed_expenses = [
            (target_date, "房租 (Rent)", 600.0, "Fixed Rent", "Expense"),
            (target_date, "其他 (Other)", 25.0, "US Mobile", "Expense"),
            (target_date, "娱乐 (Entertainment)", 34.93, "Subscription", "Expense")
        ]
        db.add_transactions_bulk(fixed_expenses)
        st.sidebar.success("Fixed expenses loaded!")
        st.rerun()

# Page 1: Quick Log
if page == "➕ 记一笔 (Quick Log)":
    st.header("Quick Log")
    
    with st.form("quick_log_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        date = col1.date_input("Date", datetime.today())
        category = col2.selectbox("Category", CATEGORIES)
        
        col3, col4 = st.columns(2)
        amount = col3.number_input("Amount", min_value=0.01, format="%.2f")
        notes = col4.text_input("Notes")
        
        submitted = st.form_submit_button("Save Expense", use_container_width=True)
        
        if submitted:
            db.add_transaction(date.strftime("%Y-%m-%d"), category, amount, notes, type="Expense")
            st.success(f"✅ Saved: {category} - ${amount:.2f}")

# Page 2: Dashboard
elif page == "📊 看账本 (Dashboard)":
    # Helper to filter data
    def filter_data(df, year, month):
        df['date'] = pd.to_datetime(df['date'])
        df = df[df['date'].dt.year == year]
        if month != "All":
            month_index = months.index(month)
            df = df[df['date'].dt.month == month_index]
        return df

    # Load Data
    df = db.get_transactions()
    df_filtered = filter_data(df.copy(), selected_year, selected_month)

    # Dashboard Metrics
    st.header("Dashboard")
    total_spent = df_filtered[df_filtered['type'] == 'Expense']['amount'].sum()
    budget_status = monthly_budget - total_spent

    col1, col2 = st.columns(2)
    col1.metric("Total Spent (This Month)", f"${total_spent:,.2f}")
    col2.metric("Budget Status", f"${budget_status:,.2f}", delta_color="normal")

    # Visualizations
    st.header("Visualizations")
    if not df_filtered.empty:
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            # Pie Chart: Expenses by Category
            fig_pie = px.pie(df_filtered[df_filtered['type'] == 'Expense'], values='amount', names='category', title='Expenses by Category')
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col_chart2:
            # Bar Chart: Total Amount by Category
            category_spending = df_filtered[df_filtered['type'] == 'Expense'].groupby('category')['amount'].sum().reset_index()
            fig_bar = px.bar(category_spending, x='category', y='amount', color='category', title='Total Amount by Category')
            st.plotly_chart(fig_bar, use_container_width=True)

    # Category Breakdown
    st.header("Monthly Summary")
    if not df_filtered.empty:
        breakdown = df_filtered[df_filtered['type'] == 'Expense'].groupby('category')['amount'].sum().reset_index()
        breakdown = breakdown.sort_values(by='amount', ascending=False)
        breakdown.columns = ["Category", "Total Amount"]
        st.dataframe(
            breakdown,
            column_config={
                "Category": st.column_config.TextColumn("Category"),
                "Total Amount": st.column_config.NumberColumn("Total Amount", format="$%.2f"),
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("No expenses yet.")


    # Data Grid (Manually Fixed Version)
    # Data Grid (Verified Fix)
    with st.expander("📝 Edit Transactions", expanded=True):
        st.subheader("Expense Log")

        # 1. 准备数据：保留 ID，但重置索引以匹配行号
        df_for_grid = df_filtered.copy().sort_values(by="date", ascending=False).reset_index(drop=True)
        
        # 2. 存入 Session State (用于回调中查找真实 ID)
        st.session_state["df_current_view"] = df_for_grid

        # 3. 回调函数
        def commit_changes():
            changes = st.session_state["expense_editor"]
            needs_rerun = False

            # --- 删除逻辑 ---
            if changes["deleted_rows"]:
                for index in changes["deleted_rows"]:
                    try:
                        # 只要 database.py 里有 commit，这里就会永久删除
                        row_id = int(st.session_state["df_current_view"].iloc[index]["id"])
                        db.delete_transaction(row_id)
                        needs_rerun = True
                        st.toast(f"🗑️ 已从数据库永久删除记录 ID: {row_id}") # 成功提示
                    except Exception as e:
                        st.error(f"删除出错: {e}")

            # --- 新增逻辑 ---
            if changes["added_rows"]:
                for row in changes["added_rows"]:
                    try:
                        db.add_transaction(
                            date=row.get("date", datetime.today().strftime('%Y-%m-%d')),
                            category=row.get("category", "其他 (Other)"),
                            amount=float(row.get("amount", 0)),
                            notes=row.get("notes", ""),
                            type="Expense"
                        )
                        needs_rerun = True
                    except Exception:
                        pass

            # --- 强制刷新 ---
            if needs_rerun:
                st.rerun()

        # 4. 渲染编辑器
        st.data_editor(
            df_for_grid,
            column_config={
                "id": None, # 隐藏 ID
                "date": st.column_config.DateColumn("Date", format="YYYY-MM-DD"),
                "type": None,
                "category": st.column_config.SelectboxColumn("Category", options=CATEGORIES, required=True),
                "amount": st.column_config.NumberColumn("Amount", format="$%.2f", required=True),
                "notes": st.column_config.TextColumn("Notes"),
            },
            use_container_width=True,
            num_rows="dynamic",
            key="expense_editor",
            on_change=commit_changes
        )
    # Export
    st.markdown("---")
    def to_excel(df):
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Sheet1')
        processed_data = output.getvalue()
        return processed_data

    if st.button("Download Excel"):
        excel_data = to_excel(df_filtered)
        st.download_button(
            label="Click to Download",
            data=excel_data,
            file_name=f"finance_data_v2_2_{selected_year}_{selected_month}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
