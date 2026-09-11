import os
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tdms_fingerprint_viewer.main_window import MainWindow


def test_export_is_white_fixed_size_and_keeps_interactive_style(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.current_channel = SimpleNamespace(unit="nA")
    x = np.linspace(0, 90, 1000)
    window.detail_curve.setData(x, np.sin(x) * 0.001)
    window.detail_plot.setXRange(0, 90, padding=0)
    window.detail_plot.setYRange(-0.01, 0.03, padding=0)
    original = window.detail_plot.getViewBox().viewRange()
    pixmap = window.export_plot_pixmap("time")
    assert pixmap.width() == 2148
    assert pixmap.height() == 894
    assert pixmap.toImage().pixelColor(0, 0).name() == "#ffffff"
    assert window.detail_plot.getViewBox().viewRange() == original
    assert window.plot_theme["background"] == "#05070A"
    window.close(); app.processEvents()
