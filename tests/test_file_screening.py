import os
from threading import Event, get_ident

import numpy as np
from nptdms import ChannelObject, TdmsWriter
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from tdms_fingerprint_viewer.main_window import MainWindow
from tdms_fingerprint_viewer.session import load_session
from tdms_fingerprint_viewer.tdms_export import export_tdms_files


def wait_until(app, predicate):
    for _ in range(500):
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


def write_trace(path):
    values = np.zeros(1000)
    values[500] = 30
    with TdmsWriter(path) as writer:
        writer.write_segment([ChannelObject(
            "Current", "ai0", values, properties={"wf_increment": .001, "unit_string": "pA"},
        )])


@pytest.fixture
def screening_window(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    try:
        yield app, window
    finally:
        window.thread_pool.waitForDone(5000)
        app.processEvents()
        window.fft_timer.stop()
        window.session_timer.stop()
        window.session = None
        window.close()
        app.processEvents()


def open_folder(app, window, folder):
    window.open_data_folder(folder)
    wait_until(app, lambda: window.current_path is not None and not window.cluster_panel.loading)


def test_validity_defaults_to_unreviewed_and_is_independent_of_saved_intervals(
    tmp_path, monkeypatch, screening_window,
):
    app, window = screening_window
    panel = window.cluster_panel
    assert not panel.valid_file_button.isEnabled()
    assert not panel.invalid_file_button.isEnabled()
    assert not panel.export_valid_button.isEnabled()
    folder = tmp_path / "data"
    folder.mkdir()
    source = folder / "sample_1.tdms"
    write_trace(source)
    open_folder(app, window, folder)

    assert panel.file_validity_label.text() == "文件判定：未判断"
    assert not panel.valid_file_button.isChecked()
    assert not panel.invalid_file_button.isChecked()
    assert panel.file_screening_summary.text() == "有效 0｜无效 0｜未判断 1"
    panel.valid_file_button.click()
    assert window.file_validity(source) == "有效"
    assert panel.valid_file_button.isChecked()
    assert not panel.invalid_file_button.isChecked()
    assert panel.export_valid_button.isEnabled()
    assert window.file_list.currentRow() == 0
    assert "[有效]" in panel.file_combo.itemText(0)
    assert "[有效]" in window.file_list.item(0).text()
    assert window.processed_file_count() == 1

    monkeypatch.setattr(window, "export_plot_pixmap", lambda *args: QPixmap(1, 1))
    monkeypatch.setattr(window, "combined_plot_pixmap", lambda *args: QPixmap(1, 1))
    window.add_current_region()
    assert len(window.session["regions"]) == 1
    assert window.file_validity(source) == "有效"
    assert window.session["file_marks"][source.name] == "候选"

    panel.invalid_file_button.click()
    assert window.file_validity(source) == "无效"
    assert not panel.valid_file_button.isChecked()
    assert panel.invalid_file_button.isChecked()
    assert panel.file_screening_summary.text() == "有效 0｜无效 1｜未判断 0"
    assert not panel.export_valid_button.isEnabled()
    assert window.session["file_marks"][source.name] == "候选"
    assert len(window.session["regions"]) == 1
    assert "[无效]" in panel.file_combo.itemText(0)


def test_file_switch_blocks_marking_until_selected_trace_is_loaded(tmp_path, screening_window):
    app, window = screening_window
    panel = window.cluster_panel
    folder = tmp_path / "data"
    folder.mkdir()
    first, second = folder / "sample_1.tdms", folder / "sample_2.tdms"
    write_trace(first)
    write_trace(second)
    open_folder(app, window, folder)
    panel.valid_file_button.click()

    panel.next_file_button.click()
    assert panel.loading
    assert not panel.valid_file_button.isEnabled()
    assert not panel.invalid_file_button.isEnabled()
    window.set_current_file_validity("无效")
    assert window.session["file_validity"] == {first.name: "有效"}
    wait_until(app, lambda: window.current_path == second and not panel.loading)
    assert not panel.valid_file_button.isChecked()
    assert not panel.invalid_file_button.isChecked()
    panel.invalid_file_button.click()
    assert window.session["file_validity"] == {first.name: "有效", second.name: "无效"}

    panel.previous_file_button.click()
    wait_until(app, lambda: window.current_path == first and not panel.loading)
    assert panel.valid_file_button.isChecked()
    assert not panel.invalid_file_button.isChecked()
    assert panel.file_screening_summary.text() == "有效 1｜无效 1｜未判断 0"


def test_validity_autosaves_and_is_restored_separately_for_each_folder(tmp_path, screening_window):
    app, window = screening_window
    panel = window.cluster_panel
    folder = tmp_path / "data"
    other = tmp_path / "other"
    folder.mkdir()
    other.mkdir()
    source = folder / "sample.tdms"
    write_trace(source)
    write_trace(other / source.name)
    open_folder(app, window, folder)
    panel.valid_file_button.click()

    wait_until(app, lambda: load_session(str(folder))["file_validity"].get(source.name) == "有效")
    open_folder(app, window, other)
    assert window.file_validity(other / source.name) == "未判断"
    assert not panel.valid_file_button.isChecked()
    assert panel.file_screening_summary.text() == "有效 0｜无效 0｜未判断 1"
    panel.invalid_file_button.click()
    open_folder(app, window, folder)
    assert window.file_validity(source) == "有效"
    assert panel.valid_file_button.isChecked()
    assert not panel.invalid_file_button.isChecked()


def test_batch_cluster_labels_and_parameter_changes_preserve_file_validity(tmp_path, screening_window):
    app, window = screening_window
    panel = window.cluster_panel
    folder = tmp_path / "data"
    folder.mkdir()
    source = folder / "sample.tdms"
    write_trace(source)
    open_folder(app, window, folder)
    panel.valid_file_button.click()
    panel.start_batch()
    wait_until(app, lambda: panel.batch_worker is None)

    assert "[1 簇]" in panel.file_combo.itemText(0)
    assert "[有效]" in panel.file_combo.itemText(0)
    panel.invalid_file_button.click()
    assert "[1 簇]" in panel.file_combo.itemText(0)
    assert "[无效]" in panel.file_combo.itemText(0)
    panel.threshold.setValue(.2)
    assert "[无效]" in panel.file_combo.itemText(0)
    assert "[1 簇]" not in panel.file_combo.itemText(0)
    assert panel.invalid_file_button.isChecked()


def test_export_runs_in_background_and_copies_snapshot_of_valid_files(
    tmp_path, monkeypatch, screening_window,
):
    app, window = screening_window
    panel = window.cluster_panel
    folder = tmp_path / "data"
    folder.mkdir()
    sources = [folder / f"sample_{index}.tdms" for index in range(3)]
    for source in sources:
        write_trace(source)
    open_folder(app, window, folder)
    panel.valid_file_button.click()
    panel.next_file_button.click()
    wait_until(app, lambda: window.current_path == sources[1] and not panel.loading)
    panel.invalid_file_button.click()
    destination = tmp_path / "export"
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(destination))
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notices.append(args[-1]))
    started, release = Event(), Event()
    worker_threads = []

    def delayed_export(files, output, progress):
        worker_threads.append(get_ident())
        started.set()
        assert release.wait(5)
        return export_tdms_files(files, output, progress)

    monkeypatch.setattr("tdms_fingerprint_viewer.main_window.export_tdms_files", delayed_export)
    try:
        panel.export_valid_button.click()
        wait_until(app, started.is_set)
        assert window.tdms_export_worker is not None
        assert not panel.export_valid_button.isEnabled()
        assert len(worker_threads) == 1 and worker_threads[0] != get_ident()
        panel.next_file_button.click()
        wait_until(app, lambda: window.current_path == sources[2] and not panel.loading)
        panel.valid_file_button.click()
        assert panel.file_screening_summary.text() == "有效 2｜无效 1｜未判断 0"
        other = tmp_path / "other"
        other.mkdir()
        write_trace(other / "sample_0.tdms")
        open_folder(app, window, other)
        assert panel.file_screening_summary.text() == "有效 0｜无效 0｜未判断 1"
    finally:
        release.set()
    wait_until(app, lambda: window.tdms_export_worker is None)

    assert sorted(path.name for path in destination.iterdir()) == [sources[0].name]
    assert (destination / sources[0].name).read_bytes() == sources[0].read_bytes()
    assert all(source.is_file() for source in sources)
    assert "成功 1｜跳过 0｜失败 0" in notices[0]
    assert not panel.export_valid_button.isEnabled()


def test_export_reports_existing_names_and_missing_sources(tmp_path, monkeypatch, screening_window):
    app, window = screening_window
    panel = window.cluster_panel
    folder = tmp_path / "data"
    folder.mkdir()
    first, second = folder / "sample_1.tdms", folder / "sample_2.tdms"
    write_trace(first)
    write_trace(second)
    open_folder(app, window, folder)
    panel.valid_file_button.click()
    panel.next_file_button.click()
    wait_until(app, lambda: window.current_path == second and not panel.loading)
    panel.valid_file_button.click()
    second.unlink()
    destination = tmp_path / "export"
    destination.mkdir()
    existing = destination / first.name
    existing.write_bytes(b"keep existing file")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(destination))
    notices = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: notices.append(args[-1]))

    panel.export_valid_button.click()
    wait_until(app, lambda: window.tdms_export_worker is None)

    assert existing.read_bytes() == b"keep existing file"
    assert "成功 0｜跳过 1｜失败 1" in notices[0]
    assert second.name in notices[0]
    assert first.name in panel.file_export_status.toolTip()
    assert panel.export_valid_button.isEnabled()


def test_cancelling_export_destination_keeps_marks_and_starts_no_export(tmp_path, monkeypatch, screening_window):
    app, window = screening_window
    folder = tmp_path / "data"
    folder.mkdir()
    write_trace(folder / "sample.tdms")
    open_folder(app, window, folder)
    window.cluster_panel.valid_file_button.click()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")

    window.cluster_panel.export_valid_button.click()

    assert window.tdms_export_worker is None
    assert window.cluster_panel.export_valid_button.isEnabled()
    assert window.session["file_validity"] == {"sample.tdms": "有效"}
