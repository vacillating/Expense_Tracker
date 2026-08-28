"""
tests/test_sheets.py — 2026-08 数据丢失事故的回归测试。mock 掉 gspread，
不碰真实 Sheets。

事故经过：表里存在一个 Google Sheets 表格(Table)对象，边界锁死在
A1:F558 不随写入扩展；append_row/append_rows 没有显式传
insert_data_option，落到 Sheets API 自己的默认值 OVERWRITE。连续 4 次
Quick Log 写入全部精确覆盖了第 559 行——每次都 200 成功、字段全部正确、
UI 显示已保存，没有任何报错，丢了 7 笔账。

这个文件要钉住两件事：insert_data_option 确实被传了 INSERT_ROWS（不会
被以后的重构悄悄弄丢），以及写入落点校验确实会拦下"覆盖而不是追加"的
情况（不会退化回原来那种"API 不报错就当成功"的沉默失败）。
"""
from unittest.mock import MagicMock

import pytest

import sheets
from schema import HEADERS


def _resp(updated_range: str) -> dict:
    return {"updates": {"updatedRange": updated_range}}


def _mock_sheet(existing_data_rows: int):
    """existing_data_rows 是不含表头的现有数据行数——决定 col_values("id")
    返回多长的列表（第一个是表头本身，get_column 会把它去掉）。"""
    sheet = MagicMock()
    sheet.col_values.return_value = ["id"] + [f"row{i}" for i in range(existing_data_rows)]
    return sheet


# ---------------------------------------------------------- insert_data_option

def test_append_row_passes_insert_data_option_insert_rows():
    sheet = _mock_sheet(existing_data_rows=0)
    sheet.append_rows.return_value = _resp("'Sheet1'!A2:O2")

    sheets.append_row(sheet, {"id": "x"})

    _, kwargs = sheet.append_rows.call_args
    assert kwargs.get("insert_data_option") == "INSERT_ROWS"
    assert kwargs.get("value_input_option") == "RAW"


def test_append_rows_passes_insert_data_option_insert_rows():
    sheet = _mock_sheet(existing_data_rows=0)
    sheet.append_rows.return_value = _resp("'Sheet1'!A2:O3")

    sheets.append_rows(sheet, [{"id": "x"}, {"id": "y"}])

    _, kwargs = sheet.append_rows.call_args
    assert kwargs.get("insert_data_option") == "INSERT_ROWS"


def test_append_row_delegates_to_append_rows_not_gspreads_append_row():
    """gspread 的 Worksheet.append_row 本身没有落点校验——这里必须走我们
    自己校验过的 append_rows 路径，不能直接调 sheet.append_row()。"""
    sheet = _mock_sheet(existing_data_rows=0)
    sheet.append_rows.return_value = _resp("'Sheet1'!A2:O2")

    sheets.append_row(sheet, {"id": "x"})

    sheet.append_row.assert_not_called()
    sheet.append_rows.assert_called_once()


# --------------------------------------------------------- 落点/行数校验

def test_write_landing_on_existing_row_raises_not_silent():
    """核心回归测试：模拟"写入落点不在表末尾"（等同于事故里被 Table 对象
    锁死落点、精确覆盖第 559 行的场景）——必须抛异常，不能像原来那样
    悄悄"成功"。"""
    sheet = _mock_sheet(existing_data_rows=558)  # 已有 558 行数据（跟事故对上）
    # 模拟被覆盖：新数据"落"在第 559 行——但 559 正好是已有数据的最后一行
    # （表头1 + 数据558 = 到第559行为止），不是追加到第560行。
    sheet.append_rows.return_value = _resp("'Sheet1'!A559:O559")

    with pytest.raises(sheets.WriteVerificationError):
        sheets.append_row(sheet, {"id": "new_but_overwrites"})


def test_write_landing_before_existing_data_raises():
    sheet = _mock_sheet(existing_data_rows=558)
    sheet.append_rows.return_value = _resp("'Sheet1'!A2:O2")  # 落在第2行，远早于已有数据

    with pytest.raises(sheets.WriteVerificationError):
        sheets.append_row(sheet, {"id": "x"})


def test_write_landing_past_existing_data_does_not_raise():
    """正常追加：落点在已知数据之后，必须放行，不能误报。"""
    sheet = _mock_sheet(existing_data_rows=558)
    sheet.append_rows.return_value = _resp("'Sheet1'!A560:O560")  # 正确落在第560行

    sheets.append_row(sheet, {"id": "x"})  # 不应该抛异常


def test_write_landing_further_than_expected_tolerated_as_concurrent_write():
    """并发写入的容错：Streamlit app 和以后的 Telegram bot 会并发写同一张
    表，后写的那个落点会比自己预判的更靠后——这是正常的并发增长，不是
    覆盖，不该被当成异常拦下来。只要落点在"已知数据"之后，不管超出预期
    多少行都该放行。"""
    sheet = _mock_sheet(existing_data_rows=10)
    # 预判应该落在第12行，但因为期间有别的写入插了几行，实际落在第20行
    sheet.append_rows.return_value = _resp("'Sheet1'!A20:O20")

    sheets.append_row(sheet, {"id": "x"})  # 不应该抛异常


def test_row_count_mismatch_raises():
    """预期写 2 行，但 updatedRange 只覆盖了 1 行——同样不能静默通过。"""
    sheet = _mock_sheet(existing_data_rows=0)
    sheet.append_rows.return_value = _resp("'Sheet1'!A2:O2")  # 只有 1 行

    with pytest.raises(sheets.WriteVerificationError):
        sheets.append_rows(sheet, [{"id": "x"}, {"id": "y"}])


def test_multi_row_append_landing_correctly_does_not_raise():
    sheet = _mock_sheet(existing_data_rows=5)
    sheet.append_rows.return_value = _resp("'Sheet1'!A7:O8")  # 表头1+已有5=到第6行，新2行落在7-8

    sheets.append_rows(sheet, [{"id": "x"}, {"id": "y"}])  # 不应该抛异常


def test_malformed_updated_range_raises_not_silent():
    sheet = _mock_sheet(existing_data_rows=0)
    sheet.append_rows.return_value = _resp("garbage, no row numbers here")

    with pytest.raises(sheets.WriteVerificationError):
        sheets.append_row(sheet, {"id": "x"})


# --------------------------------------------------------------- find_row

def test_find_row_searches_id_column_only():
    sheet = MagicMock()
    sheet.find.return_value = MagicMock(row=42)

    cell = sheets.find_row(sheet, "abc-123")

    id_col = HEADERS.index("id") + 1
    sheet.find.assert_called_once_with("abc-123", in_column=id_col)
    assert cell.row == 42


def test_find_row_raises_explicit_error_when_not_found():
    """gspread 的 find() 本身找不到就返回 None，不抛异常——不能让这个 None
    悄悄流到调用方，得在这里就变成一个明确的异常。"""
    sheet = MagicMock()
    sheet.find.return_value = None

    with pytest.raises(sheets.RowNotFoundError):
        sheets.find_row(sheet, "does-not-exist")


def test_find_row_does_not_match_id_fragment_appearing_in_notes():
    """回归测试：如果 find() 不限定列，某一行 notes 里恰好包含了另一行的
    id，会被错误匹配到那一行，改错/删错都不会报错。这里用一个模拟了
    "Sheets 按列过滤"真实语义的 fake find()，证明限定 in_column 之后
    不会被 notes 里出现的 id 误伤。"""
    target_id = "abc-123"
    other_id = "xyz-999"
    id_col = HEADERS.index("id") + 1
    notes_col = HEADERS.index("notes") + 1

    # 第 1 行：id 是 other_id，notes 里恰好写着 target_id（比如备注里贴了
    # 另一笔的 id 做参照）。第 2 行：id 真的是 target_id。
    rows = {
        1: {id_col: other_id, notes_col: f"参考另一笔 {target_id}"},
        2: {id_col: target_id, notes_col: "正常备注"},
    }

    def fake_find(query, in_column=None, **kwargs):
        for row_num, cols in rows.items():
            if cols.get(in_column) == query:
                return MagicMock(row=row_num)
        return None

    sheet = MagicMock()
    sheet.find.side_effect = fake_find

    cell = sheets.find_row(sheet, target_id)
    assert cell.row == 2  # 命中真正 id=target_id 的那一行，不是 notes 里提到它的第1行
