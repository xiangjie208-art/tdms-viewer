import csv
from pathlib import Path

import numpy as np
import pytest
from nptdms import ChannelObject, TdmsWriter

from tdms_fingerprint_viewer.exporting import (
    FEATURE_COLUMNS,
    IT_COLUMNS,
    region_export_basename,
    safe_filename_component,
    write_feature_csv,
    write_it_raw_csv,
)


def test_export_filename_combines_file_interval_note_and_sanitizes_windows_characters():
    region = {
        "file_name": "sample:01.tdms",
        "start_s": 1.25,
        "end_s": 2.5,
        "note": "周期/信号?",
    }
    assert region_export_basename(region) == "sample_01_1.25000-2.50000s_周期_信号_"
    assert safe_filename_component("CON", "fallback") == "_CON"
    assert safe_filename_component("  ", "无备注") == "无备注"


def test_feature_csv_keeps_region_summary_columns(tmp_path: Path):
    path = tmp_path / "feature.csv"
    region = {
        "file": "sample_1.tdms", "channel": "Current/ai0",
        "start_s": 0.2, "end_s": 0.4, "tag": "候选", "note": "测试",
        "statistics": {"mean": 2.0, "std": 1.0, "min": 1.0, "max": 3.0, "ptp": 2.0},
        "peaks": [[10.0, 0.5]],
    }
    write_feature_csv(path, [region])

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == FEATURE_COLUMNS
    assert rows[1][:6] == ["sample_1.tdms", "Current/ai0", "0.2", "0.4", "候选", "测试"]


def test_it_raw_csv_contains_exact_saved_interval_samples(tmp_path: Path):
    data_folder = tmp_path / "data"
    data_folder.mkdir()
    tdms_path = data_folder / "sample_1.tdms"
    values = np.arange(10, dtype=float)
    channel = ChannelObject(
        "Current", "Dev1/ai0", values,
        properties={"wf_increment": 0.1, "unit_string": "A"},
    )
    with TdmsWriter(tdms_path) as writer:
        writer.write_segment([channel])
    region = {
        "file": str(tdms_path), "file_name": tdms_path.name,
        "channel": "Current/Dev1/ai0", "start_s": 0.2, "end_s": 0.4,
        "start_index": 2, "end_index_exclusive": 5, "note": "原始区间",
    }
    output = tmp_path / "I-T_raw_data.csv"

    row_count, warnings = write_it_raw_csv(output, [region], data_folder)

    assert row_count == 3
    assert warnings == []
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == IT_COLUMNS
    assert [float(row["time_s"]) for row in rows] == pytest.approx([0.2, 0.3, 0.4])
    assert [float(row["current"]) for row in rows] == [2.0, 3.0, 4.0]
    assert {row["current_unit"] for row in rows} == {"A"}


def test_it_raw_csv_reports_missing_source_without_failing(tmp_path: Path):
    output = tmp_path / "I-T_raw_data.csv"
    region = {"file": "missing.tdms", "file_name": "missing.tdms"}

    row_count, warnings = write_it_raw_csv(output, [region], tmp_path)

    assert row_count == 0
    assert warnings == ["找不到原始文件：missing.tdms"]
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert next(csv.reader(handle)) == IT_COLUMNS
