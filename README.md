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
- **Google Sheets-style grid** for inline editing, batch entry, and deletion
- **One-click Monthly Reset** – auto-load recurring fixed expenses (e.g., rent, phone bill)

### 📈 Visual Analysis
- **Real-time metrics**: total spent + transaction count
- Interactive Plotly charts:
  - 🥧 **Pie chart**: expense breakdown by category
  - 📊 **Bar chart**: category spending comparison

### 💾 Data Management
- **SQLite backend** (zero-config local storage)
- **Excel export** with year/month filters
- **Robust deletion logic** to avoid Streamlit state sync bugs (deleted rows stay deleted)

---

## 🛠️ Tech Stack

| Layer     | Technology      |
|----------|-----------------|
| Frontend | Streamlit       |
| Data     | Pandas          |
| Charts   | Plotly Express  |
| Database | SQLite3         |
| Export   | OpenPyXL        |

---

## 🚀 Quick Start

### 1️⃣ Prerequisites
- Python **3.8+** installed

### 2️⃣ Installation
```bash
git clone https://github.com/your-username/money-manager.git
cd money-manager
pip install -r requirements.txt
```

### 3️⃣ Run the App
```bash
streamlit run app.py
```

Then open: <http://localhost:8501>

---

## 📂 Project Structure
```plaintext
money-manager/
├── app.py              # Main application entry point (UI & logic)
├── database.py         # SQLite CRUD operations
├── finance.db          # SQLite database (auto-generated on first run)
├── requirements.txt    # Project dependencies
└── README.md           # Documentation
```

---

## ☁️ Deployment (Streamlit Community Cloud)

1. Push this code to a **GitHub repository**
2. Log in to https://share.streamlit.io
3. Click **“New app”** and select your repository
4. Set **Main file path** to: `app.py`
5. Click **Deploy**

You can now access your finance manager from any device via the generated URL 🎉

---

## 📝 Roadmap & To-Do

- [x] Implement core CRUD functionality (Create, Read, Update, Delete)
- [x] Add interactive visualizations (Pie & Bar charts)
- [x] Fix Streamlit state synchronization bugs (deletion logic)
- [ ] v3.0: Migrate backend to Google Sheets for cloud persistence
- [ ] Add budget limit warnings/notifications
- [ ] Add optional “Income” tracking

---

## 🤝 Contributing
Contributions, issues, and feature requests are welcome!  
Feel free to open an issue or submit a pull request.

---

## 📄 License
This project is licensed under the **MIT License** – see the `LICENSE` file for details.

---

Built with ❤️ by **Gary Sun**
