"""
sheets.py — pure gspread connection + row I/O. No Streamlit import, no pandas.

Exists so the Telegram bot (a serverless function: no Streamlit runtime, and
too size/cold-start-constrained to bundle streamlit+pandas) can read/write
the same sheet as the Streamlit app without importing either.

database.py wraps everything here with @st.cache_data/@st.cache_resource and
turns the raw dict rows into a DataFrame for the app. This is the one place
that knows how to open the sheet and shape a row — always via
schema.row_from_dict(), never by hand-listing positional values (that was
the original sin behind the 6->14 column migration, see CLAUDE.md).
"""
from __future__ import annotations

import json
import os
import re

import gspread
from google.oauth2.service_account import Credentials

from schema import HEADERS, row_from_dict

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class WriteVerificationError(Exception):
    """写入的 API 调用本身没报错，但落点校验发现不对劲。

    2026-08 事故：表里存在一个 Google Sheets 表格(Table)对象，边界锁死在
    A1:F558 且不随写入扩展；append_row/append_rows 没有显式传
    insert_data_option，落到 Sheets API 自己的默认值 OVERWRITE。结果是
    连续 4 次 Quick Log 写入全部精确覆盖了第 559 行——每次都 200 成功、
    字段全部正确、UI 显示"已保存"，没有任何报错，丢了 7 笔账。
    被覆盖的行字段是对的，只有校验"新行落在哪、写了几行"才能抓到这种
    错误，光校验字段内容抓不到。"""


class RowNotFoundError(Exception):
    """按 id 在 id 列里没找到对应行。"""


_ROW_FROM_CELL_RE = re.compile(r"[A-Za-z]+\$?(\d+)")


def _row_range_from_updated_range(updated_range: str) -> tuple[int, int]:
    """从 API 返回的 updatedRange（比如 "'Sheet1'!A559:O559" 单行，或
    "'Sheet1'!A559:O560" 多行）解析出 (起始行号, 结束行号)。

    注意："!" 只出现一次（分隔 sheet 名和范围），不是 A1/O2 两个格子各有
    一个——先按 "!" 切一刀去掉 sheet 名前缀，再从剩下的 "A559:O560" 里
    分别抓两个格子的行号。"""
    range_part = updated_range.rsplit("!", 1)[-1]
    rows = [int(n) for n in _ROW_FROM_CELL_RE.findall(range_part)]
    if not rows:
        raise WriteVerificationError(f"无法从 updatedRange 解析出行号: {updated_range!r}")
    return min(rows), max(rows)


def _gcp_service_account_info() -> dict:
    """环境变量优先，读不到再回落到 st.secrets。让同一份代码在 Streamlit Cloud
    （有 st.secrets）和 serverless（比如 Telegram bot，很可能连 streamlit 都
    没装）两边都能跑。streamlit 只在真的要回落时才 import，不是硬依赖——
    serverless 环境下这行 import 永远不会被执行到。"""
    raw = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    import streamlit as st
    return dict(st.secrets["gcp_service_account"])


def _sheet_key() -> str:
    key = os.environ.get("SHEET_KEY")
    if key:
        return key
    import streamlit as st
    return st.secrets["sheet_key"]


def connect():
    """连接真实 Google Sheet，返回 gspread Worksheet（gid=0 那个分页）。"""
    info = _gcp_service_account_info()
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(_sheet_key())
    # gid=0，不是 .sheet1——见 CLAUDE.md：migrate 脚本建的备份分页会占用索引 0，
    # 把真实数据分页挤到索引 1，.sheet1（按索引取）会连到备份而不是真实数据。
    return spreadsheet.get_worksheet_by_id(0)


def get_all_records(sheet) -> list[dict]:
    """原始行，list[dict]，key 是当前表头。不做任何类型转换——那是
    database.py（给 app 用）或 schema.parse_row()（给逐行解析用）的事，
    这一层只管把 Sheets 的数据原样拿出来。"""
    return sheet.get_all_records()


def get_column(sheet, column_name: str) -> list[str]:
    """只读某一列的全部值，不读整张表——用于只需要一列内容的场景（比如
    Telegram bot 的幂等性检查：只是要看某个 external_id 存不存在，没必要
    把 15 列 × 全部行都拉下来）。列位置从 schema.HEADERS 推导，不硬编码
    列号——加列/挪列的时候这里不用跟着改。"""
    col_idx = HEADERS.index(column_name) + 1  # gspread 列号从 1 开始
    values = sheet.col_values(col_idx)
    return values[1:] if values else []  # 去掉表头那一行


def append_row(sheet, row_dict: dict) -> None:
    _append_and_verify(sheet, [row_from_dict(row_dict)])


def append_rows(sheet, row_dicts: list[dict]) -> None:
    _append_and_verify(sheet, [row_from_dict(d) for d in row_dicts])


def _append_and_verify(sheet, rows: list[list]) -> None:
    """真正做写入的地方（append_row/append_rows 都只是包一层调这个）。

    insert_data_option="INSERT_ROWS" 是必须显式传的——见 WriteVerificationError
    的说明，这是 2026-08 事故的直接修复。INSERT_ROWS 是真正的行插入，完全
    不依赖 Sheets 的 table detection，就算表里以后又出现 Table 对象、或者
    中间夹着空行，也不会覆盖任何已有数据。

    写完之后还要校验落点，不能只信任"API 没报错"——被覆盖的那次写入同样
    没报错。校验逻辑：新数据必须落在"当前已知的最后一行"之后，不能落在
    等于或早于它的位置（那就是覆盖）。故意不要求"精确等于预期的下一行"，
    因为 Streamlit 和以后的 Telegram bot 会并发写同一张表——如果两边前后
    脚写入，后写的那个落点会比自己预判的更靠后，这是正常的并发增长，不是
    错误，不该被当成异常拦下来。
    """
    existing_rows = len(get_column(sheet, "id"))  # 不含表头
    last_known_row = existing_rows + 1  # +1 表头

    response = sheet.append_rows(rows, value_input_option="RAW", insert_data_option="INSERT_ROWS")
    updated_range = response["updates"]["updatedRange"]
    start_row, end_row = _row_range_from_updated_range(updated_range)

    if start_row <= last_known_row:
        raise WriteVerificationError(
            f"写入落点异常：新数据落在第 {start_row} 行，但已知数据到第 "
            f"{last_known_row} 行为止——这意味着写入覆盖了已有数据，不是"
            f"追加。updatedRange={updated_range!r}。没有自动重试或修复，"
            f"因为在不确定安全的情况下自己重试可能造成二次覆盖；需要人工"
            f"检查表里是不是又出现了 Table 对象（见 CLAUDE.md 数据完整性）。"
        )
    if end_row - start_row + 1 != len(rows):
        raise WriteVerificationError(
            f"写入行数异常：预期写 {len(rows)} 行，updatedRange 实际覆盖了 "
            f"{end_row - start_row + 1} 行（{updated_range!r}）。"
        )


def find_row(sheet, transaction_id: str):
    """按 id 在 id 列里找单元格——只在这一列搜，不是全表搜索。全表搜索的
    问题：如果某个 UUID 片段意外出现在 notes 里，或者表里有重复值，会
    匹配到错误的行，改错/删错都不会报错。找不到时抛明确异常，不静默
    返回 None（gspread 的 find() 本身找不到就返回 None，不抛异常）。"""
    id_col = HEADERS.index("id") + 1
    cell = sheet.find(transaction_id, in_column=id_col)
    if cell is None:
        raise RowNotFoundError(f"id 列里没有找到: {transaction_id!r}")
    return cell


def delete_row(sheet, transaction_id: str) -> None:
    cell = find_row(sheet, transaction_id)
    sheet.delete_rows(cell.row)


def update_row(sheet, transaction_id: str, **fields) -> None:
    """按 id 找到那一行，只更新传入的字段，一次 batch_update（不管改几个
    字段都只打一次 API）。fields 的 key 必须是 schema.HEADERS 里的列名。"""
    cell = find_row(sheet, transaction_id)
    row = cell.row
    updates = []
    for field, value in fields.items():
        col_idx = HEADERS.index(field) + 1  # gspread 列号从 1 开始
        a1 = gspread.utils.rowcol_to_a1(row, col_idx)
        updates.append({"range": a1, "values": [[value]]})
    if updates:
        sheet.batch_update(updates, raw=True)
