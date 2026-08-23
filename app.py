import streamlit as st
import pandas as pd
import hmac
from datetime import datetime
import plotly.express as px
from database import DBManager
from io import BytesIO

# Page Config
st.set_page_config(page_title="Personal Finance Manager", layout="wide")


def check_password():
    """密码门：验证通过前，后面的代码（包括连 Google Sheets）都不会执行。"""
    if st.session_state.get("authenticated"):
        return True

    st.title("🔒 Personal Finance Manager")
    pwd = st.text_input("密码 (Password)", type="password")
    if st.button("登录 (Log in)"):
        if "app_password" not in st.secrets:
            st.error("未配置密码 (app_password missing in secrets)，请检查 secrets 配置。")
            return False
        if hmac.compare_digest(pwd, st.secrets["app_password"]):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("密码错误 (Incorrect password)")
    return False


if not check_password():
    st.stop()

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
    "医疗 (Medical)"
]
# 定义固定支出模板 (全局配置)
# 格式: (Category, Amount, Note) -> 不包含日期，因为日期是动态的
FIXED_TEMPLATES = [
    ("房租 (Rent)", 600.0, "Fixed Rent"),
    ("其他 (Other)", 25.0, "US Mobile"),
    ("娱乐 (Entertainment)", 34.93, "Subscription"),
    ("医疗 (Medical)", 5.0, "降压药")
]
# 自动提取“固定支出类别”列表 (给智能算法用)
# 这是一个 Python 推导式：自动把上面列表里的第0个元素(类别)拿出来，组成一个新列表
# 结果会自动变成: ["房租 (Rent)", "其他 (Other)", ...]
FIXED_CATEGORIES_For_Calc = [item[0] for item in FIXED_TEMPLATES]

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

        transactions_to_add = []
        for template in FIXED_TEMPLATES:
            # 拼装数据: (Date, Category, Amount, Note, Type)
            # template[0]是分类, template[1]是金额, template[2]是备注
            row = (target_date, template[0], template[1], template[2], "Expense")
            transactions_to_add.append(row)
            
        db.add_transactions_bulk(transactions_to_add)
        st.sidebar.success(f"已加载 {len(transactions_to_add)} 笔固定支出！")
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

# --- 顶部指标 (v3.4 智能预测版) ---
    st.header("Dashboard")

    # 1. 基础数据计算
    total_spent_month = df_filtered['amount'].sum() # 本月账面总支出
    
    # 2. 智能预测算法
    if selected_year != "All" and selected_month != "All":
        import calendar
        month_idx = months.index(selected_month)
        _, num_days_in_month = calendar.monthrange(selected_year, month_idx)
        
        # 判断是否是“当前正在进行”的月份
        is_current_month = (selected_year == today.year) and (month_idx == today.month)
        
        if is_current_month:
            # --- 核心算法优化 (v3.6 精准剥离版) ---
            
            # A. 截止目前的总支出
            df_current_progress = df_filtered[df_filtered['date'].dt.date <= today.date()].copy()
            
            # B. 精准剥离固定支出 (Targeted Stripping)
            # 逻辑：不再按“分类”一刀切，而是按 (分类 + 金额) 精准抓取
            
            # 1. 初始化一个“全部为假”的标记列表
            is_fixed_transaction = pd.Series(False, index=df_current_progress.index)
            
            # 2. 遍历你的模板，把符合特征的行标记出来
            for template in FIXED_TEMPLATES:
                # template 格式: (Category, Amount, Note)
                fix_cat = template[0]
                fix_amt = template[1]
                
                # 查找同时满足“分类”和“金额”的记录
                # (注意：浮点数比较通常用近似值，但这里我们假设金额是精确录入的)
                match_condition = (
                    (df_current_progress['category'] == fix_cat) & 
                    (abs(df_current_progress['amount'] - fix_amt) < 0.01) # 允许0.01的误差
                )
                # 将匹配到的行标记为 True (固定支出)
                is_fixed_transaction = is_fixed_transaction | match_condition
            # 注意：之前这里还有一段"只要分类是医疗就整体算固定支出"的逻辑，
            # 会覆盖掉上面按 (分类+金额) 精确匹配的效果，导致偶发的大额医疗支出
            # 被错误地排除在日常日均之外。医疗类目里金额精确等于 5.0 的那笔
            # （FIXED_TEMPLATES 里的"降压药"）已经能被上面的循环正确识别为固定支出，
            # 不需要额外的分类级别兜底。

            # 3. 拆分数据
            df_fixed = df_current_progress[is_fixed_transaction]
            df_variable = df_current_progress[~is_fixed_transaction] # 取反，剩下的就是日常
            
            amount_fixed = df_fixed['amount'].sum()
            amount_variable = df_variable['amount'].sum()
            
            # C. 计算“真实”日均 (只算日常花销)
            days_passed = today.day
            daily_living_avg = amount_variable / days_passed if days_passed > 0 else 0
            
            # D. 预测月底总额
            # 预测值 = 已知固定支出 + (日常日均 * 全月天数)
            projected_variable = daily_living_avg * num_days_in_month
            projected_total = amount_fixed + projected_variable
            
            # E. 加上未来的支出
            df_future = df_filtered[df_filtered['date'].dt.date > today.date()]
            projected_total += df_future['amount'].sum()

            metric_label = "📅 Daily Living Avg (日常日均)"
            metric_value = f"${daily_living_avg:.0f} / day"
            metric_delta = f"Est. Total: ${projected_total:,.0f}" 
            delta_color = "off"
            
            spent_to_date = df_current_progress['amount'].sum()
            
            # --- 🔍 调试窗口 (验证是否只抓到了那几项) ---
            with st.expander("🕵️‍♂️ 算法验证 (Check Logic)"):
                st.write("🔴 被识别为固定支出 (Fixed):", df_fixed[['date', 'category', 'amount', 'notes']])
                st.write("🟢 纳入日均计算的日常支出 (Variable):", df_variable[['date', 'category', 'amount', 'notes']])
            
        else:
            # 历史月份：直接算简单平均
            daily_avg = total_spent_month / num_days_in_month
            metric_label = "📅 Daily Average"
            metric_value = f"${daily_avg:.0f} / day"
            metric_delta = None
            delta_color = "off"
            spent_to_date = total_spent_month
    else:
        # All Time 视图
        metric_label = "📅 Transaction Count"
        metric_value = len(df_filtered)
        metric_delta = None
        delta_color = "off"
        spent_to_date = total_spent_month

    # 3. 渲染指标卡 (显示 3 个指标)
    col1, col2, col3 = st.columns(3)
    
    # 指标 1: 本月总账面 (包含未来的机票)
    col1.metric("Total Booked", f"${total_spent_month:,.2f}")
    
    # 指标 2: 截止今日实付 (不含未来)
    col2.metric("Spent to Date", f"${spent_to_date:,.2f}")
    
    # 指标 3: 智能预测 (剥离房租后的生活费预测)
    col3.metric(metric_label, metric_value, delta=metric_delta, delta_color=delta_color)

    
    # --- 可视化图表 (Visualizations) ---
    st.header("Visualizations")
    if not df_filtered.empty:
        
        # 场景 A: 看了具体分类 (Single Category View)
        if selected_category != "All":
            # 计算该分类占总支出的比例
            # (需要先算一下总账，为了简单，我们可以重新基于 db 算，或者简单展示当前数据)
            
            col_c1, col_c2 = st.columns(2)
            
            with col_c1:
                st.subheader(f"🔍 Top Spending in {selected_category}")
                # 方案二：该分类下最贵的 5 笔消费 (排行榜)
                top_expenses = df_filtered.nlargest(5, 'amount').sort_values(by='amount', ascending=True)
                if not top_expenses.empty:
                    fig_top = px.bar(
                        top_expenses, 
                        x='amount', 
                        y='notes', 
                        orientation='h', # 横向柱状图
                        text='amount',
                        title="Top 5 Largest Transactions",
                        color='amount',
                        color_continuous_scale='Reds'
                    )
                    fig_top.update_traces(texttemplate='$%{text:.2f}', textposition='outside')
                    st.plotly_chart(fig_top, use_container_width=True)
                else:
                    st.info("Not enough data for ranking.")

            with col_c2:
                st.subheader("📅 Spending Timeline")
                # 方案一：散点图 (气泡图)
                # X轴是日期，Y轴是金额，点的大小也是金额
                fig_scatter = px.scatter(
                    df_filtered, 
                    x='date', 
                    y='amount', 
                    size='amount',  # 钱越多，泡泡越大
                    color='amount',
                    hover_data=['notes'], # 鼠标放上去显示备注
                    title="Transaction Timeline (Spot the Outliers)",
                    size_max=30
                )
                st.plotly_chart(fig_scatter, use_container_width=True)
            
        # 场景 B: 看了所有分类 (Overview)
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
