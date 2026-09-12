from __future__ import annotations

from collections import OrderedDict
import csv
from datetime import datetime
import html
import json
from pathlib import Path
import shutil
import traceback
import uuid

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QByteArray, QObject, QRect, QRectF, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPixmap, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
    QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem, QToolButton,
    QVBoxLayout, QWidget,
)

from .core import (
    common_log_reference, compute_spectrum, discover_tdms, display_spectrum,
    dominant_peaks, load_trace, minmax_envelope, trace_statistics,
)
from .exporting import (
    DEFAULT_EXPORT_OPTIONS, region_export_basename, unique_export_basename,
    write_feature_csv, write_individual_signal_csvs, write_it_raw_csv,
)
from .plot_export import figure_pixmap
from .cluster_panel import ClusterPanel
from .layout_workspace import LayoutWorkspace
from .session import (
    app_data_dir, load_session, load_session_file, normalize_session,
    save_session, save_session_file, snapshots_dir,
)


APP_NAME = "TDMS 分子指纹筛选器"
TAGS = ["未标记", "候选", "待复查", "无明显特征", "噪声过大", "排除"]
TAG_SYMBOLS = {"未标记": "○", "候选": "★", "待复查": "?", "无明显特征": "✓", "噪声过大": "!", "排除": "×"}
TAG_COLORS = {
    "未标记": "#AAB2BD", "候选": "#FFB300", "待复查": "#4FC3F7",
    "无明显特征": "#81C784", "噪声过大": "#FF8A65", "排除": "#EF5350",
}


class SelectionViewBox(pg.ViewBox):
    """Left-button axis selections with right-button panning."""

    selectionFinished = Signal(object)
    zoomedOut = Signal(object)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_interaction_mode("time")

    def set_interaction_mode(self, mode):
        self.interaction_mode = mode
        self.setMouseMode(self.RectMode)
        self.rbScaleBox.hide()
        self.setCursor(Qt.CursorShape.CrossCursor)

    def wheelEvent(self, event, axis=None):
        previous = self.viewRange()
        outward = event.delta() * self.state["wheelScaleFactor"] > 0
        super().wheelEvent(event, axis=axis)
        if outward and axis is None and self.state["mouseEnabled"][1]:
            self.zoomedOut.emit(previous)

    def mouseDragEvent(self, event, axis=None):
        if event.button() == Qt.MouseButton.RightButton:
            event.accept()
            self.rbScaleBox.hide()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            delta = self.mapToView(event.lastPos()) - self.mapToView(event.pos())
            axes = list(self.state["mouseEnabled"])
            if axis is not None:
                axes[1 - axis] = False
            self.translateBy(x=delta.x() if axes[0] else None, y=delta.y() if axes[1] else None)
            self.sigRangeChangedManually.emit(axes)
            if event.isFinish():
                self.setCursor(Qt.CursorShape.CrossCursor)
            return
        selecting = axis is None and event.button() == Qt.MouseButton.LeftButton
        if not selecting:
            return super().mouseDragEvent(event, axis=axis)
        event.accept()
        rect = self.childGroup.mapRectFromParent(
            QRectF(event.buttonDownPos(event.button()), event.pos())
        ).normalized()
        visible = self.viewRect()
        rect.setLeft(max(visible.left(), min(visible.right(), rect.left())))
        rect.setRight(max(visible.left(), min(visible.right(), rect.right())))
        rect.setTop(max(visible.top(), min(visible.bottom(), rect.top())))
        rect.setBottom(max(visible.top(), min(visible.bottom(), rect.bottom())))
        if self.interaction_mode == "time":
            rect.setTop(visible.top())
            rect.setBottom(visible.bottom())
        elif self.interaction_mode == "y":
            rect.setLeft(visible.left())
            rect.setRight(visible.right())
        if event.isFinish():
            self.rbScaleBox.hide()
            if rect.width() > 0 and rect.height() > 0:
                self.selectionFinished.emit((
                    self.interaction_mode, rect.left(), rect.right(), rect.top(), rect.bottom(),
                ))
        else:
            self.updateScaleBox(
                self.childGroup.mapToParent(rect.topLeft()), self.childGroup.mapToParent(rect.bottomRight()),
            )
        # Do not call RectMode's default handler: it would zoom both axes.


def mode_icon(mode, color="#65717D"):
    pixmap = QPixmap(24, 24); pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = pg.mkPen(color, width=1.7); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
    if mode == "time":
        painter.drawLine(4, 4, 20, 4); painter.drawLine(4, 20, 20, 20)
        painter.drawLine(4, 4, 4, 20); painter.drawLine(20, 4, 20, 20)
        painter.drawLine(7, 4, 7, 20); painter.drawLine(17, 4, 17, 20)
    elif mode == "y":
        painter.drawLine(4, 4, 20, 4); painter.drawLine(4, 20, 20, 20)
        painter.drawLine(4, 4, 4, 20); painter.drawLine(20, 4, 20, 20)
        painter.drawLine(4, 7, 20, 7); painter.drawLine(4, 17, 20, 17)
    else:
        painter.drawRect(4, 4, 16, 16)
    painter.end(); return QIcon(pixmap)
PLOT_THEMES = {
    "深色高对比（推荐）": {
        "background": "#05070A", "foreground": "#F4F7FA", "time": "#FFFFFF",
        "spectrum": "#FFFFFF", "blank": "#00D7FF", "region": "#FFB300",
    },
    "浅色": {
        "background": "#FFFFFF", "foreground": "#263238", "time": "#1261A0",
        "spectrum": "#9B2C2C", "blank": "#69727D", "region": "#1E88E5",
    },
}

EXPORT_OPTION_GROUPS = (
    ("图片", (
        ("image_overview", "全局图"), ("image_time", "局部图"),
        ("image_spectrum", "频谱图"), ("image_combined", "全局—局部组合图"),
    )),
    ("CSV 数据", (
        ("feature_summary", "特征汇总总表 feature.csv"),
        ("raw_summary", "原始 I–T 数据总表 I-T_raw_data.csv"),
        ("individual_csv", "每条筛选信号的独立 CSV 子表"),
    )),
    ("会话与报告", (
        ("session_json", "会话文件 analysis_session.json"),
        ("html_report", "HTML 汇总报告 report.html"),
    )),
)


class FrequencyRangeDialog(QDialog):
    def __init__(self, minimum, maximum, parent=None):
        super().__init__(parent)
        self.setWindowTitle("频率显示范围")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("仅调整频谱显示范围，保留完整计算结果。"))
        form = QFormLayout()
        self.minimum_spin = QDoubleSpinBox()
        self.maximum_spin = QDoubleSpinBox()
        for spin, value in ((self.minimum_spin, minimum), (self.maximum_spin, maximum)):
            spin.setDecimals(3); spin.setRange(0, 1e12); spin.setSuffix(" Hz"); spin.setValue(value)
        form.addRow("起始频率", self.minimum_spin)
        form.addRow("终止频率", self.maximum_spin)
        layout.addLayout(form)
        note = QLabel("对数频率坐标不显示 0 Hz。")
        layout.addWidget(note)
        self.reset_button = QPushButton("恢复 0–1000 Hz")
        self.reset_button.clicked.connect(self.reset_range)
        layout.addWidget(self.reset_button)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("确定")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def reset_range(self):
        self.minimum_spin.setValue(0); self.maximum_spin.setValue(1000)

    def frequency_range(self):
        return self.minimum_spin.value(), self.maximum_spin.value()

    def accept(self):
        minimum, maximum = self.frequency_range()
        if minimum >= maximum:
            QMessageBox.warning(self, "频率范围无效", "终止频率必须大于起始频率。")
            return
        super().accept()


class ExportOptionsDialog(QDialog):
    def __init__(self, defaults, region_count, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择导出内容")
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"将导出 {region_count} 条已保存信号。请选择需要生成的内容："))
        self.option_checks = {}
        for title, options in EXPORT_OPTION_GROUPS:
            group = QGroupBox(title); group_layout = QVBoxLayout(group)
            for key, label in options:
                check = QCheckBox(label); check.setChecked(bool(defaults.get(key, True)))
                self.option_checks[key] = check; group_layout.addWidget(check)
            layout.addWidget(group)
        choice_row = QHBoxLayout(); select_all = QPushButton("全选"); clear_all = QPushButton("取消全选")
        select_all.clicked.connect(lambda: self.set_all_checked(True)); clear_all.clicked.connect(lambda: self.set_all_checked(False))
        choice_row.addWidget(select_all); choice_row.addWidget(clear_all); choice_row.addStretch(1); layout.addLayout(choice_row)
        self.remember_check = QCheckBox("记住本次导出选项"); self.remember_check.setChecked(True)
        layout.addWidget(self.remember_check)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def set_all_checked(self, checked):
        for check in self.option_checks.values(): check.setChecked(checked)

    def options(self):
        return {key: check.isChecked() for key, check in self.option_checks.items()}

    def accept(self):
        if not any(self.options().values()):
            QMessageBox.information(self, "选择导出内容", "请至少选择一项导出内容。")
            return
        super().accept()


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)


def safe_emit(signal, value):
    try:
        signal.emit(value)
    except RuntimeError:
        pass


class LoadWorker(QRunnable):
    def __init__(self, token, path, channel_key=None):
        super().__init__()
        self.token, self.path, self.channel_key = token, Path(path), channel_key
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            values, selected, channels = load_trace(self.path, self.channel_key)
            safe_emit(self.signals.result, {
                "token": self.token, "path": self.path, "values": values,
                "selected": selected, "channels": channels,
            })
        except Exception:
            safe_emit(self.signals.error, traceback.format_exc())


class SpectrumWorker(QRunnable):
    def __init__(self, token, values, dt, mode, window, unit, interval):
        super().__init__()
        self.token, self.values, self.dt = token, values, dt
        self.mode, self.window, self.unit, self.interval = mode, window, unit, interval
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            frequency, spectrum, _ = compute_spectrum(self.values, self.dt, self.mode, self.window)
            safe_emit(self.signals.result, {
                "token": self.token, "frequency": frequency, "spectrum": spectrum,
                "y_unit": f"{self.unit}²/Hz" if self.mode == "功率谱密度 (Welch)" else self.unit,
                "peaks": dominant_peaks(frequency, spectrum), "interval": self.interval,
                "resolution": float(frequency[1] - frequency[0]) if len(frequency) > 1 else float("nan"),
            })
        except Exception:
            safe_emit(self.signals.error, traceback.format_exc())


class BlankWorker(QRunnable):
    def __init__(self, token, folder, mode, window, limit=10):
        super().__init__()
        self.token, self.folder, self.limit = token, Path(folder), limit
        self.mode, self.window = mode, window
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            all_files = discover_tdms(self.folder)
            if not all_files:
                raise ValueError("空白文件夹中没有 TDMS 文件")
            count = min(self.limit, len(all_files))
            indices = np.unique(np.round(np.linspace(0, len(all_files) - 1, count)).astype(int))
            files = [all_files[i] for i in indices]
            spectra, units = [], []
            for number, path in enumerate(files, 1):
                safe_emit(self.signals.progress, f"空白参考：正在计算 {number}/{len(files)} — {path.name}")
                values, channel, _ = load_trace(path)
                frequency, spectrum, _ = compute_spectrum(values, channel.dt, self.mode, self.window)
                spectra.append((frequency, spectrum))
                units.append(channel.unit)
            frequency, median, q25, q75 = common_log_reference(spectra)
            safe_emit(self.signals.result, {
                "token": self.token, "frequency": frequency, "median": median,
                "q25": q25, "q75": q75, "files": [path.name for path in files],
                "mode": self.mode, "window": self.window,
                "y_unit": f"{units[0]}²/Hz" if self.mode == "功率谱密度 (Welch)" else units[0],
            })
        except Exception:
            safe_emit(self.signals.error, traceback.format_exc())


def make_plot(title, left_label, bottom_label, view_box=None):
    plot = pg.PlotWidget(background="white", viewBox=view_box)
    plot.setTitle(title, color="#20252B", size="11pt")
    plot.setLabel("bottom", bottom_label, color="#343A40")
    plot.setLabel("left", left_label, color="#343A40")
    plot.showGrid(x=True, y=True, alpha=0.18)
    plot.getPlotItem().setDownsampling(auto=True, mode="peak")
    plot.getPlotItem().setClipToView(True)
    return plot


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1500, 900)
        self.thread_pool = QThreadPool.globalInstance()
        self.files = []
        self.data_folder = None
        self.blank_folder = None
        self.session = None
        self.active_session_file = None
        self.current_path = None
        self.current_values = None
        self.current_channel = None
        self.current_channels = []
        self.current_stats = {}
        self.current_indices = (0, 0)
        self.last_spectrum = None
        self.frequency_min_hz, self.frequency_max_hz = 0.0, 1000.0
        self.blank_reference = None
        self.cache = OrderedDict()
        self.load_token = self.spectrum_token = self.blank_token = 0
        self.pending_region = None
        self.workers = set()
        self.plot_theme = dict(PLOT_THEMES["深色高对比（推荐）"])
        self.settings_path = app_data_dir() / "settings.json"
        self.settings = self._load_settings()
        self.fft_timer = QTimer(self)
        self.fft_timer.setSingleShot(True)
        self.fft_timer.timeout.connect(self.start_spectrum)
        self.session_timer = QTimer(self)
        self.session_timer.setSingleShot(True)
        self.session_timer.timeout.connect(self.save_session_now)
        self._build_ui()
        self._load_theme()
        self.apply_plot_theme()
        self._restore_settings()

    def _load_settings(self):
        try:
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_settings(self):
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _restore_settings(self):
        geometry = self.settings.get("geometry")
        if geometry:
            try: self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception: pass
        self.workspace.restore(self.settings.get("workspace_layout"))
        last_session = self.settings.get("last_session_file", "")
        last_folder = self.settings.get("last_data_folder", "")
        if last_session and Path(last_session).is_file():
            QTimer.singleShot(0, lambda: self.open_session_path(Path(last_session), startup=True))
        elif last_folder and Path(last_folder).is_dir():
            QTimer.singleShot(0, lambda: self.open_data_folder(Path(last_folder)))

    def file_key(self, path):
        resolved = Path(path).resolve()
        if self.data_folder:
            try: return resolved.relative_to(Path(self.data_folder).resolve()).as_posix()
            except ValueError: pass
        return resolved.name

    def _build_ui(self):
        self.workspace = LayoutWorkspace()
        self.setCentralWidget(self.workspace)

        self.controls = self._build_controls()
        overview_box = QWidget(); overview_layout = QVBoxLayout(overview_box)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_plot = make_plot("完整数据总览", "记录信号", "时间 (s)")
        self.overview_curve = self.overview_plot.plot(pen=pg.mkPen("#FFFFFF", width=0.8))
        self.region = pg.LinearRegionItem(values=(0, 10), movable=True)
        self.region.setZValue(10); self.overview_plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self.on_region_changed); overview_layout.addWidget(self.overview_plot, 1)

        detail_box = QWidget(); detail_layout = QVBoxLayout(detail_box); detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_view_box = SelectionViewBox()
        self.detail_plot = make_plot("局部波形", "记录信号", "时间 (s)", self.detail_view_box)
        self.detail_curve = self.detail_plot.plot(pen=pg.mkPen("#FFFFFF", width=0.85))
        self.detail_view_box.sigRangeChangedManually.connect(self.on_detail_range_changed)
        self.detail_view_box.selectionFinished.connect(self.on_detail_selection_finished)
        self.detail_view_box.zoomedOut.connect(self.limit_detail_zoom_out)
        self.detail_plot.setToolTip("左键框选；按住右键拖动浏览数据；滚轮缩放。向外缩小时纵轴最多保留可见数据上下各 20% 留白，横轴继续缩放。")
        detail_header = QHBoxLayout(); detail_header.addStretch(1)
        self.detail_mode_buttons = {}
        for mode, tooltip in (("time", "框选时间范围"), ("y", "框选纵轴范围"), ("xy", "框选时间和纵轴范围")):
            button = QToolButton(); button.setCheckable(True); button.setAutoExclusive(True); button.setIcon(mode_icon(mode))
            button.setIconSize(QSize(22, 22)); button.setToolTip(tooltip); button.setAccessibleName(tooltip)
            button.setProperty("mode", mode); button.clicked.connect(lambda _=False, value=mode: self.set_detail_mode(value))
            self.detail_mode_buttons[mode] = button; detail_header.addWidget(button)
        self.set_detail_mode("time")
        detail_layout.addLayout(detail_header); detail_layout.addWidget(self.detail_plot, 1)

        spectrum_box = QWidget(); spectrum_layout = QVBoxLayout(spectrum_box); spectrum_layout.setContentsMargins(0, 0, 0, 0)
        self.spectrum_info_label = QLabel("频谱：等待选择数据")
        self.spectrum_info_label.setStyleSheet("padding:4px 7px;background:#F5F7FA;color:#343A40")
        self.spectrum_plot = make_plot("傅里叶变换 / 功率谱", "幅值", "频率 (Hz)")
        spectrum_header = QHBoxLayout()
        self.spectrum_info_label.setWordWrap(True)
        spectrum_header.addWidget(self.spectrum_info_label, 1)
        self.frequency_range_button = QPushButton("频率范围…")
        self.frequency_range_button.clicked.connect(self.edit_frequency_range)
        spectrum_header.addWidget(self.frequency_range_button)
        spectrum_layout.addLayout(spectrum_header); spectrum_layout.addWidget(self.spectrum_plot, 1)
        self.workspace.setup(self.controls, overview_box, detail_box, spectrum_box)

        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(1); self.progress.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.progress, 0); self.statusBar().showMessage("请选择 TDMS 数据文件夹")

    def _build_controls(self):
        tabs = QTabWidget()
        tabs.addTab(self._scroll_page(self._build_data_tab()), "数据与频谱")
        tabs.addTab(self._scroll_page(self._build_screening_tab()), "筛选记录")
        self.cluster_panel = ClusterPanel(self)
        tabs.addTab(self._scroll_page(self.cluster_panel), "自动寻簇")
        return tabs

    def _scroll_page(self, widget):
        area = QScrollArea(); area.setWidgetResizable(True); area.setFrameShape(QFrame.NoFrame); area.setWidget(widget)
        return area

    def _folder_row(self, button_text, callback):
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit(); line.setReadOnly(True)
        button = QPushButton(button_text); button.clicked.connect(callback)
        layout.addWidget(line, 1); layout.addWidget(button); return widget, line

    def _build_data_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        data_group = QGroupBox("数据来源"); form = QFormLayout(data_group)
        row, self.data_folder_edit = self._folder_row("选择…", self.choose_data_folder); form.addRow("数据文件夹", row)
        row, self.blank_folder_edit = self._folder_row("选择…", self.choose_blank_folder); form.addRow("空白文件夹", row)
        layout.addWidget(data_group)
        self.file_count_label = QLabel("尚未载入文件"); layout.addWidget(self.file_count_label)
        self.file_list = QListWidget(); self.file_list.setMinimumHeight(105); self.file_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.file_list.currentRowChanged.connect(self.on_file_row_changed); layout.addWidget(self.file_list, 1)
        nav = QHBoxLayout(); self.prev_button = QPushButton("← 上一条"); self.next_button = QPushButton("下一条 →")
        self.prev_button.clicked.connect(self.previous_file); self.next_button.clicked.connect(self.next_file)
        nav.addWidget(self.prev_button); nav.addWidget(self.next_button); layout.addLayout(nav)

        time_group = QGroupBox("局部时间窗口"); time_form = QFormLayout(time_group)
        self.time_unit_combo = QComboBox(); self.time_unit_combo.addItems(["秒 (s)", "毫秒 (ms)"])
        self.time_unit_combo.currentIndexChanged.connect(self.on_time_unit_changed); time_form.addRow("时间单位", self.time_unit_combo)
        self.time_unit_combo.currentIndexChanged.connect(self.schedule_session_save)
        self.start_time_spin = QDoubleSpinBox(); self.end_time_spin = QDoubleSpinBox(); self.duration_time_spin = QDoubleSpinBox()
        for spin in (self.start_time_spin, self.end_time_spin, self.duration_time_spin):
            spin.setDecimals(9); spin.setRange(0.0, 1_000_000_000.0); spin.setKeyboardTracking(False); spin.setGroupSeparatorShown(True)
        self.start_time_spin.setToolTip("输入局部窗口起点；如果超过当前终点，会自动扩大终点。")
        self.end_time_spin.setToolTip("输入局部窗口终点；如果小于当前起点，会自动调整起点。")
        self.duration_time_spin.setToolTip("输入窗口宽度；接近数据终点时会自动向左移动以保持宽度。")
        self.start_time_spin.editingFinished.connect(lambda: self.apply_time_input("start"))
        self.end_time_spin.editingFinished.connect(lambda: self.apply_time_input("end"))
        self.duration_time_spin.editingFinished.connect(lambda: self.apply_time_input("duration"))
        time_form.addRow("起点", self.start_time_spin); time_form.addRow("终点", self.end_time_spin); time_form.addRow("窗口宽度", self.duration_time_spin)
        layout.addWidget(time_group)

        settings_group = QGroupBox("查看与频谱参数"); settings_form = QFormLayout(settings_group)
        self.channel_combo = QComboBox(); self.channel_combo.currentIndexChanged.connect(self.on_channel_changed); settings_form.addRow("数据通道", self.channel_combo)
        self.fft_scope_combo = QComboBox(); self.fft_scope_combo.addItems(["局部框选区间", "完整文件"])
        self.fft_scope_combo.currentIndexChanged.connect(self.schedule_spectrum); settings_form.addRow("FFT 范围", self.fft_scope_combo)
        self.fft_scope_combo.currentIndexChanged.connect(self.schedule_session_save)
        self.spectrum_mode_combo = QComboBox(); self.spectrum_mode_combo.addItems(["FFT 幅度谱", "功率谱密度 (Welch)"])
        self.spectrum_mode_combo.currentIndexChanged.connect(self.on_spectrum_setting_changed); settings_form.addRow("频谱模式", self.spectrum_mode_combo)
        self.spectrum_mode_combo.currentIndexChanged.connect(self.schedule_session_save)
        self.window_combo = QComboBox(); self.window_combo.addItems(["Hann", "Hamming", "Blackman", "矩形窗"])
        self.window_combo.currentIndexChanged.connect(self.on_spectrum_setting_changed); settings_form.addRow("窗函数", self.window_combo)
        self.window_combo.currentIndexChanged.connect(self.schedule_session_save)
        self.log_x_check = QCheckBox("频率对数坐标"); self.log_x_check.setChecked(False)
        self.log_y_check = QCheckBox("幅值对数坐标"); self.log_y_check.setChecked(False)
        self.log_x_check.toggled.connect(self.redraw_spectrum); self.log_y_check.toggled.connect(self.redraw_spectrum)
        self.log_x_check.toggled.connect(self.schedule_session_save); self.log_y_check.toggled.connect(self.schedule_session_save)
        axes = QWidget(); axes_layout = QHBoxLayout(axes); axes_layout.setContentsMargins(0, 0, 0, 0)
        axes_layout.addWidget(self.log_x_check); axes_layout.addWidget(self.log_y_check); settings_form.addRow("坐标", axes)
        self.blank_overlay_check = QCheckBox("叠加空白中位频谱与四分位范围"); self.blank_overlay_check.setChecked(True)
        self.blank_overlay_check.toggled.connect(self.on_blank_overlay_changed); settings_form.addRow("空白参考", self.blank_overlay_check)
        self.blank_overlay_check.toggled.connect(self.schedule_session_save)
        layout.addWidget(settings_group)

        theme_group = QGroupBox("显示主题"); theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(["深色高对比（推荐）", "浅色", "自定义"])
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed); theme_form.addRow("预设", self.theme_combo)
        color_box = QWidget(); color_grid = QGridLayout(color_box); color_grid.setContentsMargins(0, 0, 0, 0); self.color_buttons = {}
        for index, (key, text) in enumerate((("background", "背景"), ("time", "时域信号"), ("spectrum", "频谱信号"), ("blank", "空白参考"))):
            button = QPushButton(text); button.clicked.connect(lambda _=False, k=key: self.choose_color(k)); self.color_buttons[key] = button
            color_grid.addWidget(button, index // 2, index % 2)
        theme_form.addRow("自定义颜色", color_box)
        self.grid_check = QCheckBox("显示背景网格")
        self.grid_check.setChecked(bool(self.settings.get("plot_grid", True)))
        theme_form.addRow("背景网格", self.grid_check)
        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.2, 5.0); self.line_width_spin.setDecimals(2)
        self.line_width_spin.setSingleStep(0.1); self.line_width_spin.setSuffix(" pt")
        self.line_width_spin.setKeyboardTracking(False)
        try:
            width = float(self.settings.get("plot_line_width_pt", 0.75))
            if not np.isfinite(width): width = 0.75
        except (TypeError, ValueError):
            width = 0.75
        self.line_width_spin.setValue(width)
        self.line_width_spin.setToolTip("统一调整总览、局部波形和频谱曲线的线宽（磅）")
        theme_form.addRow("线条粗细", self.line_width_spin)
        self.grid_check.toggled.connect(self.on_plot_style_changed)
        self.line_width_spin.valueChanged.connect(self.on_plot_style_changed)
        layout.addWidget(theme_group)

        export_row = QHBoxLayout(); self.export_csv_button = QPushButton("导出局部 CSV"); self.export_image_button = QPushButton("导出当前图像")
        self.export_combined_button = QPushButton("导出组合图")
        self.export_csv_button.clicked.connect(self.export_local_csv); self.export_image_button.clicked.connect(self.export_current_images)
        self.export_combined_button.clicked.connect(self.export_combined_image)
        export_row.addWidget(self.export_csv_button); export_row.addWidget(self.export_image_button); export_row.addWidget(self.export_combined_button); layout.addLayout(export_row)
        self.peaks_label = QLabel("主要峰：尚未计算"); self.peaks_label.setWordWrap(True); self.peaks_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.peaks_label); return tab

    def _build_screening_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        session_group = QGroupBox("处理会话"); session_layout = QVBoxLayout(session_group)
        self.session_status_label = QLabel("尚未载入处理会话"); self.session_status_label.setWordWrap(True)
        session_buttons = QHBoxLayout()
        self.save_progress_button = QPushButton("保存进度"); self.save_session_as_button = QPushButton("另存会话…")
        self.open_session_button = QPushButton("打开会话…")
        self.save_progress_button.clicked.connect(self.save_progress)
        self.save_session_as_button.clicked.connect(self.save_session_as); self.open_session_button.clicked.connect(self.open_session_dialog)
        session_buttons.addWidget(self.save_progress_button); session_buttons.addWidget(self.save_session_as_button); session_buttons.addWidget(self.open_session_button)
        session_layout.addWidget(self.session_status_label); session_layout.addLayout(session_buttons); layout.addWidget(session_group)
        mark_group = QGroupBox("当前文件"); form = QFormLayout(mark_group)
        self.tag_combo = QComboBox(); self.tag_combo.addItems(TAGS); form.addRow("文件标记", self.tag_combo)
        self.note_edit = QPlainTextEdit(); self.note_edit.setPlaceholderText("可记录信号形态、判断依据等…"); self.note_edit.setMaximumHeight(90); form.addRow("备注", self.note_edit)
        self.tag_combo.currentTextChanged.connect(self.on_current_mark_edited); self.note_edit.textChanged.connect(self.on_current_mark_edited)
        save_row = QWidget(); save_layout = QHBoxLayout(save_row); save_layout.setContentsMargins(0, 0, 0, 0)
        self.save_mark_button = QPushButton("保存文件标记"); self.add_region_button = QPushButton("保存当前区间")
        self.save_mark_button.clicked.connect(self.save_current_mark); self.add_region_button.clicked.connect(self.add_current_region)
        save_layout.addWidget(self.save_mark_button); save_layout.addWidget(self.add_region_button); form.addRow(save_row); layout.addWidget(mark_group)
        layout.addWidget(QLabel("已保存的局部区间（双击可跳转）"))
        self.region_table = QTableWidget(0, 5); self.region_table.setHorizontalHeaderLabels(["文件", "起点/s", "终点/s", "标签", "备注"])
        self.region_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.region_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.region_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.region_table.doubleClicked.connect(self.jump_to_region); self.region_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.region_table, 1)
        row = QHBoxLayout(); self.delete_region_button = QPushButton("删除选中区间")
        self.export_selected_button = QPushButton("导出选中信号…"); self.export_results_button = QPushButton("导出全部结果…")
        self.delete_region_button.clicked.connect(self.delete_selected_region)
        self.export_selected_button.clicked.connect(self.export_selected_results); self.export_results_button.clicked.connect(self.export_results)
        row.addWidget(self.delete_region_button); row.addWidget(self.export_selected_button); row.addWidget(self.export_results_button); layout.addLayout(row)
        hint = QLabel("区间表支持 Ctrl/Shift 多选。快捷键：←/→ 移动选择框，↑/↓ 切换文件，Shift+←/→ 精细移动，Ctrl+← 缩窄、Ctrl+→ 加宽；A 候选，R 待复查，X 排除，S 保存区间，F 切换 FFT 范围，Space 显示/隐藏空白。")
        hint.setWordWrap(True); hint.setStyleSheet("color:#56606A;padding:5px"); layout.addWidget(hint); return tab

    def time_display_scale(self):
        return 1000.0 if self.time_unit_combo.currentIndex() == 1 else 1.0

    def configure_time_inputs(self):
        if self.current_values is None or self.current_channel is None: return
        scale = self.time_display_scale()
        duration = max(0.0, (len(self.current_values) - 1) * self.current_channel.dt)
        step = max(self.current_channel.dt * scale, 1e-9)
        decimals = 6 if scale == 1000.0 else 9
        for spin in (self.start_time_spin, self.end_time_spin, self.duration_time_spin):
            spin.setDecimals(decimals); spin.setSingleStep(step); spin.setRange(0.0, duration * scale)
        minimum_width = min(duration, self.current_channel.dt * 16) * scale
        self.duration_time_spin.setMinimum(minimum_width)
        self.sync_time_inputs()

    def sync_time_inputs(self, start=None, end=None):
        if self.current_values is None or self.current_channel is None: return
        if start is None or end is None: start, end = sorted(self.region.getRegion())
        scale = self.time_display_scale()
        for spin in (self.start_time_spin, self.end_time_spin, self.duration_time_spin): spin.blockSignals(True)
        self.start_time_spin.setValue(start * scale); self.end_time_spin.setValue(end * scale)
        self.duration_time_spin.setValue(max(0.0, end - start) * scale)
        for spin in (self.start_time_spin, self.end_time_spin, self.duration_time_spin): spin.blockSignals(False)

    def on_time_unit_changed(self, _index):
        self.configure_time_inputs()

    def apply_time_input(self, source):
        if self.current_values is None or self.current_channel is None: return
        scale = self.time_display_scale(); total = max(0.0, (len(self.current_values) - 1) * self.current_channel.dt)
        minimum_width = min(total, self.current_channel.dt * 16)
        start, end = sorted(self.region.getRegion())
        if source == "start":
            new_start = min(max(0.0, self.start_time_spin.value() / scale), max(0.0, total - minimum_width))
            new_end = min(total, max(end, new_start + minimum_width))
        elif source == "end":
            new_end = min(total, max(minimum_width, self.end_time_spin.value() / scale))
            new_start = max(0.0, min(start, new_end - minimum_width))
        else:
            width = min(total, max(minimum_width, self.duration_time_spin.value() / scale))
            new_start, new_end = start, start + width
            if new_end > total: new_start, new_end = max(0.0, total - width), total
        self.region.setRegion((new_start, new_end))
        self.statusBar().showMessage(f"局部时间窗口：{new_start:.6g}–{new_end:.6g} s，宽度 {new_end - new_start:.6g} s", 3500)

    def choose_data_folder(self):
        start = self.settings.get("last_data_folder", str(Path.home()))
        folder = QFileDialog.getExistingDirectory(self, "选择 TDMS 数据文件夹", start)
        if folder:
            self.open_data_folder(Path(folder))

    def open_session_dialog(self):
        start = str(self.active_session_file or self.data_folder or Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "打开处理会话", start,
            "TDMS 会话 (*.tdms-session.json *.json);;所有文件 (*)",
        )
        if path:
            self.open_session_path(Path(path))

    def open_session_path(self, path: Path, startup=False):
        try:
            state = load_session_file(path)
        except (OSError, ValueError) as exc:
            if startup:
                self.settings.pop("last_session_file", None); self._save_settings()
                last_folder = self.settings.get("last_data_folder", "")
                if last_folder and Path(last_folder).is_dir(): self.open_data_folder(Path(last_folder))
            else:
                QMessageBox.critical(self, "无法打开会话", str(exc))
            return
        folder = Path(state.get("data_folder", ""))
        try:
            folder_available = folder.is_dir() and bool(discover_tdms(folder))
        except OSError:
            folder_available = False
        if not folder_available:
            if startup:
                self.settings.pop("last_session_file", None); self._save_settings()
                last_folder = self.settings.get("last_data_folder", "")
                if last_folder and Path(last_folder).is_dir(): self.open_data_folder(Path(last_folder))
                return
            QMessageBox.information(self, "重新定位数据", "原数据文件夹不可用，请选择当前 TDMS 数据文件夹。")
            selected = QFileDialog.getExistingDirectory(self, "重新定位 TDMS 数据文件夹", str(path.parent))
            if not selected: return
            folder = Path(selected).resolve()
            try:
                if not discover_tdms(folder):
                    raise ValueError("所选文件夹中没有 TDMS 文件")
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "无法定位数据", str(exc)); return
            state = normalize_session(state, folder)
        active_file = path if path.name.lower().endswith(".tdms-session.json") else None
        self.open_data_folder(folder, session_override=state, session_file=active_file)

    def save_progress(self):
        if not self.session:
            QMessageBox.information(self, "保存进度", "请先选择 TDMS 数据文件夹。")
            return
        if self.save_session_now():
            self.statusBar().showMessage("处理进度已保存", 4000)

    def save_session_as(self):
        if not self.session or not self.data_folder:
            QMessageBox.information(self, "另存会话", "请先选择 TDMS 数据文件夹。")
            return
        default = Path(self.data_folder) / f"{self.session.get('session_name') or Path(self.data_folder).name}.tdms-session.json"
        path, _ = QFileDialog.getSaveFileName(self, "另存处理会话", str(default), "TDMS 会话 (*.tdms-session.json)")
        if not path: return
        if not path.lower().endswith(".tdms-session.json"):
            path += ".tdms-session.json"
        self.active_session_file = Path(path).resolve()
        self.session["session_name"] = self.active_session_file.name.removesuffix(".tdms-session.json")
        self.settings["last_session_file"] = str(self.active_session_file); self._save_settings()
        if self.save_session_now():
            QMessageBox.information(self, "会话已保存", f"处理会话已保存到：\n{self.active_session_file}")

    def choose_blank_folder(self):
        start = str(self.blank_folder or self.data_folder or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择空白 TDMS 文件夹", start)
        if folder:
            self.blank_folder = Path(folder).resolve(); self.blank_folder_edit.setText(str(self.blank_folder))
            if self.session is not None:
                self.session["blank_folder"] = str(self.blank_folder); save_session(self.session)
            self.blank_reference = None
            if self.blank_overlay_check.isChecked(): self.start_blank_reference()

    def _apply_processing_controls(self):
        processing = (self.session or {}).get("processing", {})
        controls = (
            (self.time_unit_combo, "time_unit_index", 0, True),
            (self.fft_scope_combo, "fft_scope", "局部框选区间", False),
            (self.spectrum_mode_combo, "spectrum_mode", "FFT 幅度谱", False),
            (self.window_combo, "window", "Hann", False),
        )
        for control, key, fallback, by_index in controls:
            control.blockSignals(True)
            if by_index:
                control.setCurrentIndex(int(processing.get(key, fallback)))
            else:
                value = str(processing.get(key, fallback))
                if control.findText(value) >= 0: control.setCurrentText(value)
            control.blockSignals(False)
        for control, key, fallback in (
            (self.log_x_check, "log_x", False), (self.log_y_check, "log_y", False),
            (self.blank_overlay_check, "blank_overlay", True),
        ):
            control.blockSignals(True); control.setChecked(bool(processing.get(key, fallback))); control.blockSignals(False)
        try:
            minimum = float(processing.get("frequency_min_hz", 0))
            maximum = float(processing.get("frequency_max_hz", 1000))
            if not (np.isfinite(minimum) and np.isfinite(maximum) and 0 <= minimum < maximum <= 1e12):
                raise ValueError("Invalid frequency range")
        except (TypeError, ValueError):
            minimum, maximum = 0.0, 1000.0
        self.frequency_min_hz, self.frequency_max_hz = minimum, maximum
        self.redraw_spectrum()

    def open_data_folder(self, folder: Path, session_override=None, session_file=None):
        try:
            files = discover_tdms(folder)
        except OSError as exc:
            QMessageBox.critical(self, "无法读取文件夹", str(exc)); return
        if not files:
            QMessageBox.warning(self, "没有数据", "所选文件夹中没有 .tdms 文件。"); return
        self.save_session_now()
        self.data_folder, self.files = folder.resolve(), files
        self.session = normalize_session(session_override, self.data_folder) if session_override else load_session(str(self.data_folder))
        self.active_session_file = Path(session_file).resolve() if session_file else None
        saved_blank = self.session.get("blank_folder", "")
        self.blank_folder = Path(saved_blank) if saved_blank and Path(saved_blank).is_dir() else None
        self.data_folder_edit.setText(str(self.data_folder)); self.blank_folder_edit.setText(str(self.blank_folder or ""))
        self.settings["last_data_folder"] = str(self.data_folder)
        if self.active_session_file: self.settings["last_session_file"] = str(self.active_session_file)
        else: self.settings.pop("last_session_file", None)
        self._save_settings(); self._apply_processing_controls()
        self.cache.clear(); self.blank_reference = None
        self.file_list.blockSignals(True); self.file_list.clear()
        for path in files:
            item = QListWidgetItem(); item.setData(Qt.UserRole, str(path)); self.file_list.addItem(item); self.update_file_item(item, path)
        self.file_list.blockSignals(False); self.file_count_label.setText(f"共 {len(files)} 个 TDMS 文件")
        self.cluster_panel.refresh_files()
        self.refresh_region_table()
        current_file = self.session.get("processing", {}).get("current_file", "")
        target_row = next((index for index, path in enumerate(files) if self.file_key(path) == current_file or path.name == current_file), 0)
        self.file_list.setCurrentRow(target_row); self.update_session_status()
        if self.session.pop("_recovered_from_backup", False):
            QMessageBox.warning(self, "会话已恢复", "主会话文件无法读取，程序已从 .bak 备份恢复处理进度。")
        if self.blank_folder and self.blank_overlay_check.isChecked(): self.start_blank_reference()

    def update_file_item(self, item, path):
        marks = (self.session or {}).get("file_marks", {})
        tag = marks.get(self.file_key(path), marks.get(path.name, "未标记"))
        item.setText(f"{TAG_SYMBOLS.get(tag, '○')}  {path.name}"); item.setForeground(QColor(TAG_COLORS.get(tag, "#AAB2BD")))
        item.setToolTip(f"{path}\n标记：{tag}")

    def on_file_row_changed(self, row):
        if 0 <= row < len(self.files):
            path = self.files[row]; key = self.file_key(path)
            processing = (self.session or {}).setdefault("processing", {})
            channel_key = processing.get("current_channel") if processing.get("current_file") == key else None
            processing["current_file"] = key
            if channel_key is None: processing["current_channel"] = ""
            self.schedule_session_save(); self.load_current_file(path, channel_key)

    def load_current_file(self, path, channel_key=None):
        self.cluster_panel.loading = True
        self.cluster_panel.invalidate()
        self.load_token += 1; token = self.load_token
        cache_key = (str(path), channel_key or "AUTO")
        if cache_key in self.cache:
            result = dict(self.cache[cache_key]); result["token"] = token; QTimer.singleShot(0, lambda: self.on_trace_loaded(result)); return
        self.set_busy(True, f"正在读取 {path.name}…")
        worker = LoadWorker(token, path, channel_key)
        self.track_worker(worker)
        worker.signals.result.connect(self.on_trace_loaded); worker.signals.error.connect(self.on_worker_error)
        self.thread_pool.start(worker)

    def track_worker(self, worker):
        self.workers.add(worker)
        worker.signals.result.connect(lambda _=None, w=worker: self.workers.discard(w))
        worker.signals.error.connect(lambda _=None, w=worker: self.workers.discard(w))

    def on_trace_loaded(self, result):
        if result["token"] != self.load_token: return
        self.current_path = Path(result["path"]); self.current_values = result["values"]
        self.current_channel = result["selected"]; self.current_channels = result["channels"]
        self.cluster_panel.loaded()
        if self.session is not None:
            processing = self.session.setdefault("processing", {})
            processing["current_file"] = self.file_key(self.current_path); processing["current_channel"] = self.current_channel.key
            self.schedule_session_save()
        self.last_spectrum = None; self.peaks_label.setText("主要峰：正在计算…")
        plot_item = self.spectrum_plot.getPlotItem(); plot_item.clear()
        canonical = dict(result); canonical.pop("token", None)
        self.cache[(str(self.current_path), self.current_channel.key)] = canonical; self.cache[(str(self.current_path), "AUTO")] = canonical
        while len(self.cache) > 6: self.cache.popitem(last=False)
        self.channel_combo.blockSignals(True); self.channel_combo.clear()
        for channel in self.current_channels: self.channel_combo.addItem(channel.label, channel.key)
        index = next((i for i, channel in enumerate(self.current_channels) if channel.key == self.current_channel.key), 0)
        self.channel_combo.setCurrentIndex(index); self.channel_combo.blockSignals(False)
        self.overview_plot.setLabel("left", f"记录信号 ({self.current_channel.unit})"); self.detail_plot.setLabel("left", f"记录信号 ({self.current_channel.unit})")
        x, y = minmax_envelope(self.current_values, self.current_channel.dt); self.overview_curve.setData(x, y)
        duration = max(0.0, (len(self.current_values) - 1) * self.current_channel.dt)
        self.overview_plot.setXRange(0, max(duration, 0.01), padding=0)
        self.region.setBounds((0.0, duration))
        self.configure_time_inputs()
        saved = self.session.get("view_ranges", {}).get(self.file_key(self.current_path))
        if self.pending_region is not None:
            region = self.pending_region; self.pending_region = None
        elif isinstance(saved, list) and len(saved) == 2:
            region = saved
        else:
            region = [0.0, min(10.0, duration)]
        self.region.setRegion((max(0, region[0]), min(duration, region[1])))
        self.load_current_mark()
        self.overview_plot.setXRange(0, duration, padding=0); self.set_busy(False, f"已载入 {self.current_path.name} — {len(self.current_values):,} 点")
        self.on_region_changed()

    def on_channel_changed(self, index):
        if index >= 0 and self.current_path and self.current_channel:
            key = self.channel_combo.currentData()
            if key and key != self.current_channel.key: self.load_current_file(self.current_path, key)

    def set_detail_mode(self, mode):
        self.detail_view_box.set_interaction_mode(mode)
        for name, button in self.detail_mode_buttons.items():
            button.blockSignals(True); button.setChecked(name == mode); button.blockSignals(False)
            button.setStyleSheet(
                "QToolButton { border: 1px solid transparent; border-radius: 4px; padding: 2px; }"
                "QToolButton:checked { background: #DCEBFA; border-color: #4A90E2; }"
            )

    def on_detail_selection_finished(self, selection):
        if self.current_values is None or self.current_channel is None:
            return
        mode, left, right, top, bottom = selection
        current_y = self.detail_view_box.viewRange()[1]
        if mode in ("time", "xy"):
            duration = max(0.0, (len(self.current_values) - 1) * self.current_channel.dt)
            if duration <= 0:
                return
            start, end = sorted((float(left), float(right)))
            width = min(duration, max(16 * self.current_channel.dt, end - start))
            start = min(max(0.0, (start + end - width) / 2), duration - width)
            # Freeze the untouched axis before replacing the curve's data;
            # otherwise automatic Y scaling can change a time-only selection.
            if mode == "time":
                self.detail_plot.setYRange(*current_y, padding=0)
            self.region.setRegion((start, start + width))
        if mode in ("y", "xy") and bottom > top:
            self.detail_plot.setYRange(float(top), float(bottom), padding=0)

    def detail_amplitude_bounds(self, time_range):
        if self.current_values is None or self.current_channel is None:
            return None
        dt = self.current_channel.dt
        start, end = time_range
        first = max(0, int(np.floor(start / dt)))
        last = min(len(self.current_values), int(np.floor(end / dt)) + 1)
        values = self.current_values[first:last]
        values = values[np.isfinite(values)]
        if not len(values):
            return None
        low, high = float(values.min()), float(values.max())
        span = high - low
        # Flat traces still need a finite, useful display range, including zero signals.
        if span == 0:
            span = max(abs(low) * 0.01, 1e-12)
        return low - span * 0.2, high + span * 0.2

    def limit_detail_zoom_out(self, previous):
        view = self.detail_view_box
        bounds = self.detail_amplitude_bounds(view.viewRange()[0])
        if bounds is None:
            return
        low, high = bounds
        old_bounds = self.detail_amplitude_bounds(previous[0])
        old_width = previous[1][1] - previous[1][0]
        was_fitted = old_bounds is not None and old_width >= (old_bounds[1] - old_bounds[0]) * (1 - 1e-9)
        bottom, top = view.viewRange()[1]
        width = top - bottom
        if was_fitted or width >= high - low:
            bottom, top = low, high
        else:
            # Keep gradual zoom-out for an intentionally magnified vertical selection.
            bottom = min(max(bottom, low), high - width)
            top = bottom + width
        view.setYRange(bottom, top, padding=0)

    def on_detail_range_changed(self, axes):
        if not axes[0] or self.current_values is None or self.current_channel is None:
            return
        dt = self.current_channel.dt
        duration = (len(self.current_values) - 1) * dt
        if duration <= 0:
            return
        start, end = self.detail_plot.getViewBox().viewRange()[0]
        width = min(duration, max(min(duration, 16 * dt), end - start))
        start = min(max(0.0, (start + end - width) / 2), duration - width)
        end = start + width
        # Only manual view changes flow back to the overview. Programmatic
        # range updates in on_region_changed must not create a feedback loop.
        if not np.allclose(self.region.getRegion(), (start, end), rtol=0, atol=dt * 1e-7):
            self.region.setRegion((start, end))
        self.detail_plot.setXRange(start, end, padding=0)

    def on_region_changed(self):
        if self.current_values is None or self.current_channel is None: return
        start, end = sorted(self.region.getRegion()); dt = self.current_channel.dt
        i0 = max(0, min(len(self.current_values) - 1, int(np.floor(round(start / dt, 9)))))
        i1 = max(i0 + 1, min(len(self.current_values), int(np.ceil(round(end / dt, 9)))))
        if end >= (len(self.current_values) - 1) * dt:
            i1 = len(self.current_values)
        self.current_indices = (i0, i1); selected = self.current_values[i0:i1]
        self.sync_time_inputs(start, end)
        x, y = minmax_envelope(selected, dt, start_index=i0, max_bins=8000); self.detail_curve.setData(x, y)
        # Match the selection exactly so each drag keeps its width instead of
        # repeatedly adding plot padding or subtracting a sample interval.
        self.detail_plot.setXRange(start, max(start + dt, end), padding=0)
        stats = trace_statistics(selected)
        self.current_stats = stats
        if self.session is not None and self.current_path:
            self.session.setdefault("view_ranges", {})[self.file_key(self.current_path)] = [float(start), float(end)]
            self.schedule_session_save()
        self.schedule_spectrum()

    def schedule_spectrum(self):
        if self.current_values is not None: self.fft_timer.start(350)

    def start_spectrum(self):
        if self.current_values is None or self.current_channel is None: return
        if self.fft_scope_combo.currentText() == "完整文件":
            values = self.current_values; interval = (0.0, (len(values) - 1) * self.current_channel.dt)
        else:
            i0, i1 = self.current_indices; values = self.current_values[i0:i1]
            interval = (i0 * self.current_channel.dt, (i1 - 1) * self.current_channel.dt)
        if len(values) < 16:
            self.spectrum_info_label.setText("选中区间少于 16 个点，请扩大时间范围。"); return
        self.spectrum_token += 1; token = self.spectrum_token
        self.spectrum_info_label.setText(f"正在计算 {self.fft_scope_combo.currentText()}频谱…")
        worker = SpectrumWorker(token, values, self.current_channel.dt, self.spectrum_mode_combo.currentText(), self.window_combo.currentText(), self.current_channel.unit, interval)
        self.track_worker(worker)
        worker.signals.result.connect(self.on_spectrum_result); worker.signals.error.connect(self.on_worker_error); self.thread_pool.start(worker)

    def on_spectrum_result(self, result):
        if result["token"] != self.spectrum_token: return
        self.last_spectrum = result
        start, end = result["interval"]
        self.spectrum_info_label.setText(
            f"{self.fft_scope_combo.currentText()}：{start:.5f}–{end:.5f} s  |  "
            f"频率分辨率 {result['resolution']:.5g} Hz  |  奈奎斯特频率 {result['frequency'][-1]:.5g} Hz"
        )
        self.update_peak_summary(); self.redraw_spectrum()

    def update_peak_summary(self):
        if not self.last_spectrum:
            self.peaks_label.setText("主要峰：尚未计算"); return
        reference = self.blank_reference if self.blank_overlay_check.isChecked() else None
        parts = []
        for frequency, amplitude in self.last_spectrum["peaks"][:6]:
            text = f"{frequency:.4g} Hz ({amplitude:.3g})"
            if reference and reference["frequency"][0] <= frequency <= reference["frequency"][-1]:
                baseline = float(np.exp(np.interp(np.log(frequency), np.log(reference["frequency"]), np.log(reference["median"]))))
                if baseline > 0: text += f"，空白×{amplitude / baseline:.2g}"
            if abs(frequency / 50 - round(frequency / 50)) < 0.015: text += " [疑似工频]"
            parts.append(text)
        self.peaks_label.setText("主要峰：" + ("；".join(parts) or "未找到"))

    def edit_frequency_range(self):
        dialog = FrequencyRangeDialog(self.frequency_min_hz, self.frequency_max_hz, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.frequency_min_hz, self.frequency_max_hz = dialog.frequency_range()
            self.redraw_spectrum()
            self.schedule_session_save()

    def redraw_spectrum(self, *_):
        item = self.spectrum_plot.getPlotItem(); item.clear()
        if item.legend is not None:
            item.legend.scene().removeItem(item.legend); item.legend = None
        self.spectrum_plot.addLegend(offset=(10, 10), labelTextColor=self.plot_theme["foreground"])
        log_x, log_y = self.log_x_check.isChecked(), self.log_y_check.isChecked()
        self.spectrum_plot.setLogMode(x=log_x, y=log_y)
        minimum, maximum = self.frequency_min_hz, self.frequency_max_hz
        self.frequency_range_button.setToolTip(f"当前范围：{minimum:g}–{maximum:g} Hz")

        def range_mask(frequency):
            return np.isfinite(frequency) & (frequency >= minimum) & (frequency <= maximum) & ((frequency > 0) if log_x else True)

        if self.last_spectrum:
            mask = range_mask(self.last_spectrum["frequency"])
            f, y = display_spectrum(self.last_spectrum["frequency"][mask], self.last_spectrum["spectrum"][mask], log_x=log_x, log_y=log_y)
            self.spectrum_plot.plot(f, y, pen=pg.mkPen(self.plot_theme["spectrum"], width=self.plot_line_width()), name="当前数据")
            self.spectrum_plot.setLabel("left", f"频谱 ({self.last_spectrum['y_unit']})")
        if self.blank_overlay_check.isChecked() and self.blank_reference:
            ref = self.blank_reference; color = QColor(self.plot_theme["blank"])
            mask = range_mask(ref["frequency"])
            low = self.spectrum_plot.plot(ref["frequency"][mask], ref["q25"][mask], pen=pg.mkPen(color, width=self.plot_line_width()))
            high = self.spectrum_plot.plot(ref["frequency"][mask], ref["q75"][mask], pen=pg.mkPen(color, width=self.plot_line_width()))
            fill = QColor(color); fill.setAlpha(42); self.spectrum_plot.addItem(pg.FillBetweenItem(low, high, brush=fill))
            self.spectrum_plot.plot(ref["frequency"][mask], ref["median"][mask], pen=pg.mkPen(color, width=self.plot_line_width()), name="空白中位数")
        if log_x:
            # Zero has no logarithm; use a positive display floor without changing the saved range.
            minimum = minimum if minimum > 0 else maximum / 1000
            minimum, maximum = np.log10(minimum), np.log10(maximum)
        self.spectrum_plot.setXRange(minimum, maximum, padding=0)
        self.spectrum_plot.enableAutoRange(axis="y", enable=True)

    def on_spectrum_setting_changed(self):
        self.last_spectrum = None; self.blank_reference = None; self.schedule_spectrum()
        if self.blank_overlay_check.isChecked() and self.blank_folder: self.start_blank_reference()

    def on_blank_overlay_changed(self, checked):
        if checked and self.blank_folder and self.blank_reference is None: self.start_blank_reference()
        else: self.update_peak_summary(); self.redraw_spectrum()

    def start_blank_reference(self):
        if not self.blank_folder: return
        self.blank_token += 1; worker = BlankWorker(self.blank_token, self.blank_folder, self.spectrum_mode_combo.currentText(), self.window_combo.currentText(), limit=10)
        self.track_worker(worker)
        worker.signals.progress.connect(lambda message: self.statusBar().showMessage(message))
        worker.signals.result.connect(self.on_blank_result); worker.signals.error.connect(self.on_worker_error); self.thread_pool.start(worker)

    def on_blank_result(self, result):
        if result["token"] != self.blank_token: return
        self.blank_reference = result; self.progress.setRange(0, 1); self.progress.setValue(1)
        self.statusBar().showMessage(f"空白参考已完成：均匀抽取 {len(result['files'])} 个文件", 7000)
        self.update_peak_summary(); self.redraw_spectrum()

    def load_current_mark(self):
        if not self.session or not self.current_path: return
        key = self.file_key(self.current_path)
        self.tag_combo.blockSignals(True); self.note_edit.blockSignals(True)
        self.tag_combo.setCurrentText(self.session.get("file_marks", {}).get(key, self.session.get("file_marks", {}).get(self.current_path.name, "未标记")))
        self.note_edit.setPlainText(self.session.get("file_notes", {}).get(key, self.session.get("file_notes", {}).get(self.current_path.name, "")))
        self.tag_combo.blockSignals(False); self.note_edit.blockSignals(False)

    def on_current_mark_edited(self, *_):
        if not self.session or not self.current_path: return
        key = self.file_key(self.current_path)
        self.session.setdefault("file_marks", {})[key] = self.tag_combo.currentText()
        self.session.setdefault("file_notes", {})[key] = self.note_edit.toPlainText().strip()
        row = self.file_list.currentRow()
        if 0 <= row < len(self.files): self.update_file_item(self.file_list.item(row), self.current_path)
        self.schedule_session_save(); self.update_session_status(pending=True)

    def save_current_mark(self, silent=False):
        if not self.session or not self.current_path: return
        self.on_current_mark_edited()
        self.save_session_now()
        if not silent: self.statusBar().showMessage(f"已保存：{self.current_path.name} → {self.tag_combo.currentText()}", 3500)

    def quick_tag(self, tag):
        self.tag_combo.setCurrentText(tag); self.save_current_mark()

    def add_current_region(self):
        if not self.session or not self.current_path or self.current_values is None: return
        i0, i1 = self.current_indices; tag = self.tag_combo.currentText()
        if tag == "未标记": tag = "候选"; self.tag_combo.setCurrentText(tag)
        self.save_current_mark(silent=True)
        region_id = uuid.uuid4().hex[:12]
        snapshot_folder = snapshots_dir(str(self.data_folder))
        overview_path = snapshot_folder / f"{region_id}_overview.png"
        detail_path = snapshot_folder / f"{region_id}_time.png"; spectrum_path = snapshot_folder / f"{region_id}_spectrum.png"
        combined_path = snapshot_folder / f"{region_id}_combined.png"
        record = {
            "id": region_id, "file": self.file_key(self.current_path), "file_name": self.current_path.name,
            "channel": self.current_channel.key, "start_s": float(i0 * self.current_channel.dt),
            "end_s": float((i1 - 1) * self.current_channel.dt), "tag": tag,
            "start_index": i0, "end_index_exclusive": i1, "current_unit": self.current_channel.unit,
            "note": self.note_edit.toPlainText().strip(), "statistics": self.current_stats,
            "peaks": self.last_spectrum["peaks"] if self.last_spectrum else [],
            "spectrum_mode": self.spectrum_mode_combo.currentText(), "window": self.window_combo.currentText(),
            "overview_snapshot": str(overview_path), "time_snapshot": str(detail_path),
            "spectrum_snapshot": str(spectrum_path), "combined_snapshot": str(combined_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        if self.cluster_panel.result is not None:
            result = self.cluster_panel.result
            record["cluster_detection"] = {
                "parameters": dict(result["parameters"]), "baseline": result["baseline"],
                "kernel": dict(result["kernel"]), "analysis_start_index": result["offset"],
                "analysis_end_index_exclusive": result["end_index_exclusive"],
                "manually_reviewed": True,
            }
        self.export_plot_pixmap("overview").save(str(overview_path), "PNG")
        self.export_plot_pixmap("time").save(str(detail_path), "PNG"); self.export_plot_pixmap("spectrum").save(str(spectrum_path), "PNG")
        self.combined_plot_pixmap(record).save(str(combined_path), "PNG")
        self.session.setdefault("regions", []).append(record)
        self.save_session_now(); self.refresh_region_table()
        self.statusBar().showMessage(f"已保存候选区间：{record['start_s']:.4f}–{record['end_s']:.4f} s", 5000)

    def refresh_region_table(self):
        regions = (self.session or {}).get("regions", []); self.region_table.setRowCount(len(regions))
        for row, region in enumerate(regions):
            values = (region.get("file_name", Path(region.get("file", "")).name), f"{region.get('start_s', 0):.5f}", f"{region.get('end_s', 0):.5f}", region.get("tag", ""), region.get("note", ""))
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value)); item.setData(Qt.UserRole, region.get("id")); self.region_table.setItem(row, col, item)
        self.region_table.resizeColumnsToContents()

    def jump_to_region(self, index):
        row = index.row() if hasattr(index, "row") else int(index)
        item = self.region_table.item(row, 0)
        if not item or not self.session: return
        region = next((r for r in self.session.get("regions", []) if r.get("id") == item.data(Qt.UserRole)), None)
        if not region: return
        file_index = next((i for i, path in enumerate(self.files) if self.file_key(path) == region.get("file") or path.name == region.get("file_name")), -1)
        if file_index < 0: return
        selected = (float(region["start_s"]), float(region["end_s"]))
        if file_index == self.file_list.currentRow() and self.current_path == self.files[file_index]:
            self.region.setRegion(selected)
        else:
            self.pending_region = selected
            if file_index == self.file_list.currentRow(): self.load_current_file(self.files[file_index])
            else: self.file_list.setCurrentRow(file_index)

    def selected_region_ids(self):
        if not self.region_table.selectionModel(): return []
        rows = sorted({index.row() for index in self.region_table.selectionModel().selectedRows()})
        return [
            self.region_table.item(row, 0).data(Qt.UserRole)
            for row in rows if self.region_table.item(row, 0)
        ]

    def delete_selected_region(self):
        if not self.session: return
        region_ids = set(self.selected_region_ids())
        if not region_ids:
            QMessageBox.information(self, "删除区间", "请先在区间表中选择一条或多条记录。")
            return
        prompt = f"确定删除选中的 {len(region_ids)} 条筛选记录吗？原始 TDMS 不会受影响。"
        if QMessageBox.question(self, "批量删除区间", prompt) != QMessageBox.Yes: return
        self.session["regions"] = [region for region in self.session.get("regions", []) if region.get("id") not in region_ids]
        self.save_session_now(); self.refresh_region_table()

    def export_local_csv(self):
        if self.current_values is None or self.current_path is None: return
        default = str(self.current_path.with_name(f"{self.current_path.stem}_selected.csv"))
        path, _ = QFileDialog.getSaveFileName(self, "导出局部数据", default, "CSV 文件 (*.csv)")
        if not path: return
        i0, i1 = self.current_indices; values = self.current_values[i0:i1]
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle); writer.writerow(["time_s", f"signal_{self.current_channel.unit}"])
            for index, value in enumerate(values, i0): writer.writerow([index * self.current_channel.dt, value])
        self.statusBar().showMessage(f"已导出 {len(values):,} 点：{path}", 6000)

    def export_plot_pixmap(self, kind):
        if kind == "spectrum":
            unit = self.last_spectrum.get("y_unit", "") if self.last_spectrum else ""
            label = "PSD" if "Welch" in self.spectrum_mode_combo.currentText() else "Amplitude"
            return figure_pixmap(self.spectrum_plot, xlabel="Frequency (Hz)",
                                 ylabel=f"{label} ({unit})" if unit else label,
                                 log_x=self.log_x_check.isChecked(), log_y=self.log_y_check.isChecked())
        unit = getattr(self.current_channel, "unit", "")
        label = "Current" if unit in ("A", "mA", "uA", "µA", "μA", "nA", "pA") else "Signal"
        return figure_pixmap(self.overview_plot if kind == "overview" else self.detail_plot,
                             xlabel="Time (s)", ylabel=f"{label} ({unit})" if unit else label)

    def combined_plot_pixmap(self, region=None):
        if region is None:
            i0, i1 = self.current_indices
            region = {
                "file_name": self.current_path.name if self.current_path else "signal.tdms",
                "channel": self.current_channel.key if self.current_channel else "",
                "start_s": i0 * self.current_channel.dt if self.current_channel else 0.0,
                "end_s": (i1 - 1) * self.current_channel.dt if self.current_channel and i1 else 0.0,
                "note": self.note_edit.toPlainText().strip(),
            }
        overview = self.export_plot_pixmap("overview"); detail = self.export_plot_pixmap("time")
        target_width = max(900, overview.width(), detail.width())
        content_width = target_width - 48
        overview = overview.scaledToWidth(content_width, Qt.SmoothTransformation)
        detail = detail.scaledToWidth(content_width, Qt.SmoothTransformation)
        title_height, panel_height, gap, padding = 82, 34, 18, 24
        total_height = title_height + panel_height + overview.height() + gap + panel_height + detail.height() + padding
        canvas = QPixmap(target_width, total_height); canvas.fill(QColor("white"))
        painter = QPainter(canvas); foreground = QColor("black"); accent = QColor("black")
        painter.setPen(foreground); painter.setFont(QFont("Microsoft YaHei UI", 16, QFont.DemiBold))
        painter.drawText(QRect(padding, 8, content_width, 30), Qt.AlignCenter, "I–T 信号全局—局部组合图")
        metadata = (
            f"{region.get('file_name', '')}  ·  {region.get('channel', '')}  ·  "
            f"选区 {float(region.get('start_s', 0)):.5f}–{float(region.get('end_s', 0)):.5f} s  ·  "
            f"备注：{region.get('note') or '无备注'}"
        )
        painter.setFont(QFont("Microsoft YaHei UI", 9)); metadata = painter.fontMetrics().elidedText(metadata, Qt.ElideRight, content_width)
        painter.drawText(QRect(padding, 42, content_width, 25), Qt.AlignCenter, metadata)
        y = title_height; painter.setPen(accent); painter.setFont(QFont("Microsoft YaHei UI", 11, QFont.DemiBold))
        painter.drawText(QRect(padding, y, content_width, panel_height), Qt.AlignLeft | Qt.AlignVCenter, "A  全局 I–T 信号")
        y += panel_height; painter.drawPixmap(padding, y, overview); y += overview.height() + gap
        painter.drawText(QRect(padding, y, content_width, panel_height), Qt.AlignLeft | Qt.AlignVCenter, "B  选区局部放大")
        y += panel_height; painter.drawPixmap(padding, y, detail); painter.end()
        return canvas

    def export_combined_image(self):
        if self.current_path is None or self.current_channel is None: return
        folder = QFileDialog.getExistingDirectory(self, "选择组合图导出文件夹", str(self.data_folder))
        if not folder: return
        i0, i1 = self.current_indices
        region = {
            "file_name": self.current_path.name, "channel": self.current_channel.key,
            "start_s": i0 * self.current_channel.dt, "end_s": (i1 - 1) * self.current_channel.dt,
            "note": self.note_edit.toPlainText().strip(),
        }
        output = Path(folder); basename = unique_export_basename(output, region_export_basename(region), ("combined",))
        path = output / f"{basename}_combined.png"
        self.combined_plot_pixmap(region).save(str(path), "PNG")
        self.statusBar().showMessage(f"全局—局部组合图已导出：{path}", 6000)

    def export_current_images(self):
        if self.current_path is None: return
        folder = QFileDialog.getExistingDirectory(self, "选择图像导出文件夹", str(self.data_folder))
        if not folder: return
        i0, i1 = self.current_indices
        output = Path(folder)
        export_region = {
            "file_name": self.current_path.name,
            "channel": self.current_channel.key,
            "start_s": i0 * self.current_channel.dt,
            "end_s": (i1 - 1) * self.current_channel.dt,
            "note": self.note_edit.toPlainText().strip(),
        }
        basename = unique_export_basename(
            output, region_export_basename(export_region), ("overview", "time", "spectrum", "combined")
        )
        self.export_plot_pixmap("overview").save(str(output / f"{basename}_overview.png"), "PNG")
        self.export_plot_pixmap("time").save(str(output / f"{basename}_time.png"), "PNG")
        self.export_plot_pixmap("spectrum").save(str(output / f"{basename}_spectrum.png"), "PNG")
        self.combined_plot_pixmap(export_region).save(str(output / f"{basename}_combined.png"), "PNG")
        self.statusBar().showMessage(f"当前图像及组合图已导出到 {output}", 6000)

    def export_results(self):
        regions = list((self.session or {}).get("regions", []))
        self._export_regions(regions, selected_only=False)

    def export_selected_results(self):
        if not self.session: return
        region_ids = set(self.selected_region_ids())
        if not region_ids:
            QMessageBox.information(self, "导出选中信号", "请先在区间表中选择一条或多条记录。")
            return
        regions = [region for region in self.session.get("regions", []) if region.get("id") in region_ids]
        self._export_regions(regions, selected_only=True)

    def _export_session_state(self, regions, selected_only):
        state = dict(self.session)
        state["regions"] = regions
        if not selected_only:
            return state
        file_keys = {region.get("file") for region in regions}
        file_names = {region.get("file_name") for region in regions}
        for key in ("file_marks", "file_notes"):
            state[key] = {
                file_name: value for file_name, value in self.session.get(key, {}).items()
                if file_name in file_keys or Path(file_name).name in file_names
            }
        return state

    def _snapshot_source(self, region, key):
        source = Path(region.get(key, ""))
        if not source.is_file() and source.name:
            portable_source = snapshots_dir(str(self.data_folder)) / source.name
            if portable_source.is_file():
                source = portable_source
            else:
                source = next(
                    (path for path in (app_data_dir() / "snapshots").glob(f"*/{source.name}") if path.is_file()),
                    source,
                )
        return source if source.is_file() else None

    def _unique_result_folder(self, parent, prefix):
        base = parent / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}"
        candidate = base
        number = 2
        while candidate.exists():
            candidate = parent / f"{base.name}_{number}"
            number += 1
        return candidate

    def _choose_export_options(self, region_count):
        defaults = dict(DEFAULT_EXPORT_OPTIONS)
        saved = self.settings.get("export_options", {})
        if isinstance(saved, dict): defaults.update(saved)
        dialog = ExportOptionsDialog(defaults, region_count, self)
        if dialog.exec() != QDialog.Accepted: return None
        options = dialog.options()
        if dialog.remember_check.isChecked():
            self.settings["export_options"] = options; self._save_settings()
        return options

    def _write_html_report(self, path, regions, title):
        rows = []
        for region in regions:
            peaks = ", ".join(f"{f:.5g} Hz" for f, _ in region.get("peaks", [])[:5])
            rows.append(f"<tr><td>{html.escape(region.get('file_name', ''))}</td><td>{region.get('start_s', 0):.5f}–{region.get('end_s', 0):.5f}</td><td>{html.escape(region.get('tag', ''))}</td><td>{html.escape(peaks)}</td><td>{html.escape(region.get('note', ''))}</td></tr>")
        report = f"""<!doctype html><meta charset='utf-8'><title>TDMS 筛选结果</title>
<style>body{{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:32px;color:#263238}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd3d8;padding:7px;text-align:left}}th{{background:#eef2f5}}</style>
<h1>TDMS {title}</h1><p>数据文件夹：{html.escape(str(self.data_folder))}</p><p>导出时间：{datetime.now():%Y-%m-%d %H:%M:%S}</p>
<table><tr><th>文件</th><th>区间 (s)</th><th>标签</th><th>主要峰</th><th>备注</th></tr>{''.join(rows)}</table>"""
        path.write_text(report, encoding="utf-8")

    def _export_regions(self, regions, selected_only, options=None, destination_parent=None):
        if not self.session or not self.data_folder: return
        if not regions:
            QMessageBox.information(self, "导出筛选结果", "当前没有可导出的已保存区间。")
            return
        title = "选中信号" if selected_only else "全部筛选结果"
        if options is None:
            options = self._choose_export_options(len(regions))
            if options is None: return
        options = {key: bool(options.get(key, False)) for key in DEFAULT_EXPORT_OPTIONS}
        if not any(options.values()):
            QMessageBox.information(self, "导出筛选结果", "请至少选择一项导出内容。")
            return
        folder = destination_parent or QFileDialog.getExistingDirectory(
            self, f"选择{title}导出文件夹", str(self.data_folder)
        )
        if not folder: return
        prefix = "TDMS选中信号" if selected_only else "TDMS筛选结果"
        out = self._unique_result_folder(Path(folder), prefix)
        out.mkdir(parents=True)
        warnings = []
        raw_rows = child_rows = child_files = 0
        self.set_busy(True, f"正在导出{title}…")
        QApplication.processEvents()
        try:
            if options["feature_summary"] or options["raw_summary"]:
                summary_out = out / "summary"; summary_out.mkdir()
                if options["feature_summary"]:
                    write_feature_csv(summary_out / "feature.csv", regions)
                if options["raw_summary"]:
                    raw_rows, raw_warnings = write_it_raw_csv(
                        summary_out / "I-T_raw_data.csv", regions, Path(self.data_folder)
                    )
                    warnings.extend(raw_warnings)
            if options["individual_csv"]:
                child_files, child_rows, child_warnings = write_individual_signal_csvs(
                    out / "signals", regions, Path(self.data_folder)
                )
                warnings.extend(child_warnings)
            requested_images = [
                ("overview_snapshot", "overview") if options["image_overview"] else None,
                ("time_snapshot", "time") if options["image_time"] else None,
                ("spectrum_snapshot", "spectrum") if options["image_spectrum"] else None,
                ("combined_snapshot", "combined") if options["image_combined"] else None,
            ]
            requested_images = [spec for spec in requested_images if spec]
            if requested_images:
                image_out = out / "images"; image_out.mkdir()
                for region in regions:
                    basename = unique_export_basename(
                        image_out, region_export_basename(region), tuple(spec[1] for spec in requested_images)
                    )
                    for key, image_type in requested_images:
                        source = self._snapshot_source(region, key)
                        if source:
                            shutil.copy2(source, image_out / f"{basename}_{image_type}.png")
                        else:
                            warnings.append(f"找不到快照：{region.get('file_name', '')} / {image_type}")
            if options["session_json"]:
                export_state = self._export_session_state(regions, selected_only)
                (out / "analysis_session.json").write_text(
                    json.dumps(export_state, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            if options["html_report"]:
                self._write_html_report(out / "report.html", regions, title)
        except Exception as exc:
            self.set_busy(False, "导出失败")
            QMessageBox.critical(self, "导出失败", f"导出过程中发生错误：\n{exc}\n\n已创建的目录：\n{out}")
            return
        message = f"已导出 {len(regions)} 条筛选信号：\n{out}"
        if options["raw_summary"]: message += f"\nI–T 总表：{raw_rows:,} 个数据点"
        if options["individual_csv"]: message += f"\nCSV 子表：{child_files} 个文件，{child_rows:,} 个数据点"
        if warnings:
            warnings = list(dict.fromkeys(warnings))
            preview = "\n".join(f"• {warning}" for warning in warnings[:5])
            remainder = f"\n另有 {len(warnings) - 5} 条警告。" if len(warnings) > 5 else ""
            message += f"\n\n导出完成，但有以下警告：\n{preview}{remainder}"
        self.set_busy(False, f"{title}已导出：{out}")
        QMessageBox.information(self, "导出完成", message)
        return out

    def move_region(self, direction, fraction=0.25):
        if self.current_values is None: return
        start, end = sorted(self.region.getRegion()); width = end - start
        duration = (len(self.current_values) - 1) * self.current_channel.dt; shift = direction * max(width * fraction, self.current_channel.dt)
        new_start, new_end = start + shift, end + shift
        if new_start < 0: new_start, new_end = 0.0, min(duration, width)
        elif new_end > duration: new_end, new_start = duration, max(0.0, duration - width)
        self.region.setRegion((new_start, new_end))

    def resize_region(self, wider):
        if self.current_values is None: return
        start, end = sorted(self.region.getRegion()); width = end - start; duration = (len(self.current_values) - 1) * self.current_channel.dt
        new_width = min(duration, max(min(duration, self.current_channel.dt * 16), width * (1.25 if wider else 0.8)))
        center = (start + end) / 2; new_start, new_end = center - new_width / 2, center + new_width / 2
        if new_start < 0: new_start, new_end = 0.0, new_width
        elif new_end > duration: new_start, new_end = duration - new_width, duration
        self.region.setRegion((new_start, new_end))

    def previous_file(self):
        if self.file_list.currentRow() > 0: self.file_list.setCurrentRow(self.file_list.currentRow() - 1)

    def next_file(self):
        if 0 <= self.file_list.currentRow() < self.file_list.count() - 1: self.file_list.setCurrentRow(self.file_list.currentRow() + 1)

    def toggle_fft_scope(self):
        self.fft_scope_combo.setCurrentIndex(1 - self.fft_scope_combo.currentIndex())

    def _load_theme(self):
        name = self.settings.get("theme_name", "深色高对比（推荐）")
        if name in PLOT_THEMES: self.plot_theme = dict(PLOT_THEMES[name])
        else:
            name = "自定义"; self.plot_theme.update(self.settings.get("custom_theme", {}))
        self.theme_combo.blockSignals(True); self.theme_combo.setCurrentText(name); self.theme_combo.blockSignals(False)

    def on_theme_changed(self, name):
        if name in PLOT_THEMES:
            self.plot_theme = dict(PLOT_THEMES[name]); self.settings["theme_name"] = name; self._save_settings(); self.apply_plot_theme()

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.plot_theme[key]), self, f"选择{self.color_buttons[key].text()}颜色")
        if not color.isValid(): return
        self.plot_theme[key] = color.name()
        if key == "background": self.plot_theme["foreground"] = "#F4F7FA" if color.lightness() < 145 else "#263238"
        self.theme_combo.blockSignals(True); self.theme_combo.setCurrentText("自定义"); self.theme_combo.blockSignals(False)
        self.settings["theme_name"] = "自定义"; self.settings["custom_theme"] = self.plot_theme; self._save_settings(); self.apply_plot_theme()

    def plot_line_width(self):
        return self.line_width_spin.value() * self.logicalDpiX() / 72.0

    def on_plot_style_changed(self, *_):
        self.settings["plot_grid"] = self.grid_check.isChecked()
        self.settings["plot_line_width_pt"] = self.line_width_spin.value()
        self._save_settings()
        self.apply_plot_theme()

    def apply_plot_theme(self):
        theme = self.plot_theme
        for plot in (self.overview_plot, self.detail_plot, self.spectrum_plot):
            plot.setBackground(theme["background"])
            plot.showGrid(x=self.grid_check.isChecked(), y=self.grid_check.isChecked(), alpha=0.18)
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name); axis.setTextPen(theme["foreground"]); axis.setPen(theme["foreground"]); axis.label.setDefaultTextColor(QColor(theme["foreground"]))
        self.overview_plot.setTitle("完整数据总览", color=theme["foreground"]); self.detail_plot.setTitle("局部波形", color=theme["foreground"]); self.spectrum_plot.setTitle("傅里叶变换 / 功率谱", color=theme["foreground"])
        self.overview_curve.setPen(pg.mkPen(theme["time"], width=self.plot_line_width())); self.detail_curve.setPen(pg.mkPen(theme["time"], width=self.plot_line_width()))
        region = QColor(theme["region"]); fill = QColor(region); fill.setAlpha(48)
        for line in self.region.lines: line.setPen(pg.mkPen(region, width=1.3)); line.setHoverPen(pg.mkPen(region.lighter(135), width=2))
        self.region.setBrush(fill)
        for key, button in self.color_buttons.items():
            color = QColor(theme[key]); text = "#000000" if color.lightness() > 145 else "#FFFFFF"
            button.setStyleSheet(f"background:{color.name()};color:{text};border:1px solid #777;padding:4px")
        self.redraw_spectrum()

    def capture_processing_state(self):
        if self.session is None: return
        processing = self.session.setdefault("processing", {})
        row = self.file_list.currentRow()
        selected_path = self.files[row] if 0 <= row < len(self.files) else self.current_path
        if selected_path: processing["current_file"] = self.file_key(selected_path)
        if self.current_channel and self.current_path and selected_path and Path(self.current_path).resolve() == Path(selected_path).resolve():
            processing["current_channel"] = self.current_channel.key
        processing.update({
            "time_unit_index": self.time_unit_combo.currentIndex(),
            "fft_scope": self.fft_scope_combo.currentText(),
            "spectrum_mode": self.spectrum_mode_combo.currentText(),
            "window": self.window_combo.currentText(),
            "log_x": self.log_x_check.isChecked(), "log_y": self.log_y_check.isChecked(),
            "frequency_min_hz": self.frequency_min_hz, "frequency_max_hz": self.frequency_max_hz,
            "blank_overlay": self.blank_overlay_check.isChecked(),
        })

    def processed_file_count(self):
        if not self.session: return 0
        processed = {
            key for key, tag in self.session.get("file_marks", {}).items()
            if tag and tag != "未标记"
        }
        processed.update(key for key, note in self.session.get("file_notes", {}).items() if str(note).strip())
        processed.update(region.get("file") for region in self.session.get("regions", []) if region.get("file"))
        available = {self.file_key(path) for path in self.files}
        return len(processed & available)

    def update_session_status(self, pending=False):
        if not hasattr(self, "session_status_label") or not self.session:
            return
        name = self.session.get("session_name") or (self.data_folder.name if self.data_folder else "默认会话")
        updated = self.session.get("updated_at", "")
        saved_text = "等待自动保存" if pending else (updated.replace("T", " ") if updated else "尚未保存")
        self.session_status_label.setText(
            f"会话：{name} ｜ 已处理 {self.processed_file_count()}/{len(self.files)} ｜ {saved_text}"
        )

    def schedule_session_save(self, *_):
        if self.session is None: return
        self.capture_processing_state(); self.update_session_status(pending=True)
        self.session_timer.start(700)

    def save_session_now(self):
        if self.session is None: return False
        self.capture_processing_state()
        try:
            save_session(self.session)
            if self.active_session_file: save_session_file(self.session, self.active_session_file)
            self.update_session_status()
            return True
        except OSError as exc:
            self.statusBar().showMessage(f"筛选进度保存失败：{exc}", 8000)
            return False

    def set_busy(self, busy, message):
        self.progress.setRange(0, 0 if busy else 1); self.progress.setValue(0 if busy else 1); self.statusBar().showMessage(message)

    def on_worker_error(self, details):
        self.set_busy(False, "操作失败"); short = details.strip().splitlines()[-1] if details.strip() else "未知错误"
        QMessageBox.critical(self, "操作失败", short)

    def keyPressEvent(self, event: QKeyEvent):
        key, modifiers = event.key(), event.modifiers()
        if key in (Qt.Key_Left, Qt.Key_Right):
            if modifiers & Qt.ControlModifier: self.resize_region(key == Qt.Key_Right)
            else: self.move_region(-1 if key == Qt.Key_Left else 1, 0.05 if modifiers & Qt.ShiftModifier else 0.25)
            return
        actions = {
            Qt.Key_Up: self.previous_file, Qt.Key_Down: self.next_file,
            Qt.Key_A: lambda: self.quick_tag("候选"), Qt.Key_R: lambda: self.quick_tag("待复查"),
            Qt.Key_X: lambda: self.quick_tag("排除"), Qt.Key_S: self.add_current_region,
            Qt.Key_F: self.toggle_fft_scope, Qt.Key_Space: self.blank_overlay_check.toggle,
        }
        if modifiers == Qt.NoModifier and key in actions: actions[key](); return
        if modifiers & Qt.ControlModifier and key == Qt.Key_E: self.export_results(); return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.cluster_panel.cancel_batch()
        self.settings["workspace_layout"] = self.workspace.capture()
        self.save_session_now()
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self._save_settings(); event.accept()
