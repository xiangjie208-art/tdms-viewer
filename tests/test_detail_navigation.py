import os
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
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


def wheel_detail(window, delta):
    window.show()
    QApplication.processEvents()
    plot = window.detail_plot
    pos = plot.mapFromScene(plot.getViewBox().sceneBoundingRect().center())
    event = QWheelEvent(QPointF(pos), QPointF(plot.viewport().mapToGlobal(pos)),
                        QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(plot.viewport(), event)


def test_wheel_out_caps_y_but_keeps_expanding_time(trace_window):
    window = trace_window
    window.current_values = np.sin(np.arange(1001) * np.pi / 2)
    window.on_region_changed()
    window.detail_plot.setYRange(-1.4, 1.4, padding=0)
    for _ in range(4):
        before = window.detail_view_box.viewRange()[0]
        wheel_detail(window, -120)
        after = window.detail_view_box.viewRange()
        assert after[0][1] - after[0][0] > before[1] - before[0]
        assert after[1] == pytest.approx([-1.4, 1.4])
    wheel_detail(window, 120)
    assert np.diff(window.detail_view_box.viewRange()[1])[0] < 2.8


def test_wheel_out_reveals_new_peak_after_y_limit(trace_window):
    window = trace_window
    window.current_values = np.sin(np.arange(1001) * np.pi / 2)
    window.current_values[310] = 10
    window.on_region_changed()
    window.detail_plot.setYRange(-1.4, 1.4, padding=0)
    wheel_detail(window, -120)
    assert window.detail_view_box.viewRange()[0][1] > 3.1
    assert window.detail_view_box.viewRange()[1] == pytest.approx([-3.2, 12.2])


@pytest.mark.parametrize("value", [0., -2., float("nan")])
def test_wheel_out_handles_flat_and_nonfinite_data(trace_window, value):
    window = trace_window
    window.current_values[:] = value
    window.detail_plot.setYRange(-1, 1, padding=0)
    wheel_detail(window, -120)
    low, high = window.detail_view_box.viewRange()[1]
    assert np.isfinite(low) and np.isfinite(high) and high > low


def test_vertical_selection_can_zoom_out_gradually(trace_window):
    window = trace_window
    window.current_values = np.sin(np.arange(1001) * np.pi / 2)
    window.on_region_changed()
    window.on_detail_selection_finished(("y", 2, 3, -0.1, 0.1))
    wheel_detail(window, -120)
    width = np.diff(window.detail_view_box.viewRange()[1])[0]
    assert 0.2 < width < 2.8


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


@pytest.mark.parametrize("mode", ["time", "y", "xy"])
@pytest.mark.parametrize("direction", [-1, 1])
def test_detail_right_drag_pans_without_changing_selection_mode(trace_window, mode, direction):
    window = trace_window
    window.show()
    QApplication.processEvents()
    plot = window.detail_plot
    view = plot.getViewBox()
    window.detail_mode_buttons[mode].click()
    view.setYRange(100.0, 400.0, padding=0)
    QTest.qWait(60)
    viewport = plot.viewport()
    start = plot.mapFromScene(view.sceneBoundingRect().center())
    QTest.mousePress(viewport, Qt.RightButton, Qt.NoModifier, start)
    for offset in (20, 40, 60):
        QTest.qWait(20)
        position = start + QPoint(direction * offset, offset // 3)
        event = QMouseEvent(
            QEvent.MouseMove, QPointF(position), QPointF(viewport.mapToGlobal(position)),
            Qt.NoButton, Qt.RightButton, Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, event)
    QTest.mouseRelease(viewport, Qt.RightButton, Qt.NoModifier, position)

    region_start, region_end = window.region.getRegion()
    assert (region_start > 2.0) if direction < 0 else (region_start < 2.0)
    assert region_end - region_start == pytest.approx(1.0)
    x, _ = window.detail_curve.getData()
    assert (x[-1] > 3.0) if direction < 0 else (x[0] < 2.0)
    assert view.viewRange()[0] == pytest.approx([region_start, region_end])
    y_low, y_high = view.viewRange()[1]
    assert y_high - y_low == pytest.approx(300.0)
    assert view.interaction_mode == mode
    assert not view.rbScaleBox.isVisible()
    assert not view.menu.isVisible()
    # Left drag still selects immediately after releasing the right button.
    drag_selection(window, mode, (0.2, 0.2), (0.8, 0.8))


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


def test_detail_mode_buttons_persist_and_apply_axis_selection(trace_window):
    window = trace_window
    assert set(window.detail_mode_buttons) == {"time", "y", "xy"}
    assert window.detail_mode_buttons["time"].isChecked()

    window.set_detail_mode("time")
    assert window.detail_view_box.interaction_mode == "time"
    assert window.detail_mode_buttons["time"].isChecked()
    window.on_detail_selection_finished(("time", 4.0, 5.0, -1.0, 1.0))
    assert window.region.getRegion() == pytest.approx((4.0, 5.0))

    window.set_detail_mode("y")
    window.on_detail_selection_finished(("y", 4.0, 5.0, -2.0, 2.0))
    assert window.region.getRegion() == pytest.approx((4.0, 5.0))
    assert window.detail_view_box.viewRange()[1] == pytest.approx([-2.0, 2.0])

    window.set_detail_mode("xy")
    window.on_detail_selection_finished(("xy", 6.0, 7.0, -3.0, 3.0))
    assert window.region.getRegion() == pytest.approx((6.0, 7.0))
    assert window.detail_view_box.viewRange()[1] == pytest.approx([-3.0, 3.0])


def drag_selection(window, mode, start_fraction, end_fraction):
    """Drive real Qt mouse events, checking the rubber band before release."""
    plot = window.detail_plot
    view = window.detail_view_box
    window.detail_mode_buttons[mode].click()
    QTest.qWait(60)  # Settle axis-label layout before converting pixels to data.
    before_x, before_y = view.viewRange()

    def position(fraction):
        point = QPointF(
            before_x[0] + fraction[0] * (before_x[1] - before_x[0]),
            before_y[0] + fraction[1] * (before_y[1] - before_y[0]),
        )
        return plot.mapFromScene(view.mapViewToScene(point))

    start, end = position(start_fraction), position(end_fraction)
    data_start = view.mapSceneToView(plot.mapToScene(start))
    data_end = view.mapSceneToView(plot.mapToScene(end))
    expected_x = sorted([data_start.x(), data_end.x()]) if mode != "y" else before_x
    expected_y = sorted([data_start.y(), data_end.y()]) if mode != "time" else before_y
    viewport = plot.viewport()
    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, start)
    try:
        for fraction in (0.25, 0.5, 1.0):
            QTest.qWait(20)  # Allow pyqtgraph's mouse-event rate limiter to advance.
            point = start + (end - start) * fraction
            event = QMouseEvent(
                QEvent.MouseMove, QPointF(point), QPointF(viewport.mapToGlobal(point)),
                Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
            )
            QApplication.sendEvent(viewport, event)
        assert view.rbScaleBox.isVisible()
        band = view.rbScaleBox.mapRectToParent(view.rbScaleBox.rect()).normalized()
        assert (band.left(), band.right()) == pytest.approx(expected_x)
        assert (band.top(), band.bottom()) == pytest.approx(expected_y)
        # Only releasing the mouse applies the selection.
        assert view.viewRange()[0] == pytest.approx(before_x)
        assert view.viewRange()[1] == pytest.approx(before_y)
    finally:
        QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, end)

    assert view.viewRange()[0] == pytest.approx(expected_x)
    assert view.viewRange()[1] == pytest.approx(expected_y)
    assert window.region.getRegion() == pytest.approx(expected_x)
    assert not view.rbScaleBox.isVisible()
    assert view.interaction_mode == mode
    assert window.detail_mode_buttons[mode].isChecked()


@pytest.mark.parametrize("mode,start,end", [
    ("time", (0.2, 0.4), (0.8, 0.4)),  # Horizontal drag with zero height.
    ("time", (0.8, 0.7), (0.2, 0.3)),  # Reverse drag ignores vertical motion.
    ("y", (0.4, 0.2), (0.4, 0.8)),     # Vertical drag with zero width.
    ("y", (0.7, 0.8), (0.3, 0.2)),     # Reverse drag ignores horizontal motion.
    ("xy", (0.2, 0.2), (0.8, 0.8)),
    ("xy", (0.8, 0.8), (0.2, 0.2)),
])
def test_selection_drag_draws_axis_band_and_preserves_other_axis(trace_window, mode, start, end):
    window = trace_window
    window.show()
    QApplication.processEvents()
    window.detail_view_box.setRange(xRange=(2.0, 3.0), yRange=(100.0, 400.0), padding=0)
    # Repeat without leaving the chosen mode, using the newly zoomed view.
    for _ in range(2):
        window.fft_timer.stop()
        drag_selection(window, mode, start, end)
        if mode == "y":
            assert window.current_indices == (200, 300)
            assert not window.fft_timer.isActive()
        else:
            assert window.fft_timer.isActive()
