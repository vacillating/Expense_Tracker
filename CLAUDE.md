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

Google Sheet columns: `id, date, type, category, amount, notes` (as of 2026-08; a 14-column
schema exists in `schema.py` and the live sheet has been migrated to it — `database.py` and
`schema.py` are the source of truth for the full column list, this section is not).

- `id` — UUID, generated on insert
- `type` — currently always `"Expense"`; income was designed for but never implemented
- Amounts are USD

### `date` column gotcha: Sheets silently reformats it, don't compare as strings

The `date` column carries a native Google Sheets `DATE` number format (pattern `yyyy-M-d`, not
zero-padded) that predates this app and applies to the whole column. Writing a zero-padded
string like `"2026-08-24"` with `value_input_option="RAW"` does **not** stop Sheets from
coercing it to a date serial and re-rendering it per the column's existing format — RAW only
blocks re-parsing on a column that has no prior format; it does not override one that already
exists. Net effect: `get_all_records()` can hand back `"2026-8-24"` (no leading zero) even
though the code wrote `"2026-08-24"`.

This is harmless as long as every comparison goes through `pd.to_datetime()` first (unambiguous
regardless of padding, since the year comes first) — which is what `app.py` already does. **It
is not harmless for naive string equality.** Any future date-matching logic (e.g. the planned
Phase 3 CSV-import dedup, matching by amount + date) must parse both sides to real date objects
before comparing — comparing the raw strings will silently miss matches whenever the padding
doesn't happen to line up.

### `granularity` column: transaction vs monthly_summary

Most rows are `granularity="transaction"` — one row, one real purchase. `granularity=
"monthly_summary"` is for when the total is known but the itemized breakdown isn't (a
card statement that can't be exported line-by-line, a channel that didn't get logged that
month, a period nobody got around to entering in detail). This is a general mechanism, not
a one-off special case for any single channel — any future "known total, no receipts"
situation should use it instead of becoming its own bespoke workaround.

Anything that needs itemized data must filter `monthly_summary` out first: daily average,
month-end projection, category charts, Top-N rankings (`app.py`'s `df_filtered_txn` /
`df_current_progress_txn` do this). Anything that only needs a period total — Total Booked,
Spent to Date, a future month-over-month trend — should keep it in.

### `currency` is reserved for USD-only, on purpose — not deleted, not converted

**2026-08 decision:** Gary does the mental conversion to USD at the moment he spends, so
`parser.py` no longer tries to detect currency from wording — `_validate_entry()` forces
`currency = "USD"` on every entry unconditionally (not just a prompt instruction; LLM prompt
compliance isn't guaranteed, so it's enforced in code too, same pattern as the
category/payment_method soft-fallbacks). Words like "块"/"元"/"¥" in a message are just American
slang for dollars in Gary's usage, not a currency signal.

The `currency` column itself is **kept in the schema, not dropped**, even though every new row
will read `"USD"`:
- The sheet already has real historical CNY rows (from the pre-bot manual-entry era and the
  CMB/WeChat backfill) — dropping the column would permanently erase "this number was originally
  RMB" for those rows.
- Column deletion is a destructive migration, strictly more dangerous than adding one (see "Ask
  before schema changes" above) — there's no upside to doing it now.
- Gary expects to move back to China at some point, at which point `currency` starts being CNY
  again for new rows — re-adding a deleted column later would just be paying for this same
  migration twice.

**Existing CNY rows are left as-is — not retroactively converted to USD.** The raw original
amount is the one fact that can't be reconstructed once it's converted (a conversion is lossy;
the reverse isn't recoverable). There's also no single correct rate to convert at — day-of-
transaction rate? The `CNY_PER_USD = 6.72` flat rate used for the 2026-05..08 backfill? Today's
rate? None of these is "more correct" than leaving the number as Gary actually spent it.
`amount_usd` is already populated for every row (including the CNY ones) and is what all
aggregation/summary code sums — converting `amount` itself would not fix anything that's
currently broken.

Net effect: `amount` and `amount_usd` are redundant for every row parser.py writes today (both
always USD) — deliberately not merged into one column, because they'll diverge again the moment
CNY rows start coming back in.

### `payment_method`: record the specific card, group only in config

**2026-08 decision** (prompted by adding two new Bank of America cards): `PAYMENT_METHODS` in
`config.py` stays a flat list of specific values (`"BoA credit"`, `"BoA debit"`, `"CMB credit"`,
etc.) — the schema records exactly which card/channel was used, never a pre-aggregated bucket.

`config.PAYMENT_METHOD_GROUPS` maps each `PAYMENT_METHODS` value to a coarser analysis-only
bucket ("招行(父亲还款)" / "美国卡" / "微信" / "现金"), grouped by *where the money actually came
from* — CMB is money Gary's father fronts in RMB and needs to be told about; every US card draws
from Gary's own USD balance regardless of which bank issued it; cash is the one channel with no
paper trail at all. This mapping is **config-layer only, never written to the sheet** — every
row still stores the specific payment method it always did.

Why grouping lives in config and not in the data: granularity only goes one direction. Data
recorded at the specific-card level can always be rolled up into "美国卡" later, on demand, for
any analysis. Data recorded pre-aggregated as "美国卡" can never be split back into "was this
Chase or BoA" — that information is gone the moment it's written that coarse. Recording specific
and grouping in config keeps every future option open; recording grouped forecloses all of them.

`config.py` enforces `PAYMENT_METHOD_GROUPS` covers every `PAYMENT_METHODS` value at import time
(`RuntimeError` if not) — same defensive pattern as `parser.py`'s payment-method-keyword
completeness check, so a newly added payment method can't silently fall out of every future
group-by chart just because someone forgot to also add it to the grouping dict.

**Not done this round (deliberately deferred):** `app.py`'s Dashboard doesn't use
`PAYMENT_METHOD_GROUPS` yet — grouped charts are the next round's work, this round only prepared
the config.

### Splits / advances-for-others (AA, 垫付) do NOT get their own schema fields

The ledger only ever records the *settled* amount Gary actually kept — never the gross
amount before a split, and never a `funded_by`/`split_with`-style field to track who owes
what. E.g. a $4259 moving-truck rental split with roommates gets logged as whatever Gary's
own share worked out to (say $300), with the context in `notes`
("搬家租车 AA 后自付，Splitwise 有记录") — not as a $4259 row plus some reconciliation field.

Why: large advances are rare (a few times a year, mostly family travel), and Splitwise
already solves the actual settlement problem — there's no gap in the data model to fill.
Building split-tracking into the schema for something this infrequent, with a tool that
already handles it, isn't worth the complexity. Same reasoning as rejecting a `funded_by`
field elsewhere: low-frequency situations with an existing solution don't belong in the
data model.

## Hard rules

- **Never commit secrets.** Credentials live in `.streamlit/secrets.toml` or environment variables. Never inline a key, token, or service account JSON.
- **Never commit** `*.db`, `.DS_Store`, `__pycache__`, or `.streamlit/secrets.toml`.
- **No hardcoded personal values.** Categories, fixed-expense templates, and thresholds belong in config, not scattered through the code.
- **Ask before schema changes.** Adding or renaming a Google Sheet column affects live data and needs a migration plan.

## Data integrity

The Sheets write path has more than one silent-failure mode. "Ask before schema changes" above
and everything in this section are the same lesson: writing to Google Sheets is not a plain
database insert, and each of these failure modes needed its own explicit defense before it
stopped being dangerous.

- **The sheet must never have a Table (表格) object on it.** Google Sheets' `values.append` uses
  table detection to decide where new rows land. A Table object's boundary does **not** expand
  when you append to it — every subsequent write lands at the same row just past the boundary,
  silently overwriting whatever was already there. Check for one after running any migration
  script (Insert menu / right-click a cell → look for "Table" in the context menu, or check
  whether a range shows the Table chip in the sheet UI).
- **`append_row`/`append_rows` must always pass `insert_data_option="INSERT_ROWS"` explicitly**
  (done in `sheets.py`, not `database.py` — see Stack). Leaving it unset doesn't mean "no
  opinion" — it falls through to the Sheets API's own default, which is `OVERWRITE` ("find a
  place to overwrite"), not "append". `gspread` maintainers confirmed in PR #719 that this
  default is kept for backwards compatibility, not because it's a sensible default. INSERT_ROWS
  is a true row insert that doesn't depend on table detection at all — even if a Table object
  reappears on the sheet later, or a blank row sits in the middle of the data, it still can't
  overwrite existing rows.
- **Verifying a write means checking where and how much landed, not just that the field values
  are right.** A corrupted write from this failure mode returns 200, the UI shows "saved", and
  every field in the row is exactly correct — it's just sitting in the wrong row, having erased
  what was there. `sheets.py`'s `_append_and_verify()` parses the API response's `updatedRange`
  and checks the new data landed strictly after the last known row (not merely "no error was
  raised"). It only requires landing *after* the previously-known last row, not at an exact
  predicted row number — Streamlit and the Telegram bot can write to the same sheet concurrently,
  and a write landing further out than predicted just means someone else's row landed first,
  which is fine; landing at or before it means something got overwritten, which isn't.
- **`find()` must be column-scoped**, not a full-sheet search. `sheet.find(id)` with no
  `in_column` will match the same id-shaped string if it ever shows up in `notes` or anywhere
  else, silently editing or deleting the wrong row. `sheets.find_row()` always searches the `id`
  column specifically and raises `RowNotFoundError` instead of returning `None` on a miss — this
  wasn't the cause of the 2026-08 incident, but it's the same category of problem (an API used in
  a way that "looks like it works").

**2026-08 incident, for context:** a Table object (`表格_1`, range A1:F558) existed on the live
sheet. All four Quick Log writes on 8/25 landed on row 559 — every one of them, because the
Table's boundary never moved. Each write overwrote the previous one; 7 rows of real data were
lost this way, with zero errors anywhere in the chain (Sheets API, gspread, `st.error`, the UI).
Fixed by hand: converted the Table to a plain range ("Convert to range", **not** "Delete table" —
that deletes the data too), deleted the corrupted row, verified `Cmd+↓` now lands on the true
last row. Recovering the specific lost row (a late-Nov-2025 backfill entry) is a separate,
manual, read-only-diff-first task — not something automated against the live sheet.

## Timezone

**2026-08 bug, fixed:** `app.py` used `datetime.today()` for "today" — but Streamlit Cloud's
server runs UTC, not Gary's local time. Logging an expense after 8pm EDT recorded tomorrow's
date instead of today's, silently (no error, correct-looking UI). Evidence from the incident: an
entry logged at 21:31 EDT got `date = 2026-08-28` and `created_at = 2026-08-28T01:31:42` — both
one day ahead of the user's actual "today".

Fixed by centralizing every "what is today" call into `config.py`, split into two genuinely
different needs that must not be conflated:

- **User-facing / business-logic dates — `config.today_local()` / `config.now_local()`.** Must
  reflect the user's actual timezone, read from `APP_TIMEZONE` (env var, default
  `America/New_York` — Gary is in Atlanta now but may move; changing timezone should mean
  changing one env var, not redeploying code). Call sites: `app.py`'s Quick Log date default,
  Dashboard's `is_current_month`/`days_passed`, and (once the webhook entrypoint exists) the
  `today` passed into `parser.parse_expense()`. Never call `datetime.today()`/`date.today()`
  directly anywhere else in the project — always go through `config.today_local()`, so timezone
  logic only needs to change in this one place.
- **`created_at` audit timestamps — `config.now_utc_iso()`.** Always UTC, ISO 8601, with an
  explicit `+00:00` marker. Deliberately does *not* follow `APP_TIMEZONE` — an audit timestamp
  records "when this row was written," an absolute instant, and shouldn't shift retroactively if
  the configured timezone ever changes. Convert to local time at display time, if ever needed, not
  at write time. Call sites: `database.py` (`add_transaction`, `add_transactions_bulk`),
  `bot_handlers.py` (`_entry_to_row`), `scripts/backfill_ledger.py`.

**Old `created_at` data — not touched, and not migrated.** Every `created_at` written before this
fix is a bare timestamp with no timezone marker (`2026-08-28T01:31:42`, no `+00:00`). Numerically
these old values *are* UTC (the server was always UTC), so no old data is factually wrong — it's
only missing the explicit marker new rows now carry. Plan: leave old rows as-is; do not
backfill-add `+00:00` to historical `created_at` values. Any code that reads `created_at` should
treat a bare (no-offset) timestamp as UTC and a `+00:00`-suffixed one as also UTC — both parse to
the same instant, so no reader-side branching is actually needed. `bot_handlers.handle_undo()`'s
string-comparison sort of `created_at` is unaffected: it only compares among `source == "telegram"`
rows, a feature that has no historical data predating this fix, so there's no old/new format mix
in that comparison.

`zoneinfo` (stdlib) needs an IANA timezone database to resolve `ZoneInfo("America/New_York")`,
which isn't guaranteed to be present in every deploy container — `tzdata` (pure-Python, universal
wheel) is pinned in `requirements.txt` as a portable fallback, same reasoning as the cp313 wheel
verification below but with no wheel-availability risk since it's not compiled.

## Conventions

- Code and comments in English. UI strings may be Chinese or bilingual — match whatever the surrounding page already uses.
- Prefer small, reviewable changes over large refactors. Explain the reasoning behind a design choice, not just the change.
- Wrap Google Sheets reads in `@st.cache_data` with a short TTL. Every uncached read is a network round trip and the main source of sluggishness.
- Streamlit reruns the whole script on every interaction. Anything expensive needs caching; anything stateful needs `st.session_state`.

## Language

Explain in Chinese — Gary is learning the codebase and needs explanations he can
follow quickly. Code, comments, commit messages, and variable names stay in English.

## Known issues

- **Auth is a single shared password** (`st.secrets["app_password"]`, checked via `check_password()` in `app.py`), not per-user accounts — fine for a single-user app, but no lockout/rate-limiting on wrong attempts.
- **`FIXED_TEMPLATES` matching is fundamentally fragile — three manifestations of the same root cause**: it matches on `(category, amount)` with no notion of *why* two amounts happen to be equal.
  - **Coincidental collision**: a one-off purchase that happens to share a template's exact amount gets mislabeled as recurring (already caught once — a $5.00 shampoo and a $5.00 sleep aid both matched the $5.00 medication template; fixed by hand, not by the algorithm).
  - **Hand-maintained drift**: every template edit is a manual, easy-to-forget step (e.g. the rent template was updated 600→1050 in 2026-08 for a real rent increase — correct, but only because someone remembered to do it).
  - **No time dimension**: the template only holds the *current* amount, not "this amount was correct from date A to date B." After an amount change, every historical row still recorded at the old amount permanently stops matching. This doesn't affect today's month-end projection (it only strips fixed costs from the *current* month; historical months use a simple average instead), but Phase 4's planned month-over-month trend comparison will need to reclassify historical months too, and will misclassify all pre-increase rent rows as variable spending unless this is accounted for.

  Phase 4's "auto-detect recurring from history" is meant to replace this matching scheme — its design needs to handle the same fixed expense changing amount over time, not just recognize a fixed set of `(category, amount)` pairs.
- **Historical CNY backfill (`data/`, `scripts/backfill_ledger.py`) uses a single fixed exchange rate (`CNY_PER_USD = 6.72` in `scripts/build_ledger.py`), not day-by-day rates**, for the whole 2026-05..08 window. Fine for the daily-spend numbers this app cares about (error is cents-level), not accurate enough for precise cross-currency analysis. Revisit if CNY transactions become a larger share of the data.
- No confirmation before row deletion.

## Don't break this

The month-end projection algorithm deliberately strips fixed expenses and projects only from variable spending. This is intentional and better than a naive `total ÷ days_elapsed`. Preserve the behaviour when refactoring.

## Testing

No test suite yet. When adding one, prioritise the projection algorithm and any natural-language parsing — those are the parts where a silent wrong answer is plausible.

### Group B (`tests/test_parser_live.py`, `--run-live`): judge on repeated runs, not one green pass

These hit the real LLM API, so output has genuine sampling randomness — one all-green run does
not mean the behavior is stable. **2026-08 example, exactly why this rule exists:** the old
`test_currency_cny_keyword` (asserting `"奶茶28块"` parses to `currency == "CNY"`) failed twice
in a row, then passed three times in a row, on an unchanged prompt — not a flaky test in the
"bad test" sense, but a real reflection of the model's non-deterministic sampling on a question
that doesn't actually have one correct answer ("块" is ambiguous between RMB and casual English
"bucks" without more context). That test was later removed for an unrelated reason (currency is
now hardcoded to USD, see Data model above), but the lesson about how to *read* Group B results
stands: run `--run-live` more than once (3× is a reasonable default) before concluding a prompt
change did or didn't fix something, and treat a single pass or single failure as inconclusive on
its own.

## Deployment

Pushing to `main` triggers a redeploy on Streamlit Community Cloud. Secrets are configured in the Streamlit Cloud dashboard, not in the repo.

### Cloud Python version — do not assume it matches local

Streamlit Community Cloud runs **Python 3.13.15** as of 2026-08. It does **not**
reliably honor `runtime.txt` — multiple upstream reports (streamlit/streamlit
GitHub issues, discuss.streamlit.io) describe the platform ignoring a pinned
Python version and defaulting to whatever it currently supports. Don't rely on
pinning an older Python to dodge a dependency problem; assume the Cloud
runtime will keep moving forward and pin `requirements.txt` accordingly.

### A container stuck at "Spinning up manager process" needs deleting, not rebooting

If the deploy log stalls indefinitely right after `Spinning up manager process` /
`Preparing system` — before dependency install even starts — a plain reboot from the
Streamlit Cloud dashboard can fail to clear it; the container itself is wedged, not just the
app process. This happened during the 2026-08 pandas/cp313 outage: two reboots and a
re-provision all reproduced the identical stuck state, and the actual `requirements.txt` fix
never got a chance to run because the container never got past provisioning. Deleting the app
and redeploying from scratch got a fresh container that worked on the first try. **Back up the
full contents of the Secrets panel before deleting** — deleting an app does not preserve its
secrets, and there is no way to recover them from Streamlit Cloud after the fact.

### `requirements.txt` pins must be verified against cp313, not local

A version pinned and "verified" only under local Python (e.g. 3.12) can still
be wrong for the deploy target. This caused a real outage: `pandas==2.2.2` was
pinned and tested locally, but that release predates Python 3.13 and has no
`cp313` wheel — `uv pip install` fell back to building it from source on
Streamlit Cloud, which hung for 10+ minutes with **no traceback and no
"Uvicorn server started" line** (the process never got past dependency
installation, so app code never ran).

Verification method that actually catches this, before pushing:

```bash
pip download --only-binary=:all: --python-version 3.13 --implementation cp \
  --abi cp313 --platform manylinux_2_28_x86_64 --platform manylinux2014_x86_64 \
  -d /tmp/wheel_check <every package in requirements.txt, pinned>
```

If this fails to find a wheel for any package (top-level *or* transitive —
check compiled-extension deps like `pandas`/`pyarrow`/`numpy`/`protobuf` in
particular), that pin will trigger a source build on deploy. Note the
platform tag itself can shift between package major versions — pandas 2.x
ships `manylinux2014`/`manylinux_2_17` wheels, pandas 3.x moved to
`manylinux_2_28`; pass both if unsure.

### Streamlit's own version has a Python-3.13 floor and a pandas ceiling

`streamlit==1.37.1` (Aug 2024) predates Streamlit's official Python 3.13
support, added in **1.41.0** (2024-12-10). Independently of that, 1.37.1's
package metadata caps `pandas<3` — pinning it alongside `pandas>=3` is not
just untested, it's a hard install-time conflict. Check a candidate
streamlit version's `requires_dist` (`pip download` metadata or
`https://pypi.org/pypi/streamlit/<version>/json`) for its numpy/pandas/pyarrow
bounds before pinning either side.

### Pinning is not one-and-done

Exact `==` pins give reproducibility and a diffable history, which is why
this repo uses them — but the Cloud Python version moves forward on its own
(see above), and a pin that's fine today can silently stop having a wheel
once the platform's default Python advances. Packages with compiled
extensions (`pandas`, `pyarrow`, `numpy`, and anything else that ships
platform-specific wheels rather than a `py3-none-any` universal one) are the
ones that need periodic re-verification against the current Cloud Python
version — pure-Python dependencies don't have this failure mode.

## Roadmap

**Priority order — corrected 2026-08, after building the CMB historical backfill. The
original assumption (automate the channels first) had it backwards:**

The app's actual core problem is making *manual* entry effortless, not automatically
funneling in every channel. Those two goals are inversely correlated here: the channels
that genuinely *can* be automated (Chase, Cathay — real exports/parseable statements) are
low-frequency, high-amount purchases, where manual entry was never that costly to begin
with. The channel that's actually painful — small, frequent CMB (招商银行副卡) purchases,
several times a day, the easiest kind of spending to forget — has *no* automation surface
at all: no API, a supplementary card whose statement can't be exported line-by-line (only
viewable page by page in 掌上生活), notifications buried in a WeChat official account.
Automating the easy, already-low-friction 20% while leaving the painful, high-friction 80%
manual would optimize the wrong thing.

1. **Telegram bot for fast manual entry.** Not "a feature" — this is the app's actual next
   milestone. It directly attacks the highest-frequency, highest-friction case (CMB daily
   spending), which no amount of channel automation below can ever reach.
2. Chase / Cathay email or statement parsing. Genuinely automatable, stays on the roadmap
   — but *after* the bot, not before it.
3. ~~CMB CSV/summary import~~ — see below. Not an ongoing channel; don't build recurring
   tooling around it.

### Telegram bot: `parser.py` latency (measured 2026-08)

11 live calls to DeepSeek V4 Flash (`tests/test_parser_live.py --run-live`) took 39s total,
~3.5s average per call. Add one `sheets.get_column()` read (idempotency check) and one
`sheets.append_rows()` write, and the full webhook chain (Telegram → parse → write → reply)
should land around **5–6s end to end**. Use this number when picking a serverless platform and
setting its timeout — it needs enough headroom over 5–6s to survive a slower LLM response
without the platform killing the function mid-write.

### CMB backfill — one-time, 2026-05..08 historical catch-up only, obsolete once imported

These notes describe how the *already-completed* 4-month gap was reconstructed
(`scripts/build_ledger.py`, `data/ledger_v3_20260501_20260823.csv`). They are **not** a
standing convention — Gary will not be pulling CMB statements again, so none of this should
be generalized into a recurring mechanism or built into future tooling.

- 掌上生活 (CMB's app) can't export a supplementary card's transactions — only viewable
  page by page. The only number actually available per period is a monthly total.
- That monthly total is *gross* — it includes money advanced on behalf of other people
  (e.g. $1,552.73 in August alone, tracked separately in Splitwise). Importing it as-is
  would badly inflate recorded spending and break the projection/daily-average math.
- Advances are spread across multiple cards, so a Splitwise total can't just be subtracted
  from one card's gross total — only Gary can determine which advances actually hit the CMB
  card specifically.
- Net = CMB gross − (advances that hit this card, per Splitwise) − (large one-off items
  already logged separately, e.g. moving-truck rental, insurance). What's left is the
  unavoidably-un-itemized day-to-day spending (food, rides, groceries), logged as one
  `granularity=monthly_summary` row per month.
- CMB's billing cycle is not the calendar month (the "8月消费" total covers Jul 8–Aug 7,
  not Aug 1–31) — keep that in mind when picking a date and writing the `notes` for each
  summary row.

## TODO

- [ ] Manually log the CMB 2026-05..08 net monthly summaries (`granularity=monthly_summary`)
      — decide the date-per-row convention and how `notes` states the actual billing-cycle
      range before entering them (see CMB backfill notes above).
- [ ] Resolve the two disputed $36 backfill rows (SUSHI LOVER 5/4, Zelle→Caroline Kuo 5/6) —
      held out of the import, need to check real bank records before deciding whether either
      is a duplicate of the existing "韩餐" row.
- [ ] Move `CATEGORIES` / `FIXED_TEMPLATES` / `PAYMENT_METHODS` out of `app.py` into a
      dedicated config module — they're all "no hardcoded personal values" territory per
      the Hard rules above, currently just living directly in `app.py` by precedent.
- [ ] `FIXED_TEMPLATES` has no time dimension (see Known issues) — rent went 600→1050 in
      2026-08 and every historical row at the old amount now permanently fails to match.
      Phase 4's trend analysis needs to account for this before it can trust historical
      "was this recurring" classification.
- [ ] `amount` is deliberately not editable in the data_editor grid (`disabled=True`) — 2026-08
      decision, not an oversight. Editing amount raises a real question (does `currency`/
      `amount_usd` need to change too?) that got deferred to unblock category/notes/
      payment_method/date editing, which was needed immediately. When this gets designed:
      either force `currency` to be edited in the same action, or add a separate "recompute
      amount_usd at today's rate" button — don't just let `amount` drift out of sync with
      `amount_usd`. Until then, a wrong amount gets deleted and re-entered via Quick Log.
