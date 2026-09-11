import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from tdms_fingerprint_viewer.main_window import MainWindow
from tdms_fingerprint_viewer.session import load_session_file, normalize_session, save_session_file


@pytest.fixture
def spectrum_window(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    yield window
    window.session_timer.stop()
    window.session = None
    window.close()
    app.processEvents()


def test_default_spectrum_is_linear_and_limited_to_1000_hz(spectrum_window):
    window = spectrum_window
    assert not window.log_x_check.isChecked()
    assert not window.log_y_check.isChecked()
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([0, 1000])
    window.last_spectrum = {
        "frequency": np.array([0, 100, 500, 1000, 2000]),
        "spectrum": np.array([0, 1, 2, 3, 100000]), "y_unit": "A", "peaks": [],
    }
    window.redraw_spectrum()
    curve = window.spectrum_plot.listDataItems()[0]
    np.testing.assert_array_equal(curve.xData, [0, 100, 500, 1000])
    np.testing.assert_array_equal(curve.yData, [0, 1, 2, 3])
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([0, 1000])
    assert window.last_spectrum["frequency"][-1] == 2000
    window.spectrum_plot.getViewBox().updateAutoRange()
    assert window.spectrum_plot.getViewBox().viewRange()[1][1] < 10


def test_custom_frequency_range_applies_to_blank_and_survives_session(spectrum_window, tmp_path):
    window = spectrum_window
    window.session = normalize_session(None, tmp_path)
    window.frequency_min_hz, window.frequency_max_hz = 100.0, 500.0
    window.blank_reference = {
        "frequency": np.array([10, 100, 300, 500, 1000]),
        "median": np.ones(5), "q25": np.zeros(5), "q75": np.ones(5) * 2,
    }
    window.redraw_spectrum()
    for curve in window.spectrum_plot.listDataItems():
        np.testing.assert_array_equal(curve.xData, [100, 300, 500])
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([100, 500])
    window.capture_processing_state()
    save_session_file(window.session, tmp_path / "view.json")
    window.frequency_min_hz, window.frequency_max_hz = 0, 1000
    window.session = load_session_file(tmp_path / "view.json")
    window._apply_processing_controls()
    window.redraw_spectrum()
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([100, 500])
    assert not window.log_x_check.isChecked()
    assert not window.log_y_check.isChecked()


def test_optional_log_frequency_range_uses_log_coordinates(spectrum_window):
    window = spectrum_window
    window.frequency_min_hz, window.frequency_max_hz = 10, 1000
    window.log_x_check.setChecked(True)
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([1, 3])
    window.frequency_min_hz = 0
    window.redraw_spectrum()
    assert np.all(np.isfinite(window.spectrum_plot.getViewBox().viewRange()[0]))
    window.log_x_check.setChecked(False)
    assert window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([0, 1000])


def test_frequency_dialog_rejects_reversed_range_and_restores_default(spectrum_window, monkeypatch):
    from tdms_fingerprint_viewer.main_window import FrequencyRangeDialog
    dialog = FrequencyRangeDialog(100, 500, spectrum_window)
    dialog.minimum_spin.setValue(600)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.Ok)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    dialog.reset_button.click()
    assert dialog.frequency_range() == (0.0, 1000.0)
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_frequency_button_applies_and_cancel_keeps_range(spectrum_window):
    from PySide6.QtCore import QTimer
    from tdms_fingerprint_viewer.main_window import FrequencyRangeDialog

    def finish_dialog(accept):
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, FrequencyRangeDialog)
        dialog.minimum_spin.setValue(20)
        dialog.maximum_spin.setValue(200)
        dialog.accept() if accept else dialog.reject()

    QTimer.singleShot(0, lambda: finish_dialog(False))
    spectrum_window.frequency_range_button.click()
    assert spectrum_window.frequency_max_hz == 1000
    QTimer.singleShot(0, lambda: finish_dialog(True))
    spectrum_window.frequency_range_button.click()
    assert spectrum_window.spectrum_plot.getViewBox().viewRange()[0] == pytest.approx([20, 200])


def test_linear_downsampling_keeps_zero_bins_and_final_peak():
    from tdms_fingerprint_viewer.core import display_spectrum
    frequency = np.arange(20001, dtype=float)
    values = np.zeros_like(frequency)
    values[-1] = 5
    f, y = display_spectrum(frequency, values, max_bins=10, log_x=False, log_y=False)
    assert len(f) == 10
    np.testing.assert_array_equal(y, [0] * 9 + [5])


@pytest.mark.parametrize("bounds", [(500, 100), (float("nan"), 1000), (0, None)])
def test_invalid_saved_range_falls_back_to_default(spectrum_window, bounds):
    spectrum_window.session = {"processing": {
        "frequency_min_hz": bounds[0], "frequency_max_hz": bounds[1], "log_y": True,
    }}
    spectrum_window._apply_processing_controls()
    assert (spectrum_window.frequency_min_hz, spectrum_window.frequency_max_hz) == (0, 1000)
    assert spectrum_window.log_y_check.isChecked()
