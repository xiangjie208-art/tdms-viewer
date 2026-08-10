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
from PySide6.QtCore import QByteArray, QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QFileDialog,
    QDoubleSpinBox, QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .core import (
    common_log_reference, compute_spectrum, discover_tdms, display_spectrum,
    dominant_peaks, load_trace, minmax_envelope, trace_statistics,
)
from .session import app_data_dir, load_session, save_session, snapshots_dir


APP_NAME = "TDMS 分子指纹筛选器"
TAGS = ["未标记", "候选", "待复查", "无明显特征", "噪声过大", "排除"]
TAG_SYMBOLS = {"未标记": "○", "候选": "★", "待复查": "?", "无明显特征": "✓", "噪声过大": "!", "排除": "×"}
TAG_COLORS = {
    "未标记": "#AAB2BD", "候选": "#FFB300", "待复查": "#4FC3F7",
    "无明显特征": "#81C784", "噪声过大": "#FF8A65", "排除": "#EF5350",
}
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


def make_plot(title, left_label, bottom_label):
    plot = pg.PlotWidget(background="white")
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
        self.current_path = None
        self.current_values = None
        self.current_channel = None
        self.current_channels = []
        self.current_stats = {}
        self.current_indices = (0, 0)
        self.last_spectrum = None
        self.blank_reference = None
        self.cache = OrderedDict()
        self.load_token = self.spectrum_token = self.blank_token = 0
        self.pending_region = None
        self.workers = set()
        self.plot_theme = dict(PLOT_THEMES["深色高对比（推荐）"])
        self.settings_path = Path(__file__).resolve().parents[1] / "user_data" / "settings.json"
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
        last_folder = self.settings.get("last_data_folder", "")
        if last_folder and Path(last_folder).is_dir():
            QTimer.singleShot(0, lambda: self.open_data_folder(Path(last_folder)))

    def file_key(self, path):
        return str(Path(path).resolve())

    def _build_ui(self):
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(7, 7, 7, 7); grid.setSpacing(7)
        grid.setColumnStretch(0, 34); grid.setColumnStretch(1, 66)
        grid.setRowStretch(0, 43); grid.setRowStretch(1, 57)
        self.setCentralWidget(central)

        self.controls = self._build_controls(); grid.addWidget(self.controls, 0, 0)
        self.overview_plot = make_plot("完整数据总览", "记录信号", "时间 (s)")
        self.overview_curve = self.overview_plot.plot(pen=pg.mkPen("#FFFFFF", width=0.8))
        self.region = pg.LinearRegionItem(values=(0, 10), movable=True)
        self.region.setZValue(10); self.overview_plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self.on_region_changed); grid.addWidget(self.overview_plot, 0, 1)

        detail_box = QWidget(); detail_layout = QVBoxLayout(detail_box); detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_stats_label = QLabel("局部区间：尚未载入数据"); self.detail_stats_label.setWordWrap(True)
        self.detail_stats_label.setStyleSheet("padding:4px 7px;background:#F5F7FA;color:#343A40")
        self.detail_plot = make_plot("局部波形", "记录信号", "时间 (s)")
        self.detail_curve = self.detail_plot.plot(pen=pg.mkPen("#FFFFFF", width=0.85))
        detail_layout.addWidget(self.detail_stats_label); detail_layout.addWidget(self.detail_plot, 1); grid.addWidget(detail_box, 1, 0)

        spectrum_box = QWidget(); spectrum_layout = QVBoxLayout(spectrum_box); spectrum_layout.setContentsMargins(0, 0, 0, 0)
        self.spectrum_info_label = QLabel("频谱：等待选择数据")
        self.spectrum_info_label.setStyleSheet("padding:4px 7px;background:#F5F7FA;color:#343A40")
        self.spectrum_plot = make_plot("傅里叶变换 / 功率谱", "幅值", "频率 (Hz)")
        spectrum_layout.addWidget(self.spectrum_info_label); spectrum_layout.addWidget(self.spectrum_plot, 1); grid.addWidget(spectrum_box, 1, 1)

        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(1); self.progress.setTextVisible(False)
        self.statusBar().addPermanentWidget(self.progress, 0); self.statusBar().showMessage("请选择 TDMS 数据文件夹")

    def _build_controls(self):
        tabs = QTabWidget()
        tabs.addTab(self._scroll_page(self._build_data_tab()), "数据与频谱")
        tabs.addTab(self._scroll_page(self._build_screening_tab()), "筛选记录")
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
        self.spectrum_mode_combo = QComboBox(); self.spectrum_mode_combo.addItems(["FFT 幅度谱", "功率谱密度 (Welch)"])
        self.spectrum_mode_combo.currentIndexChanged.connect(self.on_spectrum_setting_changed); settings_form.addRow("频谱模式", self.spectrum_mode_combo)
        self.window_combo = QComboBox(); self.window_combo.addItems(["Hann", "Hamming", "Blackman", "矩形窗"])
        self.window_combo.currentIndexChanged.connect(self.on_spectrum_setting_changed); settings_form.addRow("窗函数", self.window_combo)
        self.log_x_check = QCheckBox("频率对数坐标"); self.log_x_check.setChecked(True)
        self.log_y_check = QCheckBox("幅值对数坐标"); self.log_y_check.setChecked(True)
        self.log_x_check.toggled.connect(self.redraw_spectrum); self.log_y_check.toggled.connect(self.redraw_spectrum)
        axes = QWidget(); axes_layout = QHBoxLayout(axes); axes_layout.setContentsMargins(0, 0, 0, 0)
        axes_layout.addWidget(self.log_x_check); axes_layout.addWidget(self.log_y_check); settings_form.addRow("坐标", axes)
        self.blank_overlay_check = QCheckBox("叠加空白中位频谱与四分位范围"); self.blank_overlay_check.setChecked(True)
        self.blank_overlay_check.toggled.connect(self.on_blank_overlay_changed); settings_form.addRow("空白参考", self.blank_overlay_check)
        layout.addWidget(settings_group)

        theme_group = QGroupBox("显示主题"); theme_form = QFormLayout(theme_group)
        self.theme_combo = QComboBox(); self.theme_combo.addItems(["深色高对比（推荐）", "浅色", "自定义"])
        self.theme_combo.currentTextChanged.connect(self.on_theme_changed); theme_form.addRow("预设", self.theme_combo)
        color_box = QWidget(); color_grid = QGridLayout(color_box); color_grid.setContentsMargins(0, 0, 0, 0); self.color_buttons = {}
        for index, (key, text) in enumerate((("background", "背景"), ("time", "时域信号"), ("spectrum", "频谱信号"), ("blank", "空白参考"))):
            button = QPushButton(text); button.clicked.connect(lambda _=False, k=key: self.choose_color(k)); self.color_buttons[key] = button
            color_grid.addWidget(button, index // 2, index % 2)
        theme_form.addRow("自定义颜色", color_box); layout.addWidget(theme_group)

        export_row = QHBoxLayout(); self.export_csv_button = QPushButton("导出局部 CSV"); self.export_image_button = QPushButton("导出当前图像")
        self.export_csv_button.clicked.connect(self.export_local_csv); self.export_image_button.clicked.connect(self.export_current_images)
        export_row.addWidget(self.export_csv_button); export_row.addWidget(self.export_image_button); layout.addLayout(export_row)
        self.peaks_label = QLabel("主要峰：尚未计算"); self.peaks_label.setWordWrap(True); self.peaks_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.peaks_label); return tab

    def _build_screening_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        mark_group = QGroupBox("当前文件"); form = QFormLayout(mark_group)
        self.tag_combo = QComboBox(); self.tag_combo.addItems(TAGS); form.addRow("文件标记", self.tag_combo)
        self.note_edit = QPlainTextEdit(); self.note_edit.setPlaceholderText("可记录信号形态、判断依据等…"); self.note_edit.setMaximumHeight(90); form.addRow("备注", self.note_edit)
        save_row = QWidget(); save_layout = QHBoxLayout(save_row); save_layout.setContentsMargins(0, 0, 0, 0)
        self.save_mark_button = QPushButton("保存文件标记"); self.add_region_button = QPushButton("保存当前区间")
        self.save_mark_button.clicked.connect(self.save_current_mark); self.add_region_button.clicked.connect(self.add_current_region)
        save_layout.addWidget(self.save_mark_button); save_layout.addWidget(self.add_region_button); form.addRow(save_row); layout.addWidget(mark_group)
        layout.addWidget(QLabel("已保存的局部区间（双击可跳转）"))
        self.region_table = QTableWidget(0, 5); self.region_table.setHorizontalHeaderLabels(["文件", "起点/s", "终点/s", "标签", "备注"])
        self.region_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.region_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.region_table.doubleClicked.connect(self.jump_to_region); self.region_table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.region_table, 1)
        row = QHBoxLayout(); self.delete_region_button = QPushButton("删除选中区间"); self.export_results_button = QPushButton("导出筛选结果…")
        self.delete_region_button.clicked.connect(self.delete_selected_region); self.export_results_button.clicked.connect(self.export_results)
        row.addWidget(self.delete_region_button); row.addWidget(self.export_results_button); layout.addLayout(row)
        hint = QLabel("快捷键：←/→ 移动选择框，↑/↓ 切换文件，Shift+←/→ 精细移动，Ctrl+← 缩窄、Ctrl+→ 加宽；A 候选，R 待复查，X 排除，S 保存区间，F 切换 FFT 范围，Space 显示/隐藏空白。")
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

    def choose_blank_folder(self):
        start = str(self.blank_folder or self.data_folder or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择空白 TDMS 文件夹", start)
        if folder:
            self.blank_folder = Path(folder).resolve(); self.blank_folder_edit.setText(str(self.blank_folder))
            if self.session is not None:
                self.session["blank_folder"] = str(self.blank_folder); save_session(self.session)
            self.blank_reference = None
            if self.blank_overlay_check.isChecked(): self.start_blank_reference()

    def open_data_folder(self, folder: Path):
        try:
            files = discover_tdms(folder)
        except OSError as exc:
            QMessageBox.critical(self, "无法读取文件夹", str(exc)); return
        if not files:
            QMessageBox.warning(self, "没有数据", "所选文件夹中没有 .tdms 文件。"); return
        self.save_session_now()
        self.data_folder, self.files = folder.resolve(), files
        self.session = load_session(str(self.data_folder))
        saved_blank = self.session.get("blank_folder", "")
        self.blank_folder = Path(saved_blank) if saved_blank and Path(saved_blank).is_dir() else None
        self.data_folder_edit.setText(str(self.data_folder)); self.blank_folder_edit.setText(str(self.blank_folder or ""))
        self.settings["last_data_folder"] = str(self.data_folder); self._save_settings()
        self.cache.clear(); self.blank_reference = None
        self.file_list.blockSignals(True); self.file_list.clear()
        for path in files:
            item = QListWidgetItem(); item.setData(Qt.UserRole, str(path)); self.file_list.addItem(item); self.update_file_item(item, path)
        self.file_list.blockSignals(False); self.file_count_label.setText(f"共 {len(files)} 个 TDMS 文件")
        self.refresh_region_table(); self.file_list.setCurrentRow(0)
        if self.blank_folder and self.blank_overlay_check.isChecked(): self.start_blank_reference()

    def update_file_item(self, item, path):
        marks = (self.session or {}).get("file_marks", {})
        tag = marks.get(self.file_key(path), marks.get(path.name, "未标记"))
        item.setText(f"{TAG_SYMBOLS.get(tag, '○')}  {path.name}"); item.setForeground(QColor(TAG_COLORS.get(tag, "#AAB2BD")))
        item.setToolTip(f"{path}\n标记：{tag}")

    def on_file_row_changed(self, row):
        if 0 <= row < len(self.files):
            self.load_current_file(self.files[row])

    def load_current_file(self, path, channel_key=None):
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

    def on_region_changed(self):
        if self.current_values is None or self.current_channel is None: return
        start, end = sorted(self.region.getRegion()); dt = self.current_channel.dt
        i0 = max(0, min(len(self.current_values) - 1, int(np.floor(start / dt))))
        i1 = max(i0 + 1, min(len(self.current_values), int(np.ceil(end / dt))))
        self.current_indices = (i0, i1); selected = self.current_values[i0:i1]
        self.sync_time_inputs(start, end)
        x, y = minmax_envelope(selected, dt, start_index=i0, max_bins=8000); self.detail_curve.setData(x, y)
        self.detail_plot.setXRange(i0 * dt, max(i0 * dt + dt, (i1 - 1) * dt), padding=0.015)
        stats = trace_statistics(selected)
        self.current_stats = stats
        resolution = 1.0 / max(dt, len(selected) * dt)
        self.detail_stats_label.setText(
            f"局部区间 {i0 * dt:.5f}–{(i1 - 1) * dt:.5f} s  |  {len(selected):,} 点  |  "
            f"均值 {stats['mean']:.5g} {self.current_channel.unit}  |  标准差 {stats['std']:.5g}  |  "
            f"峰峰值 {stats['ptp']:.5g}  |  理论 FFT 分辨率约 {resolution:.4g} Hz"
        )
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

    def redraw_spectrum(self, *_):
        item = self.spectrum_plot.getPlotItem(); item.clear()
        if item.legend is not None:
            item.legend.scene().removeItem(item.legend); item.legend = None
        self.spectrum_plot.addLegend(offset=(10, 10), labelTextColor=self.plot_theme["foreground"])
        self.spectrum_plot.setLogMode(x=self.log_x_check.isChecked(), y=self.log_y_check.isChecked())
        if self.last_spectrum:
            f, y = display_spectrum(self.last_spectrum["frequency"], self.last_spectrum["spectrum"])
            self.spectrum_plot.plot(f, y, pen=pg.mkPen(self.plot_theme["spectrum"], width=1.0), name="当前数据")
            self.spectrum_plot.setLabel("left", f"频谱 ({self.last_spectrum['y_unit']})")
        if self.blank_overlay_check.isChecked() and self.blank_reference:
            ref = self.blank_reference; color = QColor(self.plot_theme["blank"])
            low = self.spectrum_plot.plot(ref["frequency"], ref["q25"], pen=pg.mkPen(color, width=0.5))
            high = self.spectrum_plot.plot(ref["frequency"], ref["q75"], pen=pg.mkPen(color, width=0.5))
            fill = QColor(color); fill.setAlpha(42); self.spectrum_plot.addItem(pg.FillBetweenItem(low, high, brush=fill))
            self.spectrum_plot.plot(ref["frequency"], ref["median"], pen=pg.mkPen(color, width=1.1), name="空白中位数")

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
        self.tag_combo.setCurrentText(self.session.get("file_marks", {}).get(key, self.session.get("file_marks", {}).get(self.current_path.name, "未标记")))
        self.note_edit.setPlainText(self.session.get("file_notes", {}).get(key, self.session.get("file_notes", {}).get(self.current_path.name, "")))

    def save_current_mark(self, silent=False):
        if not self.session or not self.current_path: return
        key = self.file_key(self.current_path)
        self.session.setdefault("file_marks", {})[key] = self.tag_combo.currentText()
        self.session.setdefault("file_notes", {})[key] = self.note_edit.toPlainText().strip()
        row = self.file_list.currentRow()
        if 0 <= row < len(self.files): self.update_file_item(self.file_list.item(row), self.current_path)
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
        detail_path = snapshot_folder / f"{region_id}_time.png"; spectrum_path = snapshot_folder / f"{region_id}_spectrum.png"
        self.detail_plot.grab().save(str(detail_path), "PNG"); self.spectrum_plot.grab().save(str(spectrum_path), "PNG")
        record = {
            "id": region_id, "file": self.file_key(self.current_path), "file_name": self.current_path.name,
            "channel": self.current_channel.key, "start_s": float(i0 * self.current_channel.dt),
            "end_s": float((i1 - 1) * self.current_channel.dt), "tag": tag,
            "note": self.note_edit.toPlainText().strip(), "statistics": self.current_stats,
            "peaks": self.last_spectrum["peaks"] if self.last_spectrum else [],
            "spectrum_mode": self.spectrum_mode_combo.currentText(), "window": self.window_combo.currentText(),
            "time_snapshot": str(detail_path), "spectrum_snapshot": str(spectrum_path),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
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

    def delete_selected_region(self):
        row = self.region_table.currentRow()
        if row < 0 or not self.session: return
        item = self.region_table.item(row, 0)
        if not item: return
        if QMessageBox.question(self, "删除区间", "确定删除选中的筛选记录吗？原始 TDMS 不会受影响。") != QMessageBox.Yes: return
        region_id = item.data(Qt.UserRole)
        self.session["regions"] = [region for region in self.session.get("regions", []) if region.get("id") != region_id]
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

    def export_current_images(self):
        if self.current_path is None: return
        folder = QFileDialog.getExistingDirectory(self, "选择图像导出文件夹", str(self.data_folder))
        if not folder: return
        output = Path(folder); stem = self.current_path.stem
        self.overview_plot.grab().save(str(output / f"{stem}_overview.png"), "PNG")
        self.detail_plot.grab().save(str(output / f"{stem}_local.png"), "PNG")
        self.spectrum_plot.grab().save(str(output / f"{stem}_spectrum.png"), "PNG")
        self.statusBar().showMessage(f"当前三张图已导出到 {output}", 6000)

    def export_results(self):
        if not self.session or not self.data_folder: return
        folder = QFileDialog.getExistingDirectory(self, "选择筛选结果导出文件夹", str(self.data_folder))
        if not folder: return
        out = Path(folder) / f"TDMS筛选结果_{datetime.now():%Y%m%d_%H%M%S}"; out.mkdir(parents=True, exist_ok=True)
        marks = self.session.get("file_marks", {}); notes = self.session.get("file_notes", {})
        with (out / "file_marks.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle); writer.writerow(["file", "tag", "note"])
            for file_name, tag in marks.items(): writer.writerow([file_name, tag, notes.get(file_name, "")])
        regions = self.session.get("regions", [])
        columns = ["file", "channel", "start_s", "end_s", "tag", "note", "mean", "std", "min", "max", "ptp", "peaks"]
        with (out / "candidate_regions.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle); writer.writerow(columns)
            for region in regions:
                stats = region.get("statistics", {})
                writer.writerow([region.get("file", ""), region.get("channel", ""), region.get("start_s", ""), region.get("end_s", ""), region.get("tag", ""), region.get("note", ""), stats.get("mean", ""), stats.get("std", ""), stats.get("min", ""), stats.get("max", ""), stats.get("ptp", ""), json.dumps(region.get("peaks", []), ensure_ascii=False)])
        (out / "analysis_session.json").write_text(json.dumps(self.session, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot_out = out / "snapshots"; snapshot_out.mkdir(exist_ok=True)
        for region in regions:
            for key in ("time_snapshot", "spectrum_snapshot"):
                source = Path(region.get(key, ""))
                if not source.is_file() and source.name:
                    portable_source = snapshots_dir(str(self.data_folder)) / source.name
                    if portable_source.is_file(): source = portable_source
                    else:
                        source = next((path for path in (app_data_dir() / "snapshots").glob(f"*/{source.name}") if path.is_file()), source)
                if source.is_file(): shutil.copy2(source, snapshot_out / source.name)
        rows = []
        for region in regions:
            peaks = ", ".join(f"{f:.5g} Hz" for f, _ in region.get("peaks", [])[:5])
            rows.append(f"<tr><td>{html.escape(region.get('file_name', ''))}</td><td>{region.get('start_s', 0):.5f}–{region.get('end_s', 0):.5f}</td><td>{html.escape(region.get('tag', ''))}</td><td>{html.escape(peaks)}</td><td>{html.escape(region.get('note', ''))}</td></tr>")
        report = f"""<!doctype html><meta charset='utf-8'><title>TDMS 筛选结果</title>
<style>body{{font-family:Segoe UI,Microsoft YaHei,sans-serif;margin:32px;color:#263238}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd3d8;padding:7px;text-align:left}}th{{background:#eef2f5}}</style>
<h1>TDMS 筛选结果</h1><p>数据文件夹：{html.escape(str(self.data_folder))}</p><p>导出时间：{datetime.now():%Y-%m-%d %H:%M:%S}</p>
<table><tr><th>文件</th><th>区间 (s)</th><th>标签</th><th>主要峰</th><th>备注</th></tr>{''.join(rows)}</table>"""
        (out / "report.html").write_text(report, encoding="utf-8")
        self.statusBar().showMessage(f"筛选结果已导出：{out}", 8000); QMessageBox.information(self, "导出完成", f"筛选结果已保存到：\n{out}")

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

    def apply_plot_theme(self):
        theme = self.plot_theme
        for plot in (self.overview_plot, self.detail_plot, self.spectrum_plot):
            plot.setBackground(theme["background"])
            for axis_name in ("left", "bottom"):
                axis = plot.getAxis(axis_name); axis.setTextPen(theme["foreground"]); axis.setPen(theme["foreground"]); axis.label.setDefaultTextColor(QColor(theme["foreground"]))
        self.overview_plot.setTitle("完整数据总览", color=theme["foreground"]); self.detail_plot.setTitle("局部波形", color=theme["foreground"]); self.spectrum_plot.setTitle("傅里叶变换 / 功率谱", color=theme["foreground"])
        self.overview_curve.setPen(pg.mkPen(theme["time"], width=0.8)); self.detail_curve.setPen(pg.mkPen(theme["time"], width=0.85))
        region = QColor(theme["region"]); fill = QColor(region); fill.setAlpha(48)
        for line in self.region.lines: line.setPen(pg.mkPen(region, width=1.3)); line.setHoverPen(pg.mkPen(region.lighter(135), width=2))
        self.region.setBrush(fill)
        for key, button in self.color_buttons.items():
            color = QColor(theme[key]); text = "#000000" if color.lightness() > 145 else "#FFFFFF"
            button.setStyleSheet(f"background:{color.name()};color:{text};border:1px solid #777;padding:4px")
        self.redraw_spectrum()

    def schedule_session_save(self):
        self.session_timer.start(700)

    def save_session_now(self):
        if self.session is None: return
        try: save_session(self.session)
        except OSError as exc: self.statusBar().showMessage(f"筛选进度保存失败：{exc}", 8000)

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
        self.save_session_now()
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self._save_settings(); event.accept()
