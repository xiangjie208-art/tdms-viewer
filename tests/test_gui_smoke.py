import os

import numpy as np
from nptdms import ChannelObject, TdmsWriter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox, QTabWidget

from tdms_fingerprint_viewer.main_window import MainWindow


def test_main_window_constructs_with_original_four_panel_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.settings_path == tmp_path / "state" / "settings.json"
    assert isinstance(window.controls, QTabWidget)
    assert window.controls.count() == 2
    assert window.start_time_spin is not None
    assert window.end_time_spin is not None
    assert window.duration_time_spin is not None
    window.session = None
    window.current_path = None
    window.close()
    app.processEvents()


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
    time_snapshot = tmp_path / "time.png"; time_snapshot.write_bytes(b"time")
    spectrum_snapshot = tmp_path / "spectrum.png"; spectrum_snapshot.write_bytes(b"spectrum")
    region = {
        "id": "region", "file": str(tdms_path), "file_name": tdms_path.name,
        "channel": "Current/Dev1/ai0", "start_s": 0.1, "end_s": 0.3,
        "start_index": 1, "end_index_exclusive": 4, "tag": "候选", "note": "测试",
        "statistics": {}, "peaks": [], "time_snapshot": str(time_snapshot),
        "spectrum_snapshot": str(spectrum_snapshot),
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

    window._export_regions([region], selected_only=False)

    result_folder = next(export_parent.iterdir())
    assert (result_folder / "feature.csv").is_file()
    assert (result_folder / "I-T_raw_data.csv").is_file()
    assert not (result_folder / "file_marks.csv").exists()
    assert not (result_folder / "candidate_regions.csv").exists()
    assert (result_folder / "snapshots" / "sample_1_0.10000-0.30000s_测试_time.png").is_file()
    assert (result_folder / "snapshots" / "sample_1_0.10000-0.30000s_测试_spectrum.png").is_file()
    window.session = None
    window.close()
    app.processEvents()
