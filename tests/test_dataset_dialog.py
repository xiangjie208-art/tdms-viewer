import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from tdms_fingerprint_viewer.dataset_dialog import DatasetBuildWorker, DatasetDialog
from tdms_fingerprint_viewer.dataset_export import DatasetBuildSummary, DatasetSource
from tdms_fingerprint_viewer.widgets import WheelSafeDoubleSpinBox


def app():
    return QApplication.instance() or QApplication([])


def sources(tmp_path):
    return [
        DatasetSource(tmp_path / "A", "A", "A", 2, 3, True),
        DatasetSource(tmp_path / "B", "B", "B", 1, 0, False),
    ]


def test_dataset_dialog_defaults_and_editable_label_mapping(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))

    dialog.set_root(tmp_path)

    assert isinstance(dialog.threshold_spin, WheelSafeDoubleSpinBox)
    assert dialog.threshold_spin.value() == 10.0
    assert dialog.source_table.rowCount() == 2
    assert dialog.source_table.item(0, 0).checkState() == Qt.Checked
    assert dialog.source_table.item(1, 0).checkState() == Qt.Unchecked
    dialog.source_table.item(0, 2).setText("same-molecule")
    selected = dialog.selected_sources()
    assert len(selected) == 1
    assert selected[0].label == "same-molecule"
    dialog.close()


def test_dataset_dialog_enables_build_only_with_valid_inputs(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))

    dialog.set_root(tmp_path)

    assert not dialog.build_button.isEnabled()
    dialog.set_output_parent(tmp_path / "exports")
    assert dialog.build_button.isEnabled()
    dialog.source_table.item(0, 2).setText("")
    assert not dialog.build_button.isEnabled()
    dialog.close()


def test_dataset_worker_forwards_progress_and_cancellation(tmp_path):
    app()
    calls = {}

    def builder(root, output, selected, threshold, progress, cancelled):
        progress(1, 2, "A / trace_1.tdms")
        calls["cancelled"] = cancelled()
        return DatasetBuildSummary(tmp_path / "done", 1, (), calls["cancelled"])

    worker = DatasetBuildWorker(tmp_path, tmp_path, sources(tmp_path)[:1], 10.0, builder)
    progress_spy = QSignalSpy(worker.signals.progress)
    finish_spy = QSignalSpy(worker.signals.finished)

    worker.cancel()
    worker.run()

    assert calls["cancelled"] is True
    assert progress_spy.count() == 1
    assert finish_spy.count() == 1


def test_dialog_stop_requests_worker_cancellation(tmp_path):
    app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))
    dialog.set_root(tmp_path)
    dialog.set_output_parent(tmp_path / "exports")

    class StubWorker:
        def __init__(self):
            self.was_cancelled = False

        def cancel(self):
            self.was_cancelled = True

    dialog.worker = StubWorker()
    dialog.set_running(True)

    dialog.stop_build()

    assert dialog.worker.was_cancelled
    assert "正在停止" in dialog.status_label.text()
    dialog.close()


def test_dialog_reject_stops_worker_and_stays_open_until_completion(tmp_path):
    application = app()
    dialog = DatasetDialog(discoverer=lambda root: sources(tmp_path))
    dialog.set_root(tmp_path)
    dialog.set_output_parent(tmp_path / "exports")

    class StubWorker:
        def __init__(self):
            self.was_cancelled = False

        def cancel(self):
            self.was_cancelled = True

    dialog.worker = StubWorker()
    dialog.set_running(True)
    dialog.show()
    application.processEvents()

    dialog.reject()

    assert dialog.worker.was_cancelled
    assert dialog.isVisible()
    assert "正在停止" in dialog.status_label.text()
    dialog.worker = None
    dialog.close()
