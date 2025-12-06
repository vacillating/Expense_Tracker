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
    "医疗（Medical）"
]

# Title
st.title("💰 Personal Finance Manager")

# Navigation
page = st.sidebar.radio("Navigation", ["➕ 记一笔 (Quick Log)", "📊 看账本 (Dashboard)"])

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
# ==========================================
# 4. 页面: 看账本 (Dashboard)
# ==========================================
elif page == "📊 看账本 (Dashboard)":
    
    # --- 过滤器 (Sidebar Filters) ---
    st.sidebar.header("Filters")
    today = datetime.today()
    current_year = today.year
    
    # 1. 年份筛选 (增加 All)
    year_options = ["All"] + list(range(current_year - 5, current_year + 6))
    selected_year = st.sidebar.selectbox("Year", year_options, index=6)

    # 2. 月份筛选
    months = ["All", "January", "February", "March", "April", "May", "June", 
              "July", "August", "September", "October", "November", "December"]
    selected_month = st.sidebar.selectbox("Month", months, index=today.month)
    
    # 3. ✨ 新增：分类筛选 (Category Filter) ✨
    # 在选项列表前面加一个 "All"，方便看总账
    category_options = ["All"] + CATEGORIES
    selected_category = st.sidebar.selectbox("Category (Filter)", category_options, index=0)

    # --- 固定支出按钮 (保持不变) ---
    st.sidebar.markdown("---")
    st.sidebar.header("Monthly Setup")
    if st.sidebar.button("Load Fixed Expenses"):
        # 默认填入当年当月，如果是 All 则填入今天
        target_year = current_year if selected_year == "All" else selected_year
        target_month_idx = today.month if selected_month == "All" else months.index(selected_month)
        
        try:
            target_date = datetime(target_year, target_month_idx, 1).strftime("%Y-%m-%d")
        except:
            target_date = today.strftime("%Y-%m-%d") # 防止日期错误兜底

        fixed_expenses = [
            (target_date, "房租 (Rent)", 600.0, "Fixed Rent", "Expense"),
            (target_date, "其他 (Other)", 25.0, "US Mobile", "Expense"),
            (target_date, "娱乐 (Entertainment)", 34.93, "Subscription", "Expense"),
            (target_date, "医疗 (Medical)", 5.0, "降压药", "Expense"),
        ]
        db.add_transactions_bulk(fixed_expenses)
        st.sidebar.success("Fixed expenses loaded!")
        st.rerun()

    # --- 数据读取与多重过滤逻辑 ---
    df = db.get_transactions()
    
    if not df.empty:
        df['date'] = pd.to_datetime(df['date'])
        
        # 1. 年份过滤
        if selected_year != "All":
            df_filtered = df[df['date'].dt.year == selected_year]
        else:
            df_filtered = df.copy()
            
        # 2. 月份过滤
        if selected_month != "All":
            month_idx = months.index(selected_month)
            df_filtered = df_filtered[df_filtered['date'].dt.month == month_idx]
            
        # 3. ✨ 分类过滤 ✨
        if selected_category != "All":
            df_filtered = df_filtered[df_filtered['category'] == selected_category]
            
    else:
        df_filtered = df # 空表

    # --- 顶部指标 ---
    st.header("Dashboard")
    total_spent = df_filtered['amount'].sum()
    count = len(df_filtered)
    
    col1, col2 = st.columns(2)
    # 根据是否选择了分类，动态修改标题
    metric_label = "Total Spent" if selected_category == "All" else f"Total Spent on {selected_category}"
    
    col1.metric(metric_label, f"${total_spent:,.2f}")
    col2.metric("Transactions", count)

    # --- 可视化图表 (智能切换) ---
    st.header("Visualizations")
    if not df_filtered.empty:
        # 场景 A: 看了具体分类 (例如：只看餐饮) -> 显示每日趋势
        if selected_category != "All":
            st.info(f"👀 Viewing details for: **{selected_category}**")
            # 每日趋势图
            daily_trend = df_filtered.groupby('date')['amount'].sum().reset_index()
            fig_trend = px.bar(daily_trend, x='date', y='amount', title=f'Daily Spending Trend ({selected_category})')
            st.plotly_chart(fig_trend, use_container_width=True)
            
        # 场景 B: 看了所有分类 -> 显示饼图和对比柱状图
        else:
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                fig_pie = px.pie(df_filtered, values='amount', names='category', title='Expenses by Category')
                st.plotly_chart(fig_pie, use_container_width=True)
            with col_c2:
                cat_sum = df_filtered.groupby('category')['amount'].sum().reset_index()
                fig_bar = px.bar(cat_sum, x='category', y='amount', color='category', title='Total Amount by Category')
                st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("No expenses found for this period.")

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
                        row_id = str(st.session_state["df_current_view"].iloc[index]["id"])
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
