import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

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
