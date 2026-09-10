# 💰 Expense Tracker

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://garyexpense.streamlit.app)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A personal expense tracker for a single user (Gary), built with **Streamlit** and **Google
Sheets** as the datastore. Two ways in: a web dashboard for logging and analysis, and a
**Telegram bot** for recording a purchase in one line without opening the app at all.

Live at [garyexpense.streamlit.app](https://garyexpense.streamlit.app).

---

## ✨ What it does

### Streamlit app (`app.py`) — Quick Log + Dashboard
- **Quick Log** — fast entry form for a single transaction, or a one-click "load this
  month's fixed expenses" (rent, phone bill, subscriptions) to skip re-typing recurring costs
- **Dashboard** — an editable data grid (add/edit/delete rows inline), Plotly charts (spend by
  category, by payment method), and a **month-end spending projection** that deliberately
  excludes fixed expenses before projecting — a naive `total ÷ days-elapsed` would be thrown off
  by rent landing on the 1st, so the projection is built from variable spending only
- Password-gated (single shared password via `st.secrets`) — this is a private single-user tool,
  not a multi-account product

### Telegram bot (`api/telegram.py`) — fast manual entry from anywhere
Send a plain-language message, get a row in the sheet and a receipt back:

```
火锅60                    → ✅ $60.00 · 餐饮 (Dine & Grocery) · 今天
chipotle 11.63 9.1        → ✅ $11.63 · 餐饮 (Dine & Grocery) · 09-01
咖啡5, 咖啡6               → two rows, one message
/undo                     → undoes everything the last message wrote
```

An LLM (currently DeepSeek V4 Flash, swappable via env vars) turns the message into structured
data; `/undo` reverses the most recent message (not just the most recent row — a multi-item
message undoes as a unit). Built for the highest-frequency, lowest-friction spending (small daily
purchases) that's the easiest kind of expense to forget to log — see the Roadmap note in
`CLAUDE.md` for why this was prioritized over automating bank-statement imports.

Single-user by design: every webhook request is checked against a secret token and a hardcoded
Telegram user ID; anything else is silently dropped (see `CLAUDE.md`'s webhook security model).

---

## 🛠️ Tech stack

| Layer | Technology |
|---|---|
| Web UI | Streamlit |
| Bot entry point | Plain `http.server.BaseHTTPRequestHandler`, no web framework |
| Datastore | Google Sheets, via `gspread` + a service account |
| NL parsing | An OpenAI-compatible LLM API (DeepSeek V4 Flash by default) |
| Charts | Plotly |
| Data wrangling | Pandas |
| Tests | pytest |

Two independent deploy targets share the same Google Sheet and the same Python modules
(`schema.py`, `sheets.py`, `config.py`) — see **Deployment** below.

---

## 🚀 Running locally

### Streamlit app
```bash
pip install -r requirements.txt
streamlit run app.py
```
Needs `.streamlit/secrets.toml` with a Google service account (`gcp_service_account`), a
`sheet_key`, and an `app_password`. This file is gitignored and must never be committed.

### Telegram bot (webhook handler, not runnable as a standalone server)
```bash
pip install -r requirements-dev.txt          # test tooling + requirements.txt
pip install openai requests                  # the bot's own deps not already in requirements.txt
                                              # (gspread/google-auth/pandas are already pulled
                                              # in above; see pyproject.toml for exact pins)
cp .env.example .env                         # fill in real values
```
See `.env.example` for the full list of variables (Google Sheets, LLM provider, Telegram
secrets, timezone). `scripts/set_webhook.py` registers/inspects/removes the Telegram webhook
once the bot is deployed (`set` / `info` / `delete` subcommands).

### Tests
```bash
pip install -r requirements-dev.txt
pytest                       # Group A: mocked, no network — CI-safe
pytest --run-live -v         # + Group B: hits the real LLM API (needs LLM_* env vars)
```
Group B has genuine output randomness — see `CLAUDE.md`'s testing section for why a single
`--run-live` pass (green or red) isn't conclusive on its own.

---

## 📂 Project structure

```
Expense_Tracker/
├── app.py                # Streamlit UI: Quick Log + Dashboard
├── database.py           # Sheets I/O wrapped with Streamlit caching, for app.py
├── sheets.py              # Pure gspread I/O — no Streamlit/pandas, shared with the bot
├── schema.py              # Single source of truth for the sheet's columns
├── config.py              # Categories, payment methods, timezone helpers — shared config
├── parser.py               # LLM-based natural-language expense parsing
├── bot_handlers.py         # Telegram bot business logic (parse → write → reply, /undo)
├── api/telegram.py         # Telegram webhook entry point (Vercel Function)
├── scripts/                 # One-off migration/backfill/ops tooling, not part of either deploy
├── tests/                    # pytest — Group A (mocked) + Group B (live LLM)
├── requirements.txt          # Streamlit Cloud's dependencies
├── pyproject.toml            # The bot's dependencies (Vercel reads this instead — see below)
├── vercel.json                # Vercel Function config for api/telegram.py
├── .python-version             # Pins Vercel's Python version
└── CLAUDE.md                    # Full design log: every non-obvious decision and why
```

---

## ☁️ Deployment

Two independent targets, from the same repo:

| | Streamlit Cloud | Vercel |
|---|---|---|
| Runs | `app.py` | `api/telegram.py` |
| Deploys on | every push to `main` | manual, from the Vercel dashboard |
| Dependencies from | `requirements.txt` | `pyproject.toml` |
| Python version | set in the Streamlit Cloud dashboard (not a repo file) | `.python-version` |

The repo deliberately keeps **both** `requirements.txt` and `pyproject.toml` at the root —
Vercel's Python builder prefers `pyproject.toml` over a sibling `requirements.txt` when there's
no lockfile, which is what keeps `streamlit`/`plotly` out of the bot's deploy bundle without
needing a subfolder split (both apps import the same `schema.py`/`sheets.py`/`config.py` from
the repo root). Don't "clean this up" into one manifest — see `CLAUDE.md`'s Deployment section
for the full reasoning and the failure mode each file avoids.

Secrets/environment variables are configured on each platform's dashboard, never committed —
see `.env.example` for the full variable list and `CLAUDE.md`'s environment variable table for
which platform needs which.

---

## 📝 Status

- [x] Google Sheets as the datastore (migrated off an earlier local SQLite prototype)
- [x] Quick Log + Dashboard, with month-end projection that excludes fixed expenses
- [x] Telegram bot: natural-language entry, idempotent writes, `/undo`
- [ ] Bank statement import (Chase / Cathay) — see `CLAUDE.md`'s Roadmap for why this comes
      *after* the bot, not before
- [ ] Grouped payment-method charts on the Dashboard (`config.PAYMENT_METHOD_GROUPS` exists,
      not wired into the UI yet)

`CLAUDE.md` is the actual living design doc — every non-obvious decision, past incident, and
rejected alternative is recorded there with its reasoning. This README is the map; that's the
territory.

---

## 📄 License

MIT — see `LICENSE`.

---

Built by **Gary Sun**.
