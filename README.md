# 💰 Personal Expense Tracker

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://streamlit.io)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A lightweight, robust, and interactive personal expense tracker built with **Python** and **Streamlit**. Designed to replace complex Excel spreadsheets with a clean UI, rapid data entry, and real-time visualization.

---

## ✨ Key Features

### 🚀 Efficient Workflow
* **Dual Modes**:
    * **➕ Quick Log**: A distraction-free interface designed solely for rapid transaction entry.
    * **📊 Dashboard**: A comprehensive view for data management and analysis.
* **Google Sheets-style Grid**: An editable data table that supports batch entry, inline editing, and deletion.
* **Smart "One-Click" Monthly Reset**: Automatically load recurring fixed expenses (e.g., Rent, Phone Bill) with a single button click in the sidebar.

### 📈 Visual Analysis
* **Real-time Metrics**: Instantly track Total Spent and Transaction Counts.
* **Interactive Charts** (Powered by Plotly):
    * 🥧 **Pie Chart**: Visual breakdown of expenses by category.
    * 📊 **Bar Chart**: Side-by-side comparison of total spending per category.

### 💾 Data Management
* **Robust Backend**: Currently powered by **SQLite** for zero-configuration local storage. (Codebase is extensible to Google Sheets).
* **Excel Export**: Filter your data by year/month and download reports as `.xlsx` files.
* **Bug-Free Deletion**: Implements custom callback logic to resolve Streamlit's common "state synchronization" issues, ensuring deleted rows stay deleted.

---

## 🛠️ Tech Stack

* **Frontend**: [Streamlit](https://streamlit.io/)
* **Data Manipulation**: [Pandas](https://pandas.pydata.org/)
* **Visualization**: [Plotly Express](https://plotly.com/python/plotly-express/)
* **Database**: SQLite3 (Standard Python Library)
* **Export Engine**: OpenPyXL

---

## 🚀 Quick Start

Follow these steps to run the app on your local machine.

### 1. Prerequisites
Ensure you have Python 3.8 or higher installed.

### 2. Installation
Clone this repository or download the files, then navigate to the project directory:

```bash
cd money-manager
Install the required dependencies:

Bash

pip install -r requirements.txt
3. Run the App
Launch the Streamlit server:

Bash

streamlit run app.py
Your default browser should open automatically at http://localhost:8501.

📂 Project Structure
Plaintext

money-manager/
├── app.py              # Main application entry point (UI & Logic)
├── database.py         # Backend logic (SQLite CRUD operations)
├── finance.db          # SQLite database (Auto-generated on first run)
├── requirements.txt    # Project dependencies
└── README.md           # Documentation
☁️ Deployment (How to put it online)
This app is optimized for Streamlit Community Cloud.

Push this code to a GitHub Repository.

Log in to share.streamlit.io.

Click "New App" and select your repository.

Set the main file path to app.py.

Click Deploy!

Now you can access your finance manager from any mobile device via the URL.

📝 Roadmap & To-Do
[x] Implement core CRUD functionality (Create, Read, Update, Delete).

[x] Add interactive visualizations (Pie & Bar charts).

[x] Fix Streamlit state synchronization bugs (Deletion logic).

[ ] v3.0 Upgrade: Migrate backend to Google Sheets for cloud persistence.

[ ] Add budget limit warnings/notifications.

[ ] Add "Income" tracking toggle.

🤝 Contributing
Contributions, issues, and feature requests are welcome! Feel free to check the issues page if you want to contribute.

📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

Built with ❤️ by Gary Sun