# CLAUDE.md

Personal expense tracker. Streamlit frontend, Google Sheets as the datastore. Single user (Gary), deployed on Streamlit Community Cloud at `garyexpense.streamlit.app`.

## Stack

- **Streamlit** — UI, two pages: Quick Log (entry) and Dashboard (analysis)
- **Google Sheets** — datastore, accessed via `gspread` + `ServiceAccountCredentials`
- **Plotly** — charts

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Requires `.streamlit/secrets.toml` with Google service account credentials. This file is gitignored and must never be committed.

## Data model

Google Sheet columns: `id, date, type, category, amount, notes`

- `id` — UUID, generated on insert
- `type` — currently always `"Expense"`; income was designed for but never implemented
- Amounts are USD

## Hard rules

- **Never commit secrets.** Credentials live in `.streamlit/secrets.toml` or environment variables. Never inline a key, token, or service account JSON.
- **Never commit** `*.db`, `.DS_Store`, `__pycache__`, or `.streamlit/secrets.toml`.
- **No hardcoded personal values.** Categories, fixed-expense templates, and thresholds belong in config, not scattered through the code.
- **Ask before schema changes.** Adding or renaming a Google Sheet column affects live data and needs a migration plan.

## Conventions

- Code and comments in English. UI strings may be Chinese or bilingual — match whatever the surrounding page already uses.
- Prefer small, reviewable changes over large refactors. Explain the reasoning behind a design choice, not just the change.
- Wrap Google Sheets reads in `@st.cache_data` with a short TTL. Every uncached read is a network round trip and the main source of sluggishness.
- Streamlit reruns the whole script on every interaction. Anything expensive needs caching; anything stateful needs `st.session_state`.

## Language

Explain in Chinese — Gary is learning the codebase and needs explanations he can
follow quickly. Code, comments, commit messages, and variable names stay in English.

## Known issues

- **No authentication.** The app is publicly reachable and anyone with the URL can read and write data. Highest priority.
- **Medical category is hardcoded as always-fixed**, so one-off medical charges are wrongly excluded from the variable-spending average.
- **`FIXED_TEMPLATES` is hand-maintained** and matches on `(category, amount)` — fragile.
- **Stale files in the repo:** `finance.db` (superseded by Google Sheets), `check_db.py` (debug leftover), `.DS_Store`.
- No confirmation before row deletion.

## Don't break this

The month-end projection algorithm deliberately strips fixed expenses and projects only from variable spending. This is intentional and better than a naive `total ÷ days_elapsed`. Preserve the behaviour when refactoring.

## Testing

No test suite yet. When adding one, prioritise the projection algorithm and any natural-language parsing — those are the parts where a silent wrong answer is plausible.

## Deployment

Pushing to `main` triggers a redeploy on Streamlit Community Cloud. Secrets are configured in the Streamlit Cloud dashboard, not in the repo.
