import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from tdms_fingerprint_viewer.main_window import MainWindow


def test_splitter_resize_and_controls_are_reversible(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    w = MainWindow(); w.show(); app.processEvents()
    layout = w.workspace
    layout.top.moveSplitter(620, 1); layout.bottom.moveSplitter(780, 1)
    layout.vertical.moveSplitter(320, 1); app.processEvents()
    before = [s.sizes() for s in layout.splitters]
    bounds = w.detail_view_box.viewRange()
    assert w.detail_view_box.viewRange() == bounds
    layout.controls_button.click(); app.processEvents()
    assert not w.controls.isVisible()
    assert layout.panels['overview'].isVisible()
    assert not w.controls.isVisible()
    layout.controls_button.click(); app.processEvents()
    assert layout.top.sizes() == pytest.approx(before[1], abs=2)
    layout.reset_button.click(); app.processEvents()
    assert w.controls.isVisible()
    w.close(); app.processEvents()


def test_layout_remembers_splitters_and_hidden_controls_across_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    w = MainWindow(); w.show(); app.processEvents()
    w.workspace.top.moveSplitter(570, 1)
    w.workspace.bottom.moveSplitter(750, 1)
    w.workspace.vertical.moveSplitter(310, 1); app.processEvents()
    top = w.workspace.top.sizes()
    bottom = w.workspace.bottom.sizes()
    w.workspace.controls_button.click()
    app.processEvents()
    w.close(); app.processEvents()
    restored = MainWindow(); restored.show(); app.processEvents()
    assert restored.workspace.controls_hidden
    assert not restored.controls.isVisible()
    actual = restored.workspace.bottom.sizes()
    assert actual[0] / sum(actual) == pytest.approx(bottom[0] / sum(bottom), abs=.01)
    restored.workspace.controls_button.click(); app.processEvents()
    actual = restored.workspace.top.sizes()
    assert actual[0] / sum(actual) == pytest.approx(top[0] / sum(top), abs=.01)
    restored.close(); app.processEvents()
