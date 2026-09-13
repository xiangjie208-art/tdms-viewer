import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from nptdms import ChannelObject, TdmsWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget

from tdms_fingerprint_viewer.main_window import MainWindow
from tdms_fingerprint_viewer.exporting import DEFAULT_EXPORT_OPTIONS


def test_main_window_constructs_with_original_four_panel_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.settings_path == tmp_path / "state" / "settings.json"
    assert isinstance(window.controls, QTabWidget)
    assert window.controls.count() == 3
    assert window.start_time_spin is not None
    assert window.end_time_spin is not None
    assert window.duration_time_spin is not None
    assert window.save_progress_button is not None
    assert window.open_session_button is not None
    assert window.export_combined_button is not None
    assert window.detail_plot.toolTip() == "左键框选；右键拖动；滚轮缩放。"
    assert window.start_time_spin.toolTip() == "局部窗口起点；超过终点时同步调整终点。"
    window.session = None
    window.current_path = None
    window.close()
    app.processEvents()


def test_processing_controls_and_unsaved_note_are_captured_automatically(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    data_folder = tmp_path / "data"; data_folder.mkdir()
    current_path = data_folder / "sample.tdms"
    window = MainWindow(); window.data_folder = data_folder; window.current_path = current_path
    window.session = {
        "data_folder": str(data_folder), "file_marks": {}, "file_notes": {}, "regions": [],
        "processing": {
            "time_unit_index": 1, "fft_scope": "完整文件", "spectrum_mode": "功率谱密度 (Welch)",
            "window": "Blackman", "log_x": False, "log_y": True, "blank_overlay": False,
        },
    }
    window._apply_processing_controls()
    window.note_edit.setPlainText("尚未点击保存的备注")

    assert window.time_unit_combo.currentIndex() == 1
    assert window.fft_scope_combo.currentText() == "完整文件"
    assert window.spectrum_mode_combo.currentText() == "功率谱密度 (Welch)"
    assert window.window_combo.currentText() == "Blackman"
    assert window.log_x_check.isChecked() is False
    assert window.blank_overlay_check.isChecked() is False
    assert window.session["file_notes"]["sample.tdms"] == "尚未点击保存的备注"
    window.session = None; window.close(); app.processEvents()


def test_open_data_folder_restores_last_file_and_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    data_folder = tmp_path / "data"; data_folder.mkdir()
    (data_folder / "sample_1.tdms").touch(); (data_folder / "sample_2.tdms").touch()
    state = {
        "data_folder": str(data_folder), "file_marks": {}, "file_notes": {}, "regions": [],
        "processing": {"current_file": "sample_2.tdms", "current_channel": "Current/ai1"},
    }
    window = MainWindow(); loaded = []
    window.load_current_file = lambda path, channel_key=None: loaded.append((Path(path).name, channel_key))

    window.open_data_folder(data_folder, session_override=state)

    assert window.file_list.currentRow() == 1
    assert loaded == [("sample_2.tdms", "Current/ai1")]
    window.session = None; window.close(); app.processEvents()


def test_combined_plot_pixmap_uses_vertical_global_and_local_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow(); window.current_path = tmp_path / "sample.tdms"
    window.current_channel = SimpleNamespace(key="Current/ai0", dt=0.01)
    window.current_indices = (10, 40); window.note_edit.setPlainText("组合图")

    pixmap = window.combined_plot_pixmap()

    assert not pixmap.isNull()
    assert pixmap.height() > pixmap.width() * 0.8
    window.session = None; window.close(); app.processEvents()


def test_region_table_supports_batch_selection_and_deletion(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.session = {
        "data_folder": "",
        "regions": [
            {"id": "one", "file_name": "one.tdms", "start_s": 0.0, "end_s": 1.0},
            {"id": "two", "file_name": "two.tdms", "start_s": 1.0, "end_s": 2.0},
            {"id": "three", "file_name": "three.tdms", "start_s": 2.0, "end_s": 3.0},
        ],
    }
    window.refresh_region_table()
    selection = window.region_table.selectionModel()
    flags = QItemSelectionModel.Select | QItemSelectionModel.Rows
    selection.select(window.region_table.model().index(0, 0), flags)
    selection.select(window.region_table.model().index(2, 0), flags)
    assert window.selected_region_ids() == ["one", "three"]
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

    window.delete_selected_region()

    assert [region["id"] for region in window.session["regions"]] == ["two"]
    window.session = None
    window.close()
    app.processEvents()


def test_result_bundle_uses_new_csv_names_and_readable_snapshot_names(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    data_folder = tmp_path / "data"
    export_parent = tmp_path / "exports"
    data_folder.mkdir(); export_parent.mkdir()
    tdms_path = data_folder / "sample_1.tdms"
    channel = ChannelObject(
        "Current", "Dev1/ai0", np.arange(5, dtype=float),
        properties={"wf_increment": 0.1, "unit_string": "A"},
    )
    with TdmsWriter(tdms_path) as writer:
        writer.write_segment([channel])
    overview_snapshot = tmp_path / "overview.png"; overview_snapshot.write_bytes(b"overview")
    time_snapshot = tmp_path / "time.png"; time_snapshot.write_bytes(b"time")
    spectrum_snapshot = tmp_path / "spectrum.png"; spectrum_snapshot.write_bytes(b"spectrum")
    combined_snapshot = tmp_path / "combined.png"; combined_snapshot.write_bytes(b"combined")
    region = {
        "id": "region", "file": str(tdms_path), "file_name": tdms_path.name,
        "channel": "Current/Dev1/ai0", "start_s": 0.1, "end_s": 0.3,
        "start_index": 1, "end_index_exclusive": 4, "tag": "候选", "note": "测试",
        "statistics": {}, "peaks": [], "overview_snapshot": str(overview_snapshot),
        "time_snapshot": str(time_snapshot), "spectrum_snapshot": str(spectrum_snapshot),
        "combined_snapshot": str(combined_snapshot),
    }
    window = MainWindow()
    window.data_folder = data_folder
    window.session = {
        "data_folder": str(data_folder), "file_marks": {}, "file_notes": {},
        "regions": [region],
    }
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(
        "tdms_fingerprint_viewer.main_window.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(export_parent),
    )

    window._export_regions(
        [region], selected_only=False, options=DEFAULT_EXPORT_OPTIONS,
        destination_parent=export_parent,
    )

    result_folder = next(export_parent.iterdir())
    assert (result_folder / "summary" / "feature.csv").is_file()
    assert (result_folder / "summary" / "I-T_raw_data.csv").is_file()
    assert (result_folder / "signals" / "sample_1_0.10000-0.30000s_测试.csv").is_file()
    assert not (result_folder / "file_marks.csv").exists()
    assert not (result_folder / "candidate_regions.csv").exists()
    assert (result_folder / "images" / "sample_1_0.10000-0.30000s_测试_overview.png").is_file()
    assert (result_folder / "images" / "sample_1_0.10000-0.30000s_测试_time.png").is_file()
    assert (result_folder / "images" / "sample_1_0.10000-0.30000s_测试_spectrum.png").is_file()
    assert (result_folder / "images" / "sample_1_0.10000-0.30000s_测试_combined.png").is_file()
    assert (result_folder / "analysis_session.json").is_file()
    assert (result_folder / "report.html").is_file()
    window.session = None
    window.close()
    app.processEvents()


def test_result_bundle_generates_only_selected_export_content(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    data_folder = tmp_path / "data"; export_parent = tmp_path / "exports"
    data_folder.mkdir(); export_parent.mkdir()
    tdms_path = data_folder / "sample_2.tdms"
    channel = ChannelObject(
        "Current", "Dev1/ai0", np.arange(5, dtype=float),
        properties={"wf_increment": 0.1, "unit_string": "A"},
    )
    with TdmsWriter(tdms_path) as writer: writer.write_segment([channel])
    combined = tmp_path / "combined.png"; combined.write_bytes(b"combined")
    region = {
        "id": "region", "file": tdms_path.name, "file_name": tdms_path.name,
        "channel": "Current/Dev1/ai0", "start_s": 0.1, "end_s": 0.3,
        "start_index": 1, "end_index_exclusive": 4, "note": "仅组合图",
        "combined_snapshot": str(combined),
    }
    window = MainWindow(); window.data_folder = data_folder
    window.session = {"data_folder": str(data_folder), "file_marks": {}, "file_notes": {}, "regions": [region]}
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    options = {key: False for key in DEFAULT_EXPORT_OPTIONS}
    options.update({"individual_csv": True, "image_combined": True})

    result_folder = window._export_regions(
        [region], selected_only=True, options=options, destination_parent=export_parent,
    )

    assert not (result_folder / "summary").exists()
    assert (result_folder / "signals" / "sample_2_0.10000-0.30000s_仅组合图.csv").is_file()
    assert (result_folder / "images" / "sample_2_0.10000-0.30000s_仅组合图_combined.png").is_file()
    assert len(list((result_folder / "images").iterdir())) == 1
    assert not (result_folder / "analysis_session.json").exists()
    assert not (result_folder / "report.html").exists()
    window.session = None; window.close(); app.processEvents()
