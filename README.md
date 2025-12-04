# 💰 Personal Finance Manager

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://streamlit.io)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, robust, and interactive personal expense tracker built with **Python** and **Streamlit**.  
Designed to replace complex Excel spreadsheets with a clean UI, rapid data entry, and real-time visualization.

---

## ✨ Key Features

### 🚀 Efficient Workflow
- **Dual Modes**:
  - **➕ Quick Log** – distraction-free, fast transaction entry
  - **📊 Dashboard** – full analytics and data management
- **Google Sheets-style grid** for inline editing and deletion
- **One-click Monthly Reset** – auto load recurring fixed expenses

### 📈 Visual Analysis
- **Real-time metrics**: total spent + transaction count
- Interactive Plotly charts:
  - 🥧 Pie chart by category
  - 📊 Bar chart comparison

### 💾 Data Management
- **SQLite backend** (zero-config local DB)
- **Excel export** with year/month filter
- **Resilient deletion logic** to avoid Streamlit sync bugs

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Streamlit |
| Data | Pandas |
| Charts | Plotly Express |
| Database | SQLite3 |
| Export | OpenPyXL |

---

## 🚀 Quick Start

### 1️⃣ Prerequisites
Python **3.8+** installed

### 2️⃣ Installation
```bash
git clone https://github.com/xxx/money-manager.git
cd money-manager
pip install -r requirements.txt
3️⃣ Run the App
bash
Copy code
streamlit run app.py
Then open: http://localhost:8501

📂 Project Structure
plaintext
Copy code
money-manager/
├── app.py              # Main UI & logic
├── database.py         # SQLite CRUD engine
├── finance.db          # Auto-generated local DB
├── requirements.txt    # Dependencies
└── README.md           # Documentation
☁️ Deployment (Streamlit Cloud)
Push to GitHub

Log in to https://share.streamlit.io

New App → select repo

App file path: app.py

Deploy & enjoy mobile access 🎉

📝 Roadmap
Status	Feature
✅	CRUD system
✅	Interactive charts
✅	Stable delete logic
🔜	Google Sheets backend
🔜	Budget alerts
🔜	Income tracking

🤝 Contributing
PRs / issues are welcome! Check the Issues tab for opportunities.

📄 License
MIT License — see LICENSE for details.

Built with ❤️ by Gary Sun