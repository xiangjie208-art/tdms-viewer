import os
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from tdms_fingerprint_viewer.core import ChannelInfo
from tdms_fingerprint_viewer.main_window import MainWindow
from tdms_fingerprint_viewer.session import normalize_session


@pytest.fixture
def trace_window(tmp_path, monkeypatch):
    monkeypatch.setenv("TDMS_VIEWER_DATA_DIR", str(tmp_path / "state"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.data_folder = tmp_path
    window.session = normalize_session(None, tmp_path)
    channel = ChannelInfo("Current", "ai0", 1001, 0.01, "A")
    window.on_trace_loaded({
        "token": window.load_token, "path": tmp_path / "sample.tdms",
        "values": np.arange(1001, dtype=float), "selected": channel,
        "channels": [channel],
    })
    window.region.setRegion((2.0, 3.0))
    window.fft_timer.stop()
    window.session_timer.stop()
    yield window
    window.fft_timer.stop()
    window.session_timer.stop()
    window.session = None
    window.close()
    app.processEvents()


def test_detail_pan_reveals_adjacent_samples_and_updates_analysis(trace_window):
    window = trace_window
    view = window.detail_plot.getViewBox()
    # Same range mutation and notification used by ViewBox.mouseDragEvent.
    view.translateBy(x=2.0)
    view.sigRangeChangedManually.emit([True, False])

    assert window.region.getRegion() == pytest.approx((4.0, 5.0))
    assert window.current_indices == (400, 500)
    x, y = window.detail_curve.getData()
    assert x[[0, -1]] == pytest.approx([4.0, 4.99])
    np.testing.assert_array_equal(y, np.arange(400, 500, dtype=float))
    assert window.current_stats["mean"] == pytest.approx(449.5)
    assert window.start_time_spin.value() == pytest.approx(4.0)
    assert window.end_time_spin.value() == pytest.approx(5.0)
    assert window.session["view_ranges"]["sample.tdms"] == pytest.approx([4.0, 5.0])
    assert window.fft_timer.isActive()

    # Repeated drags must not grow/shrink the time window or accumulate padding.
    view.translateBy(x=-1.0)
    view.sigRangeChangedManually.emit([True, False])
    assert window.region.getRegion() == pytest.approx((3.0, 4.0))
    assert view.viewRange()[0] == pytest.approx([3.0, 4.0])


@pytest.mark.parametrize("shift, expected", [(-20.0, (0.0, 1.0)), (20.0, (9.0, 10.0))])
def test_detail_pan_stops_at_file_edges_without_losing_window_width(trace_window, shift, expected):
    window = trace_window
    view = window.detail_plot.getViewBox()
    view.translateBy(x=shift)
    view.sigRangeChangedManually.emit([True, False])

    assert window.region.getRegion() == pytest.approx(expected)
    assert view.viewRange()[0] == pytest.approx(expected)
    x, _ = window.detail_curve.getData()
    assert x[0] == pytest.approx(expected[0])
    assert x[-1] == pytest.approx(expected[1] - 0.01)


def test_detail_zoom_updates_selection_but_vertical_pan_does_not(trace_window):
    window = trace_window
    view = window.detail_plot.getViewBox()
    view.setXRange(4.0, 6.0, padding=0)
    view.sigRangeChangedManually.emit([True, False])
    assert window.region.getRegion() == pytest.approx((4.0, 6.0))
    assert window.current_indices == (400, 600)

    window.fft_timer.stop()
    view.translateBy(y=10.0)
    view.sigRangeChangedManually.emit([False, True])
    assert window.region.getRegion() == pytest.approx((4.0, 6.0))
    assert not window.fft_timer.isActive()

    # The overview remains a working navigation source after a detail drag.
    window.region.setRegion((1.0, 2.0))
    assert view.viewRange()[0] == pytest.approx([1.0, 2.0])
    assert window.current_indices == (100, 200)


@pytest.mark.parametrize("requested, expected", [((4.0, 4.02), (3.93, 4.09)), ((-5.0, 15.0), (0.0, 10.0))])
def test_detail_zoom_limits_keep_analyzable_data_inside_file(trace_window, requested, expected):
    window = trace_window
    view = window.detail_plot.getViewBox()
    view.setXRange(*requested, padding=0)
    view.sigRangeChangedManually.emit([True, False])
    assert window.region.getRegion() == pytest.approx(expected)
    assert view.viewRange()[0] == pytest.approx(expected)
    assert window.current_indices[1] - window.current_indices[0] >= 16


def test_detail_mouse_drag_reveals_data_beyond_original_selection(trace_window):
    window = trace_window
    window.show()
    QApplication.processEvents()
    plot = window.detail_plot
    view = plot.getViewBox()
    viewport = plot.viewport()
    start = plot.mapFromScene(view.sceneBoundingRect().center())
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    for offset in (20, 40, 60):
        position = start - QPoint(offset, 0)
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(position), QPointF(viewport.mapToGlobal(position)),
            Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, position)

    region_start, region_end = window.region.getRegion()
    assert region_start > 2.0
    assert region_end - region_start == pytest.approx(1.0)
    x, _ = window.detail_curve.getData()
    assert x[-1] > 3.0
    assert view.viewRange()[0] == pytest.approx([region_start, region_end])


def test_detail_pan_fft_uses_newly_visible_signal(trace_window):
    window = trace_window
    window.current_values[400:500] = np.sin(2 * np.pi * 25 * np.arange(100) * 0.01)
    view = window.detail_plot.getViewBox()
    view.translateBy(x=2.0)
    view.sigRangeChangedManually.emit([True, False])
    window.fft_timer.stop()
    window.start_spectrum()
    assert window.thread_pool.waitForDone(5000)
    QApplication.processEvents()

    assert window.last_spectrum["interval"] == pytest.approx((4.0, 4.99))
    assert window.last_spectrum["peaks"][0][0] == pytest.approx(25.0)
